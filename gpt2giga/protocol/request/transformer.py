import base64
import json
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from gigachat import GigaChat
from gigachat.models import (
    ChatV2,
    ChatV2ModelOptions,
    ChatV2Reasoning,
    ChatV2ResponseFormat,
    ChatV2Storage,
    ChatV2Tool,
    ChatV2ToolConfig,
    ChatV2UserInfo,
    FunctionCall,
    Messages,
    MessagesRole,
)

from gpt2giga.common.content_utils import ensure_json_object_str
from gpt2giga.common.json_schema import normalize_json_schema, resolve_schema_refs
from gpt2giga.common.message_utils import (
    collapse_user_messages,
    ensure_system_first,
    limit_attachments,
    map_role,
    merge_consecutive_messages,
)
from gpt2giga.common.tools import (
    convert_tool_to_giga_functions,
    map_tool_name_to_gigachat,
)
from gpt2giga.constants import DEFAULT_MAX_AUDIO_IMAGE_TOTAL_SIZE_BYTES
from gpt2giga.logger import sanitize_for_utf8
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

        extra_body = transformed.pop("extra_body", None)
        additional_fields = transformed.get("additional_fields")
        if isinstance(extra_body, dict):
            if isinstance(additional_fields, dict):
                transformed["additional_fields"] = {**extra_body, **additional_fields}
            elif additional_fields is None:
                transformed["additional_fields"] = extra_body
        elif extra_body is not None and additional_fields is None:
            transformed["additional_fields"] = extra_body

        reasoning = transformed.pop("reasoning", None)
        if isinstance(reasoning, dict):
            effort = reasoning.get("effort")
            if effort is not None:
                transformed["reasoning_effort"] = effort

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

    @staticmethod
    def _invalid_request(
        message: str,
        *,
        param: Optional[str] = None,
        code: Optional[str] = None,
    ) -> HTTPException:
        return HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": message,
                    "type": "invalid_request_error",
                    "param": param,
                    "code": code,
                }
            },
        )

    @staticmethod
    def _merge_additional_fields(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        extra_body = data.get("extra_body")
        additional_fields = data.get("additional_fields")
        if isinstance(extra_body, dict):
            if isinstance(additional_fields, dict):
                return {**extra_body, **additional_fields}
            return dict(extra_body)
        if isinstance(additional_fields, dict):
            return dict(additional_fields)
        if extra_body is not None:
            return extra_body
        return None

    @staticmethod
    def _decode_json_value(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    @staticmethod
    def _normalize_function_result_value(value: Any) -> Dict[str, Any] | str:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                return value
            return (
                decoded
                if isinstance(decoded, dict)
                else json.dumps(decoded, ensure_ascii=False)
            )
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _map_openai_tool_type_to_gigachat(type_: Any) -> Optional[str]:
        mapping = {
            "web_search": "web_search",
            "web_search_2025_08_26": "web_search",
            "web_search_preview": "web_search",
            "web_search_preview_2025_03_11": "web_search",
            "code_interpreter": "code_interpreter",
            "image_generation": "image_generate",
        }
        if not isinstance(type_, str):
            return None
        return mapping.get(type_)

    def _collect_response_tools(
        self,
        tools: List[Dict[str, Any]],
    ) -> tuple[
        Dict[str, Any],
        Dict[str, ChatV2Tool],
        List[Dict[str, Any]],
        Optional[str],
    ]:
        function_specs: Dict[str, Any] = {}
        builtin_tools: Dict[str, ChatV2Tool] = {}
        unsupported_tools: List[Dict[str, Any]] = []
        user_timezone: Optional[str] = None

        for tool in tools:
            if not isinstance(tool, dict):
                continue

            tool_type = tool.get("type")
            if tool_type == "function":
                raw_function = tool.get("function", tool)
                visible_name = raw_function.get("name")
                if not visible_name:
                    continue
                giga_functions = convert_tool_to_giga_functions({"tools": [tool]})
                if giga_functions:
                    function_specs[visible_name] = giga_functions[0]
                else:
                    unsupported_tools.append(tool)
                continue

            giga_tool_name = self._map_openai_tool_type_to_gigachat(tool_type)
            if giga_tool_name == "web_search":
                builtin_tools[giga_tool_name] = ChatV2Tool.web_search_tool()
                user_location = tool.get("user_location")
                if isinstance(user_location, dict):
                    timezone = user_location.get("timezone")
                    if isinstance(timezone, str) and timezone.strip():
                        user_timezone = timezone.strip()
                continue
            if giga_tool_name == "code_interpreter":
                builtin_tools[giga_tool_name] = ChatV2Tool.code_interpreter_tool()
                continue
            if giga_tool_name == "image_generate":
                builtin_tools[giga_tool_name] = ChatV2Tool.image_generate_tool()
                continue

            unsupported_tools.append(tool)

        return function_specs, builtin_tools, unsupported_tools, user_timezone

    def _filter_allowed_response_tools(
        self,
        function_specs: Dict[str, Any],
        builtin_tools: Dict[str, ChatV2Tool],
        allowed_tools: List[Dict[str, Any]],
    ) -> tuple[Dict[str, Any], Dict[str, ChatV2Tool]]:
        allowed_functions: Dict[str, Any] = {}
        allowed_builtins: Dict[str, ChatV2Tool] = {}

        for tool in allowed_tools:
            if not isinstance(tool, dict):
                continue
            if tool.get("type") == "function":
                name = tool.get("name")
                if isinstance(name, str) and name in function_specs:
                    allowed_functions[name] = function_specs[name]
                continue

            giga_tool_name = self._map_openai_tool_type_to_gigachat(tool.get("type"))
            if giga_tool_name and giga_tool_name in builtin_tools:
                allowed_builtins[giga_tool_name] = builtin_tools[giga_tool_name]

        return allowed_functions, allowed_builtins

    def _single_tool_target_config(
        self,
        function_specs: Dict[str, Any],
        builtin_tools: Dict[str, ChatV2Tool],
    ) -> Optional[ChatV2ToolConfig]:
        target_count = len(function_specs) + len(builtin_tools)
        if target_count != 1:
            return None
        if function_specs:
            name = next(iter(function_specs))
            return ChatV2ToolConfig(
                mode="forced",
                function_name=map_tool_name_to_gigachat(name),
            )
        giga_tool_name = next(iter(builtin_tools))
        return ChatV2ToolConfig(mode="forced", tool_name=giga_tool_name)

    def _build_response_tool_config(
        self,
        tool_choice: Any,
        function_specs: Dict[str, Any],
        builtin_tools: Dict[str, ChatV2Tool],
    ) -> Optional[ChatV2ToolConfig]:
        if tool_choice is None:
            return None

        if isinstance(tool_choice, str):
            if tool_choice == "none":
                return ChatV2ToolConfig(mode="none")
            if tool_choice == "auto":
                return ChatV2ToolConfig(mode="auto")
            if tool_choice == "required":
                return self._single_tool_target_config(
                    function_specs,
                    builtin_tools,
                ) or ChatV2ToolConfig(mode="auto")
            return ChatV2ToolConfig(mode="auto")

        if not isinstance(tool_choice, dict):
            return None

        tool_type = tool_choice.get("type")
        if tool_type == "allowed_tools":
            mode = tool_choice.get("mode")
            if mode == "required":
                return self._single_tool_target_config(
                    function_specs,
                    builtin_tools,
                ) or ChatV2ToolConfig(mode="auto")
            return ChatV2ToolConfig(mode="auto")

        if tool_type == "function":
            name = tool_choice.get("name")
            if not isinstance(name, str) or name not in function_specs:
                raise self._invalid_request(
                    f"Unsupported forced tool choice for function {name!r}.",
                    param="tool_choice",
                )
            return ChatV2ToolConfig(
                mode="forced",
                function_name=map_tool_name_to_gigachat(name),
            )

        giga_tool_name = self._map_openai_tool_type_to_gigachat(tool_type)
        if giga_tool_name:
            if giga_tool_name not in builtin_tools:
                raise self._invalid_request(
                    f"Unsupported forced tool choice for tool type {tool_type!r}.",
                    param="tool_choice",
                )
            return ChatV2ToolConfig(mode="forced", tool_name=giga_tool_name)

        raise self._invalid_request(
            f"Unsupported forced tool choice for tool type {tool_type!r}.",
            param="tool_choice",
        )

    def _resolve_response_thread_id(
        self,
        data: Dict[str, Any],
        response_store: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        conversation = data.get("conversation")
        previous_response_id = data.get("previous_response_id")

        if conversation is not None and previous_response_id is not None:
            raise self._invalid_request(
                "`conversation` and `previous_response_id` cannot be used together.",
                param="conversation",
            )

        if conversation is not None:
            if not isinstance(conversation, dict) or not isinstance(
                conversation.get("id"),
                str,
            ):
                raise self._invalid_request(
                    "`conversation.id` must be a string.",
                    param="conversation",
                )
            return conversation["id"]

        if previous_response_id is not None:
            if not isinstance(previous_response_id, str):
                raise self._invalid_request(
                    "`previous_response_id` must be a string.",
                    param="previous_response_id",
                )
            metadata = (
                response_store.get(previous_response_id) if response_store else None
            )
            thread_id = (
                metadata.get("thread_id") if isinstance(metadata, dict) else None
            )
            if not isinstance(thread_id, str) or not thread_id:
                raise self._invalid_request(
                    f"Unknown `previous_response_id`: {previous_response_id}",
                    param="previous_response_id",
                )
            return thread_id

        return None

    async def _upload_response_file_part(
        self,
        giga_client: Optional[GigaChat],
        source: Any,
        *,
        filename: Optional[str] = None,
        size_totals: Optional[Dict[str, int]] = None,
    ) -> Optional[Dict[str, Any]]:
        if source is None:
            return None
        processor = self.attachment_processor
        if processor is None:
            return None
        if giga_client is None:
            self.logger.warning("giga_client not provided for file upload")
            return None

        max_audio_image_total = getattr(
            self.config.proxy_settings,
            "max_audio_image_total_size_bytes",
            DEFAULT_MAX_AUDIO_IMAGE_TOTAL_SIZE_BYTES,
        )
        remaining = max_audio_image_total
        if size_totals is not None:
            remaining = max(
                0,
                max_audio_image_total - size_totals.get("audio_image_total", 0),
            )

        if hasattr(processor, "upload_file_with_meta"):
            upload_result = await processor.upload_file_with_meta(
                giga_client,
                source,
                filename,
                max_audio_image_total_remaining=remaining,
            )
            if not upload_result:
                return None
            if (
                upload_result.file_kind in {"audio", "image"}
                and size_totals is not None
            ):
                size_totals["audio_image_total"] = (
                    size_totals.get("audio_image_total", 0)
                    + upload_result.file_size_bytes
                )
            return {"files": [{"id": upload_result.file_id}]}

        file_id = await processor.upload_file(giga_client, source, filename)
        if not file_id:
            return None
        return {"files": [{"id": file_id}]}

    async def _build_response_v2_content_parts(
        self,
        content: Any,
        giga_client: Optional[GigaChat] = None,
        *,
        size_totals: Optional[Dict[str, int]] = None,
        fallback_function_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if content is None:
            return []
        if isinstance(content, str):
            return [{"text": content}]
        if isinstance(content, dict):
            content = [content]
        if not isinstance(content, list):
            return [{"text": str(content)}]

        result: List[Dict[str, Any]] = []
        pending_multimodal_part: Dict[str, Any] = {}

        def flush_pending_multimodal_part() -> None:
            nonlocal pending_multimodal_part
            if pending_multimodal_part:
                result.append(pending_multimodal_part)
                pending_multimodal_part = {}

        def append_text_to_pending_part(text: str) -> None:
            existing_text = pending_multimodal_part.get("text")
            if isinstance(existing_text, str) and existing_text:
                pending_multimodal_part["text"] = f"{existing_text}\n{text}"
            else:
                pending_multimodal_part["text"] = text

        def append_files_to_pending_part(files_part: Dict[str, Any]) -> None:
            files = files_part.get("files")
            if not isinstance(files, list) or not files:
                return
            pending_multimodal_part.setdefault("files", []).extend(files)

        for content_part in content:
            if not isinstance(content_part, dict):
                continue
            ctype = content_part.get("type")

            if ctype in {"input_text", "output_text", "text"}:
                text = content_part.get("text")
                if text is not None:
                    append_text_to_pending_part(str(text))
                continue

            if ctype in {"input_image", "image_url"}:
                file_id = content_part.get("file_id")
                if isinstance(file_id, str) and file_id:
                    append_files_to_pending_part({"files": [{"id": file_id}]})
                    continue
                image_url = content_part.get("image_url")
                if isinstance(image_url, dict):
                    image_url = image_url.get("url")
                uploaded = await self._upload_response_file_part(
                    giga_client,
                    image_url,
                    size_totals=size_totals,
                )
                if uploaded:
                    append_files_to_pending_part(uploaded)
                continue

            if ctype in {"input_file", "file"}:
                if ctype == "input_file":
                    file_id = content_part.get("file_id")
                    if isinstance(file_id, str) and file_id:
                        append_files_to_pending_part({"files": [{"id": file_id}]})
                        continue
                    source = content_part.get("file_data") or content_part.get(
                        "file_url"
                    )
                    filename = content_part.get("filename")
                else:
                    file_payload = content_part.get("file") or {}
                    file_id = file_payload.get("file_id")
                    if isinstance(file_id, str) and file_id:
                        result.append({"files": [{"id": file_id}]})
                        continue
                    source = file_payload.get("file_data") or file_payload.get(
                        "file_url"
                    )
                    filename = file_payload.get("filename")

                uploaded = await self._upload_response_file_part(
                    giga_client,
                    source,
                    filename=filename,
                    size_totals=size_totals,
                )
                if uploaded:
                    append_files_to_pending_part(uploaded)
                continue

            if ctype == "input_audio":
                input_audio = content_part.get("input_audio") or {}
                audio_data = input_audio.get("data")
                audio_format = input_audio.get("format", "mp3")
                decoded_audio = audio_data
                if isinstance(audio_data, str):
                    try:
                        decoded_audio = base64.b64decode(audio_data)
                    except Exception:
                        decoded_audio = audio_data
                uploaded = await self._upload_response_file_part(
                    giga_client,
                    decoded_audio,
                    filename=f"input.{audio_format}",
                    size_totals=size_totals,
                )
                if uploaded:
                    append_files_to_pending_part(uploaded)
                continue

            if ctype == "function_call":
                flush_pending_multimodal_part()
                name = content_part.get("name")
                if not isinstance(name, str) or not name:
                    continue
                result.append(
                    {
                        "function_call": {
                            "name": map_tool_name_to_gigachat(name),
                            "arguments": self._decode_json_value(
                                content_part.get("arguments"),
                            ),
                        }
                    }
                )
                continue

            if ctype == "function_call_output":
                flush_pending_multimodal_part()
                name = content_part.get("name") or fallback_function_name
                if not isinstance(name, str) or not name:
                    continue
                result.append(
                    {
                        "function_result": {
                            "name": map_tool_name_to_gigachat(name),
                            "result": self._normalize_function_result_value(
                                content_part.get("output"),
                            ),
                        }
                    }
                )
                continue

            if ctype == "refusal":
                text = content_part.get("refusal") or content_part.get("text")
                if text is not None:
                    append_text_to_pending_part(str(text))

        flush_pending_multimodal_part()
        return result

    async def _build_response_v2_messages(
        self,
        data: Dict[str, Any],
        giga_client: Optional[GigaChat] = None,
    ) -> List[Dict[str, Any]]:
        messages: List[Dict[str, Any]] = []
        size_totals = {"audio_image_total": 0}
        system_seen = False
        last_function_name: Optional[str] = None
        last_tools_state_id: Optional[str] = None

        instructions = data.get("instructions")
        if isinstance(instructions, str) and instructions:
            messages.append({"role": "system", "content": [{"text": instructions}]})
            system_seen = True

        input_ = data.get("input")
        if isinstance(input_, str):
            messages.append({"role": "user", "content": [{"text": input_}]})
            return messages
        if not isinstance(input_, list):
            return messages

        for item in input_:
            if not isinstance(item, dict):
                continue

            item_type = item.get("type")
            if item_type == "function_call":
                name = item.get("name") or last_function_name
                if not isinstance(name, str) or not name:
                    continue
                last_function_name = name
                last_tools_state_id = (
                    str(
                        item.get("call_id")
                        or item.get("id")
                        or last_tools_state_id
                        or "",
                    ).strip()
                    or last_tools_state_id
                )
                message = {
                    "role": "assistant",
                    "content": [
                        {
                            "function_call": {
                                "name": map_tool_name_to_gigachat(name),
                                "arguments": self._decode_json_value(
                                    item.get("arguments"),
                                ),
                            }
                        }
                    ],
                }
                if last_tools_state_id:
                    message["tools_state_id"] = last_tools_state_id
                messages.append(message)
                continue

            if item_type == "function_call_output":
                name = item.get("name") or last_function_name
                if not isinstance(name, str) or not name:
                    continue
                tool_state_id = (
                    item.get("call_id") or item.get("id") or last_tools_state_id
                )
                message = {
                    "role": "user",
                    "content": [
                        {
                            "function_result": {
                                "name": map_tool_name_to_gigachat(name),
                                "result": self._normalize_function_result_value(
                                    item.get("output"),
                                ),
                            }
                        }
                    ],
                }
                if tool_state_id:
                    message["tools_state_id"] = str(tool_state_id)
                messages.append(message)
                continue

            if item_type == "reasoning":
                reasoning_chunks: List[str] = []
                summary = item.get("summary")
                if isinstance(summary, list):
                    reasoning_chunks.extend(
                        part.get("text")
                        for part in summary
                        if isinstance(part, dict) and isinstance(part.get("text"), str)
                    )
                content = item.get("content")
                if isinstance(content, list):
                    reasoning_chunks.extend(
                        part.get("text")
                        for part in content
                        if isinstance(part, dict) and isinstance(part.get("text"), str)
                    )
                if reasoning_chunks:
                    messages.append(
                        {
                            "role": "assistant",
                            "content": [{"text": "\n".join(reasoning_chunks)}],
                        }
                    )
                continue

            role = item.get("role")
            if role is None and item_type != "message":
                continue
            role = role or "user"

            if role == "tool":
                name = item.get("name") or last_function_name
                if not isinstance(name, str) or not name:
                    continue
                message = {
                    "role": "user",
                    "content": [
                        {
                            "function_result": {
                                "name": map_tool_name_to_gigachat(name),
                                "result": self._normalize_function_result_value(
                                    item.get("content"),
                                ),
                            }
                        }
                    ],
                }
                if item.get("tool_call_id"):
                    message["tools_state_id"] = str(item["tool_call_id"])
                messages.append(message)
                continue

            mapped_role = self._map_role(role, not system_seen)
            if mapped_role == "system":
                system_seen = True

            content_parts = await self._build_response_v2_content_parts(
                item.get("content"),
                giga_client,
                size_totals=size_totals,
                fallback_function_name=last_function_name,
            )

            tool_calls = item.get("tool_calls")
            if isinstance(tool_calls, list):
                for tool_call in tool_calls:
                    if not isinstance(tool_call, dict):
                        continue
                    function = tool_call.get("function")
                    if not isinstance(function, dict):
                        continue
                    name = function.get("name")
                    if not isinstance(name, str) or not name:
                        continue
                    last_function_name = name
                    last_tools_state_id = (
                        str(
                            tool_call.get("id") or last_tools_state_id or "",
                        ).strip()
                        or last_tools_state_id
                    )
                    content_parts.append(
                        {
                            "function_call": {
                                "name": map_tool_name_to_gigachat(name),
                                "arguments": self._decode_json_value(
                                    function.get("arguments"),
                                ),
                            }
                        }
                    )

            if not content_parts:
                continue

            message: Dict[str, Any] = {
                "role": mapped_role,
                "content": content_parts,
            }

            tools_state_id = (
                item.get("tools_state_id")
                or item.get("tool_state_id")
                or item.get("call_id")
                or item.get("id")
            )
            if isinstance(tools_state_id, str) and tools_state_id:
                message["tools_state_id"] = tools_state_id

            messages.append(message)

        return messages

    def _build_response_v2_model_options(
        self,
        data: Dict[str, Any],
    ) -> Optional[ChatV2ModelOptions]:
        options: Dict[str, Any] = {}

        temperature = data.get("temperature")
        if temperature == 0:
            options["top_p"] = 0
        elif isinstance(temperature, (int, float)) and temperature > 0:
            options["temperature"] = float(temperature)

        top_p = data.get("top_p")
        if top_p is not None and temperature != 0:
            options["top_p"] = top_p

        max_output_tokens = data.get("max_output_tokens")
        if max_output_tokens is not None:
            options["max_tokens"] = max_output_tokens

        top_logprobs = data.get("top_logprobs")
        if top_logprobs is not None:
            options["top_logprobs"] = top_logprobs

        reasoning = data.get("reasoning")
        if isinstance(reasoning, dict):
            effort = reasoning.get("effort")
            if effort in {"low", "medium", "high"}:
                options["reasoning"] = ChatV2Reasoning(effort=effort)
        elif getattr(self.config.proxy_settings, "enable_reasoning", False):
            options["reasoning"] = ChatV2Reasoning(effort="high")

        text_config = data.get("text")
        if isinstance(text_config, dict):
            response_format = text_config.get("format")
            if isinstance(response_format, dict):
                format_type = response_format.get("type")
                if format_type == "text":
                    options["response_format"] = ChatV2ResponseFormat(type="text")
                elif format_type == "json_schema":
                    schema_holder = response_format.get("json_schema")
                    if isinstance(schema_holder, dict):
                        schema = schema_holder.get("schema")
                        strict = schema_holder.get(
                            "strict", response_format.get("strict")
                        )
                    else:
                        schema = response_format.get("schema")
                        strict = response_format.get("strict")
                    if not isinstance(schema, dict):
                        raise self._invalid_request(
                            "`text.format.schema` must be an object for json_schema responses.",
                            param="text",
                        )
                    options["response_format"] = ChatV2ResponseFormat(
                        type="json_schema",
                        schema=normalize_json_schema(resolve_schema_refs(schema)),
                        strict=strict,
                    )

        return ChatV2ModelOptions(**options) if options else None

    async def prepare_response_v2(
        self,
        data: dict,
        giga_client: Optional[GigaChat] = None,
        response_store: Optional[Dict[str, Any]] = None,
    ) -> ChatV2:
        """Prepares request for Responses API using native GigaChat v2 payloads."""
        request_data = data.copy()

        function_specs, builtin_tools, _unsupported_tools, user_timezone = (
            self._collect_response_tools(request_data.get("tools", []) or [])
        )

        tool_choice = request_data.get("tool_choice")
        if isinstance(tool_choice, dict) and tool_choice.get("type") == "allowed_tools":
            function_specs, builtin_tools = self._filter_allowed_response_tools(
                function_specs,
                builtin_tools,
                tool_choice.get("tools", []) or [],
            )

        tool_config = self._build_response_tool_config(
            tool_choice,
            function_specs,
            builtin_tools,
        )

        tools_payload: List[ChatV2Tool] = []
        if function_specs:
            tools_payload.append(
                ChatV2Tool.functions_tool(specifications=list(function_specs.values()))
            )
        tools_payload.extend(builtin_tools.values())

        thread_id = self._resolve_response_thread_id(request_data, response_store)
        storage: ChatV2Storage | bool | None
        if thread_id:
            storage = ChatV2Storage(thread_id=thread_id)
        else:
            storage = None

        payload: Dict[str, Any] = {
            "messages": await self._build_response_v2_messages(
                request_data,
                giga_client,
            ),
            "stream": bool(request_data.get("stream", False)),
            "additional_fields": self._merge_additional_fields(request_data),
        }
        if storage is not None:
            payload["storage"] = storage

        if not payload["messages"]:
            raise self._invalid_request(
                "Request must include at least one input item.",
                param="input",
            )

        model_options = self._build_response_v2_model_options(request_data)
        if model_options is not None:
            payload["model_options"] = model_options

        if tools_payload:
            payload["tools"] = tools_payload
        if tool_config is not None:
            payload["tool_config"] = tool_config
        if user_timezone:
            payload["user_info"] = ChatV2UserInfo(timezone=user_timezone)

        gpt_model = request_data.get("model")
        if self.config.proxy_settings.pass_model and gpt_model:
            payload["model"] = gpt_model

        sanitized_payload = sanitize_for_utf8(
            {
                key: value.model_dump(exclude_none=True, by_alias=True)
                if hasattr(value, "model_dump")
                else value
                for key, value in payload.items()
                if value is not None
            }
        )
        return ChatV2.model_validate(sanitized_payload)

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

        return sanitize_for_utf8(transformed_data)

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
