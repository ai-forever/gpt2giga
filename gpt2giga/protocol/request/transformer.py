import json
from typing import Any, Dict, List, Optional, Tuple

from gigachat import GigaChat
from gigachat.models import FunctionCall, Messages, MessagesRole

from gpt2giga.common.content_utils import ensure_json_object_str
from gpt2giga.common.json_schema import normalize_json_schema, resolve_schema_refs
from gpt2giga.common.message_utils import (
    collapse_user_messages,
    ensure_system_first,
    limit_attachments,
    map_role,
    merge_consecutive_messages,
)
from gpt2giga.common.tools import map_tool_name_to_gigachat
from gpt2giga.constants import DEFAULT_MAX_AUDIO_IMAGE_TOTAL_SIZE_BYTES
from gpt2giga.models.config import ProxyConfig
from gpt2giga.protocol.attachment.attachments import AttachmentProcessor


class RequestTransformer:
    """Transformer for converting OpenAI requests to GigaChat format."""

    def __init__(
        self,
        config: ProxyConfig,
        logger,
        attachment_processor: Optional[AttachmentProcessor] = None,
    ):
        self.config = config
        self.logger = logger
        self.attachment_processor = attachment_processor

    def _map_role(self, role: str, is_first: bool) -> str:
        """Maps a role to a valid GigaChat role."""
        return map_role(role, is_first, self.logger)

    def _merge_consecutive_messages(self, messages: List[Dict]) -> List[Dict]:
        """Merges consecutive messages with the same role."""
        return merge_consecutive_messages(messages)

    def _limit_attachments(self, messages: List[Dict]) -> None:
        """Limits the number of attachments in messages."""
        limit_attachments(messages, max_total=10, logger=self.logger)

    async def transform_messages(
        self, messages: List[Dict], giga_client: Optional[GigaChat] = None
    ) -> List[Dict]:
        """Transforms messages to GigaChat format."""
        transformed_messages = []
        attachment_count = 0
        system_message = None

        size_totals = {"audio_image_total": 0}

        for i, message in enumerate(messages):
            self.logger.debug(f"Processing message {i}: role={message.get('role')}")

            original_role = message.get("role", "user")

            # Map role to valid GigaChat role
            # For system detection, we consider it "first" if we haven't seen a system yet
            is_first_for_system = system_message is None
            message["role"] = self._map_role(original_role, is_first_for_system)

            # Track the first system message
            if message["role"] == "system" and system_message is None:
                system_message = message

            # Handle tool/function role specifics
            if original_role == "tool":
                message["content"] = ensure_json_object_str(message.get("content"))
                if message.get("name"):
                    message["name"] = map_tool_name_to_gigachat(message["name"])
            else:
                # Remove unused fields
                message.pop("name", None)

            # Process content
            if message.get("content") is None:
                message["content"] = ""

            # Process tool_calls
            if "tool_calls" in message and message["tool_calls"]:
                message["function_call"] = message["tool_calls"][0]["function"]
                if isinstance(message.get("function_call"), dict) and message[
                    "function_call"
                ].get("name"):
                    message["function_call"]["name"] = map_tool_name_to_gigachat(
                        message["function_call"]["name"]
                    )
                try:
                    message["function_call"]["arguments"] = json.loads(
                        message["function_call"]["arguments"]
                    )
                except json.JSONDecodeError as e:
                    self.logger.warning(f"Failed to parse function call arguments: {e}")
            elif (
                message.get("function_call")
                and isinstance(message["function_call"], dict)
                and message["function_call"].get("name")
            ):
                message["function_call"]["name"] = map_tool_name_to_gigachat(
                    message["function_call"]["name"]
                )

            # Process compound content (text + images/files)
            if isinstance(message["content"], list):
                texts, attachments = await self._process_content_parts(
                    message["content"], giga_client, size_totals
                )
                message["content"] = "\n".join(texts)
                message["attachments"] = attachments
                attachment_count += len(attachments)

            transformed_messages.append(message)

        # Merge consecutive messages with the same role
        transformed_messages = self._merge_consecutive_messages(transformed_messages)

        # Ensure system message is first
        transformed_messages = ensure_system_first(transformed_messages)

        # Check attachment limits
        if attachment_count > 10:
            limit_attachments(transformed_messages, max_total=10, logger=self.logger)

        return transformed_messages

    async def _process_content_parts(
        self,
        content_parts: List[Dict],
        giga_client: Optional[GigaChat] = None,
        size_totals: Optional[Dict[str, int]] = None,
    ) -> Tuple[List[str], List[str]]:
        """Processes content parts (text and images/files)."""
        texts = []
        attachments: List[str] = []
        max_attachments = 2

        processor = self.attachment_processor
        enable_images = getattr(self.config.proxy_settings, "enable_images", False)
        max_audio_image_total = getattr(
            self.config.proxy_settings,
            "max_audio_image_total_size_bytes",
            DEFAULT_MAX_AUDIO_IMAGE_TOTAL_SIZE_BYTES,
        )
        logger = self.logger

        for content_part in content_parts:
            ctype = content_part.get("type")
            if ctype == "text":
                texts.append(content_part.get("text", ""))
            elif (
                ctype == "image_url"
                and processor is not None
                and enable_images
                and content_part.get("image_url")
                and len(attachments) < max_attachments
            ):
                url = content_part["image_url"].get("url")
                if url is not None:
                    if giga_client:
                        if hasattr(processor, "upload_file_with_meta"):
                            remaining = max_audio_image_total
                            if size_totals is not None:
                                remaining = max(
                                    0,
                                    max_audio_image_total
                                    - size_totals.get("audio_image_total", 0),
                                )
                            upload_result = await processor.upload_file_with_meta(
                                giga_client,
                                url,
                                max_audio_image_total_remaining=remaining,
                            )
                            if upload_result:
                                attachments.append(upload_result.file_id)
                                if (
                                    upload_result.file_kind in {"audio", "image"}
                                    and size_totals is not None
                                ):
                                    size_totals["audio_image_total"] = (
                                        size_totals.get("audio_image_total", 0)
                                        + upload_result.file_size_bytes
                                    )
                                logger.info(
                                    f"Added attachment: {upload_result.file_id}"
                                )
                        else:
                            file_id = await processor.upload_file(giga_client, url)
                            if file_id:
                                attachments.append(file_id)
                                logger.info(f"Added attachment: {file_id}")
                    else:
                        logger.warning("giga_client not provided for image upload")

            elif ctype == "file" and processor is not None and content_part.get("file"):
                filename = content_part["file"].get("filename")
                file_data = content_part["file"].get("file_data")
                if giga_client:
                    if hasattr(processor, "upload_file_with_meta"):
                        remaining = max_audio_image_total
                        if size_totals is not None:
                            remaining = max(
                                0,
                                max_audio_image_total
                                - size_totals.get("audio_image_total", 0),
                            )
                        upload_result = await processor.upload_file_with_meta(
                            giga_client,
                            file_data,
                            filename,
                            max_audio_image_total_remaining=remaining,
                        )
                        if upload_result:
                            attachments.append(upload_result.file_id)
                            if (
                                upload_result.file_kind in {"audio", "image"}
                                and size_totals is not None
                            ):
                                size_totals["audio_image_total"] = (
                                    size_totals.get("audio_image_total", 0)
                                    + upload_result.file_size_bytes
                                )
                            logger.info(f"Added attachment: {upload_result.file_id}")
                    else:
                        file_id = await processor.upload_file(
                            giga_client, file_data, filename
                        )
                        if file_id:
                            attachments.append(file_id)
                            logger.info(f"Added attachment: {file_id}")
                else:
                    logger.warning("giga_client not provided for file upload")

        if len(attachments) > max_attachments:
            logger.warning(
                "GigaChat can only handle 2 images per message. Cutting off excess."
            )
            attachments = attachments[:max_attachments]

        return texts, attachments

    def _transform_common_parameters(self, data: Dict) -> Dict:
        """Common parameter transformation logic for Chat Completions and Responses API."""
        transformed = data.copy()

        if getattr(self.config.proxy_settings, "enable_reasoning", False):
            transformed.setdefault("reasoning_effort", "high")

        gpt_model = data.get("model", None)
        if not self.config.proxy_settings.pass_model and gpt_model:
            del transformed["model"]

        temperature = transformed.pop("temperature", 0)
        if temperature == 0:
            transformed["top_p"] = 0
        elif temperature > 0:
            transformed["temperature"] = temperature

        max_tokens = transformed.pop("max_output_tokens", None)
        if max_tokens:
            transformed["max_tokens"] = max_tokens

        if "functions" not in transformed and "tools" in transformed:
            functions = []
            for tool in transformed["tools"]:
                if tool["type"] == "function":
                    functions.append(tool.get("function", tool))
            transformed["functions"] = functions
            self.logger.debug(f"Transformed {len(functions)} tools to functions")

        # Map reserved tool names to safe aliases for GigaChat
        function_call = transformed.get("function_call")
        if isinstance(function_call, dict) and function_call.get("name"):
            function_call["name"] = map_tool_name_to_gigachat(function_call["name"])

        functions_list = transformed.get("functions")
        if isinstance(functions_list, list):
            for fn in functions_list:
                if isinstance(fn, dict) and fn.get("name"):
                    fn["name"] = map_tool_name_to_gigachat(fn["name"])
                elif hasattr(fn, "name") and getattr(fn, "name", None):
                    setattr(fn, "name", map_tool_name_to_gigachat(getattr(fn, "name")))

        return transformed

    @staticmethod
    def _apply_json_schema_as_function(
        transformed: Dict, schema_name: str, schema: Dict
    ) -> None:
        """Applies JSON schema as function call for structured output."""
        resolved_schema = resolve_schema_refs(schema)
        resolved_schema = normalize_json_schema(resolved_schema)

        function_def = {
            "name": schema_name,
            "description": f"Output response in structured format: {schema_name}",
            "parameters": resolved_schema,
        }

        if "functions" not in transformed:
            transformed["functions"] = []

        transformed["functions"].append(function_def)
        transformed["function_call"] = {"name": schema_name}

    def transform_chat_parameters(self, data: Dict) -> Dict:
        """Transforms chat parameters (Chat Completions API)."""
        transformed = self._transform_common_parameters(data)

        response_format: dict | None = transformed.pop("response_format", None)
        if response_format:
            if response_format.get("type") == "json_schema":
                json_schema = response_format.get("json_schema", {})
                schema_name = json_schema.get("name", "structured_output")
                schema = json_schema.get("schema")
                self._apply_json_schema_as_function(transformed, schema_name, schema)
            else:
                transformed["response_format"] = {
                    "type": response_format.get("type"),
                    **response_format.get("json_schema", {}),
                }

        return transformed

    def transform_responses_parameters(self, data: Dict) -> Dict:
        """Transforms responses parameters (Responses API)."""
        transformed = self._transform_common_parameters(data)

        response_format_responses: dict | None = transformed.pop("text", None)
        if response_format_responses:
            response_format = response_format_responses.get("format", {})
            if response_format.get("type") == "json_schema":
                if "json_schema" in response_format:
                    json_schema = response_format.get("json_schema", {})
                    schema_name = json_schema.get("name", "structured_output")
                    schema = json_schema.get("schema")
                else:
                    schema_name = response_format.get("name", "structured_output")
                    schema = response_format.get("schema")
                self._apply_json_schema_as_function(transformed, schema_name, schema)
            else:
                transformed["response_format"] = response_format

        return transformed

    def transform_response_format(self, data: Dict) -> List:
        """Transforms response format for Responses API input."""
        message_payload = []
        if "instructions" in data:
            message_payload.append({"role": "system", "content": data["instructions"]})
            del data["instructions"]
        input_ = data["input"]
        del data["input"]
        if isinstance(input_, str):
            message_payload.append({"role": "user", "content": input_})

        elif isinstance(input_, list):
            last_function_name: Optional[str] = None
            for message in input_:
                message_type = message.get("type")
                if message_type == "function_call_output":
                    fn_name = message.get("name") or last_function_name
                    fn_name = map_tool_name_to_gigachat(fn_name) if fn_name else fn_name
                    message_payload.append(
                        {
                            "role": "function",
                            "name": fn_name,
                            "content": ensure_json_object_str(message.get("output")),
                        }
                    )
                    continue
                if message_type == "function_call":
                    last_function_name = message.get("name") or last_function_name
                    message_payload.append(self.mock_completion(message))
                    continue

                role = message.get("role")
                if role:
                    content = message.get("content")
                    if isinstance(content, list):
                        contents = []
                        append = contents.append
                        for content_part in content:
                            ctype = content_part.get("type")
                            if ctype == "input_text":
                                append(
                                    {
                                        "type": "text",
                                        "text": content_part.get("text"),
                                    }
                                )
                            elif ctype == "input_image":
                                append(
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": content_part.get("image_url")
                                        },
                                    }
                                )

                        message_payload.append({"role": role, "content": contents})
                    else:
                        message_payload.append({"role": role, "content": content})
        return message_payload

    @staticmethod
    def mock_completion(message: dict) -> dict:
        """Creates a mock completion message for function calls."""
        arguments = json.loads(message.get("arguments"))
        name = map_tool_name_to_gigachat(message.get("name"))
        return Messages(
            role=MessagesRole.ASSISTANT,
            function_call=FunctionCall(name=name, arguments=arguments),
        ).model_dump()

    async def _finalize_transformation(
        self, transformed_data: dict, giga_client: Optional[GigaChat] = None
    ) -> Dict[str, Any]:
        """Common logic for message transformation and logging."""
        transformed_data["messages"] = await self.transform_messages(
            transformed_data.get("messages", []), giga_client
        )

        messages_objs = [
            Messages.model_validate(m) for m in transformed_data["messages"]
        ]
        collapsed_objs = collapse_user_messages(messages_objs)
        transformed_data["messages"] = [
            m.model_dump(exclude_none=True) for m in collapsed_objs
        ]

        if self.config.proxy_settings.mode == "PROD":
            self.logger.bind(event="gigachat_request").debug(
                "Sending request to GigaChat API (payload omitted in PROD)"
            )
        else:
            msg_count = len(transformed_data.get("messages", []))
            has_functions = bool(transformed_data.get("functions"))
            self.logger.bind(
                event="gigachat_request",
                message_count=msg_count,
                has_functions=has_functions,
            ).debug(
                f"Sending request to GigaChat API: "
                f"{msg_count} messages, functions={has_functions}"
            )

        return transformed_data

    async def prepare_chat_completion(
        self, data: dict, giga_client: Optional[GigaChat] = None
    ) -> Dict[str, Any]:
        """Prepares request for Chat Completions API."""
        transformed_data = self.transform_chat_parameters(data)
        return await self._finalize_transformation(transformed_data, giga_client)

    async def prepare_response(
        self, data: dict, giga_client: Optional[GigaChat] = None
    ) -> Dict[str, Any]:
        """Prepares request for Responses API."""
        transformed_data = self.transform_responses_parameters(data)
        transformed_data["messages"] = self.transform_response_format(transformed_data)
        return await self._finalize_transformation(transformed_data, giga_client)

    # Backward-compatible API (used by older tests / integrations)
    async def send_to_gigachat(
        self, data: dict, giga_client: Optional[GigaChat] = None
    ) -> Dict[str, Any]:
        """Backward-compatible alias for Chat Completions payload preparation."""
        return await self.prepare_chat_completion(data, giga_client)

    async def send_to_gigachat_responses(
        self, data: dict, giga_client: Optional[GigaChat] = None
    ) -> Dict[str, Any]:
        """Backward-compatible alias for Responses API payload preparation."""
        return await self.prepare_response(data, giga_client)
