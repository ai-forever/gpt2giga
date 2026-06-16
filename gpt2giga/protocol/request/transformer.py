import json
from collections.abc import Mapping
from typing import Any, Dict, List, Optional, Tuple

from gigachat import GigaChat
from gigachat.models import (
    ChatCompletionRequest,
    ChatFunctionSpecification,
    ChatMessage,
    ChatModelOptions,
    ChatTool,
    FunctionCall,
    Messages,
    MessagesRole,
)

from gpt2giga.common.client_params import ClientCompatibilityError
from gpt2giga.common.content_utils import ensure_json_object_str
from gpt2giga.common.debug_logging import log_debug_payload
from gpt2giga.common.json_schema import (
    normalize_json_schema,
    normalize_tool_parameters_schema,
    resolve_schema_refs,
)
from gpt2giga.common.message_utils import (
    collapse_user_messages,
    ensure_system_first,
    limit_attachments,
    map_role,
    merge_consecutive_messages,
)
from gpt2giga.common.tools import (
    build_gigachat_builtin_tool_payload,
    iter_function_tool_payloads,
    map_tool_name_to_gigachat,
    normalize_gigachat_function_definitions,
)
from gpt2giga.constants import DEFAULT_MAX_AUDIO_IMAGE_TOTAL_SIZE_BYTES
from gpt2giga.models.config import ProxyConfig
from gpt2giga.protocol.attachment.attachments import AttachmentProcessor
from gpt2giga.protocol.request.params import (
    sanitize_openai_chat_parameters,
    sanitize_openai_responses_parameters,
)


class RequestTransformer:
    """Transformer for converting OpenAI requests to GigaChat format."""

    _CHAT_COMPLETION_REQUEST_FIELDS = set(ChatCompletionRequest.model_fields)
    _CHAT_COMPLETION_MODEL_OPTION_FIELDS = set(ChatModelOptions.model_fields)

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
        pending_tool_calls: list[tuple[str, Optional[str]]] = []
        tool_name_by_call_id: dict[str, str] = {}

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
            if original_role in {"tool", "function"}:
                tool_call_id = self._extract_tool_call_id(message)
                function_name = self._resolve_tool_result_name(
                    message,
                    tool_call_id,
                    pending_tool_calls,
                    tool_name_by_call_id,
                )
                if function_name and not message.get("name"):
                    message["name"] = function_name
                self._set_backend_state_id(message, tool_call_id)
                message["content"] = ensure_json_object_str(message.get("content"))
                if message.get("name"):
                    message["name"] = map_tool_name_to_gigachat(message["name"])
            else:
                # Remove unused fields
                message.pop("name", None)

            # Process content
            if message.get("content") is None:
                message["content"] = ""

            if (
                isinstance(message.get("content"), list)
                and original_role == "assistant"
            ):
                (
                    extracted_function_call,
                    remaining_content,
                ) = self._extract_legacy_content_function_call(message["content"])
                if (
                    extracted_function_call is not None
                    and message.get("function_call") is None
                ):
                    message["function_call"] = extracted_function_call
                message["content"] = remaining_content

            # Process tool_calls
            if "tool_calls" in message and message["tool_calls"]:
                tool_call = message["tool_calls"][0]
                if isinstance(tool_call, dict):
                    tool_call_id = self._extract_tool_call_id(tool_call)
                    self._set_backend_state_id(message, tool_call_id)
                    message["function_call"] = tool_call.get("function")
                    if isinstance(message.get("function_call"), dict):
                        self._normalize_message_function_call(message["function_call"])
                        self._track_pending_tool_call(
                            message["function_call"],
                            tool_call_id,
                            pending_tool_calls,
                            tool_name_by_call_id,
                        )
                elif isinstance(message.get("function_call"), dict):
                    self._normalize_message_function_call(message["function_call"])
                    self._track_pending_tool_call(
                        message["function_call"],
                        self._extract_tool_call_id(message),
                        pending_tool_calls,
                        tool_name_by_call_id,
                    )
            elif (
                message.get("function_call")
                and isinstance(message["function_call"], dict)
                and message["function_call"].get("name")
            ):
                tool_call_id = self._extract_tool_call_id(message)
                self._set_backend_state_id(message, tool_call_id)
                self._normalize_message_function_call(message["function_call"])
                self._track_pending_tool_call(
                    message["function_call"],
                    tool_call_id,
                    pending_tool_calls,
                    tool_name_by_call_id,
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

    def _normalize_message_function_call(self, function_call: Dict[str, Any]) -> None:
        name = function_call.get("name")
        if name:
            function_call["name"] = map_tool_name_to_gigachat(name)

        arguments = function_call.get("arguments")
        if not isinstance(arguments, str):
            return

        try:
            function_call["arguments"] = json.loads(arguments)
        except json.JSONDecodeError as e:
            self.logger.warning(f"Failed to parse function call arguments: {e}")

    @staticmethod
    def _extract_legacy_content_function_call(
        content: List[Dict[str, Any]],
    ) -> tuple[Optional[dict], List[Dict[str, Any]]]:
        """Extract first legacy content function_call block and return remaining content."""
        function_call = None
        remaining: List[Dict[str, Any]] = []

        for item in content:
            if (
                function_call is None
                and isinstance(item, dict)
                and isinstance(item.get("function_call"), dict)
                and item["function_call"].get("name")
            ):
                function_call = item["function_call"]
                continue
            if isinstance(item, dict):
                remaining.append(item)

        return function_call, remaining

    @staticmethod
    def _extract_tool_call_id(message: Dict[str, Any]) -> Optional[str]:
        for field_name in (
            "tool_call_id",
            "tools_state_id",
            "tool_state_id",
            "functions_state_id",
            "function_state_id",
            "call_id",
            "id",
        ):
            value = message.get(field_name)
            normalized = RequestTransformer._normalize_backend_state_id(value)
            if normalized:
                return normalized
        return None

    @staticmethod
    def _normalize_backend_state_id(value: Any) -> Optional[str]:
        if not isinstance(value, str):
            return None
        state_id = value.strip()
        if not state_id:
            return None
        for prefix in ("fc_", "call_"):
            if state_id.startswith(prefix) and len(state_id) > len(prefix):
                return state_id.removeprefix(prefix)
        return state_id

    @classmethod
    def _set_backend_state_id(
        cls,
        message: Dict[str, Any],
        state_id: Optional[str],
    ) -> None:
        normalized = cls._normalize_backend_state_id(state_id)
        if not normalized:
            return
        if not cls._normalize_backend_state_id(message.get("tools_state_id")):
            message["tools_state_id"] = normalized
        if not cls._normalize_backend_state_id(message.get("functions_state_id")):
            message["functions_state_id"] = normalized

    @staticmethod
    def _track_pending_tool_call(
        function_call: Dict[str, Any],
        tool_call_id: Optional[str],
        pending_tool_calls: list[tuple[str, Optional[str]]],
        tool_name_by_call_id: dict[str, str],
    ) -> None:
        name = function_call.get("name")
        if not isinstance(name, str) or not name:
            return
        pending_tool_calls.append((name, tool_call_id))
        if tool_call_id:
            tool_name_by_call_id[tool_call_id] = name

    @staticmethod
    def _resolve_tool_result_name(
        message: Dict[str, Any],
        tool_call_id: Optional[str],
        pending_tool_calls: list[tuple[str, Optional[str]]],
        tool_name_by_call_id: dict[str, str],
    ) -> Optional[str]:
        name = message.get("name")
        if isinstance(name, str) and name:
            return name

        if tool_call_id:
            mapped_name = tool_name_by_call_id.get(tool_call_id)
            if mapped_name:
                pending_tool_calls[:] = [
                    item for item in pending_tool_calls if item[1] != tool_call_id
                ]
                return mapped_name

        if pending_tool_calls:
            pending_name, pending_call_id = pending_tool_calls.pop(0)
            if pending_call_id and not tool_call_id:
                RequestTransformer._set_backend_state_id(message, pending_call_id)
            return pending_name

        return None

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

        transformed.pop("extra_headers", None)
        transformed.pop("extra_query", None)

        extra_body = transformed.pop("extra_body", None)
        additional_fields = transformed.get("additional_fields")
        if isinstance(extra_body, dict):
            if isinstance(additional_fields, dict):
                transformed["additional_fields"] = {**extra_body, **additional_fields}
            elif additional_fields is None:
                transformed["additional_fields"] = extra_body
        elif extra_body is not None and additional_fields is None:
            transformed["additional_fields"] = extra_body

        disable_reasoning = getattr(
            self.config.proxy_settings, "disable_reasoning", False
        )
        reasoning = transformed.pop("reasoning", None)
        if disable_reasoning:
            transformed.pop("reasoning_effort", None)
            additional_fields = transformed.get("additional_fields")
            if isinstance(additional_fields, dict):
                additional_fields = self._strip_reasoning_payload_fields(
                    additional_fields
                )
                if additional_fields:
                    transformed["additional_fields"] = additional_fields
                else:
                    transformed.pop("additional_fields", None)
        elif isinstance(reasoning, dict):
            effort = reasoning.get("effort")
            if effort is not None:
                transformed["reasoning_effort"] = effort

        if not disable_reasoning and getattr(
            self.config.proxy_settings, "enable_reasoning", False
        ):
            transformed.setdefault("reasoning_effort", "high")

        gpt_model = data.get("model", None)
        if not self.config.proxy_settings.pass_model and gpt_model:
            del transformed["model"]

        temperature = transformed.pop("temperature", None)
        if temperature is not None:
            if temperature == 0:
                transformed["top_p"] = 0
            elif temperature > 0:
                transformed["temperature"] = temperature

        max_tokens = transformed.pop("max_output_tokens", None)
        if max_tokens:
            transformed["max_tokens"] = max_tokens

        # Apply default max_tokens if configured and none was provided by the client.
        default_max_tokens = self.config.proxy_settings.default_max_tokens
        if "max_tokens" not in transformed and default_max_tokens is not None:
            transformed["max_tokens"] = default_max_tokens

        if "functions" not in transformed and "tools" in transformed:
            functions = list(
                iter_function_tool_payloads(
                    {"tools": transformed["tools"]},
                    require_parameters=False,
                )
            )
            transformed["functions"] = functions
            self.logger.debug(f"Transformed {len(functions)} tools to functions")

        if "functions" in transformed:
            transformed["functions"] = self._normalize_legacy_functions(
                transformed["functions"]
            )

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
    def _normalize_legacy_functions(functions: Any) -> Any:
        """Normalize legacy function schemas before GigaChat Chat validation."""
        if not isinstance(functions, list):
            return functions

        normalized_functions = []
        for function in functions:
            if hasattr(function, "model_dump"):
                function_payload = function.model_dump(exclude_none=True, by_alias=True)
            elif isinstance(function, Mapping):
                function_payload = dict(function)
            else:
                normalized_functions.append(function)
                continue

            parameters = function_payload.get("parameters")
            if isinstance(parameters, dict):
                function_payload["parameters"] = normalize_json_schema(
                    resolve_schema_refs(parameters)
                )
            normalized_functions.append(function_payload)

        return normalized_functions

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
    def _extract_json_schema_response_format(
        response_format: Dict,
    ) -> tuple[str, Dict, Optional[bool]]:
        """Extract schema metadata from OpenAI chat/responses JSON schema formats."""
        if "json_schema" in response_format:
            json_schema = response_format.get("json_schema") or {}
            schema_name = json_schema.get("name", "structured_output")
            schema = json_schema.get("schema")
            strict = json_schema.get("strict", response_format.get("strict"))
            return schema_name, schema, strict

        return (
            response_format.get("name", "structured_output"),
            response_format.get("schema"),
            response_format.get("strict"),
        )

    @staticmethod
    def _apply_json_schema_natively(
        transformed: Dict, schema: Dict, strict: Optional[bool]
    ) -> None:
        """Applies JSON schema through GigaChat native response_format."""
        schema = (
            normalize_json_schema(resolve_schema_refs(schema))
            if isinstance(schema, dict)
            else {}
        )
        response_format = {"type": "json_schema", "schema": schema}
        if strict is not None:
            response_format["strict"] = strict
        transformed["response_format"] = response_format

    @staticmethod
    def _reject_json_object_response_format(param: str) -> None:
        raise ClientCompatibilityError(
            "GigaChat does not support response_format.type='json_object'. "
            "Use response_format.type='json_schema' with a schema.",
            provider="openai",
            param=param,
            code="unsupported_response_format",
        )

    def _structured_output_mode(self) -> str:
        return getattr(
            self.config.proxy_settings,
            "structured_output_mode",
            "function_call",
        )

    def _responses_chat_completion_tools_enabled_by_default(self) -> bool:
        return getattr(self.config.proxy_settings, "gigachat_api_mode", "v1") == "v2"

    @staticmethod
    def _strip_reasoning_payload_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
        stripped = {
            key: value
            for key, value in payload.items()
            if key not in {"reasoning", "reasoning_effort"}
        }
        model_options = stripped.get("model_options")
        if isinstance(model_options, dict):
            model_options = {
                key: value
                for key, value in model_options.items()
                if key not in {"reasoning", "reasoning_effort"}
            }
            if model_options:
                stripped["model_options"] = model_options
            else:
                stripped.pop("model_options", None)
        return stripped

    def _chat_completion_tools_enabled_by_default(self) -> bool:
        return getattr(self.config.proxy_settings, "gigachat_api_mode", "v1") == "v2"

    def transform_chat_parameters(
        self, data: Dict, *, allow_builtin_tools: Optional[bool] = None
    ) -> Dict:
        """Transforms chat parameters (Chat Completions API)."""
        builtin_tools_enabled = (
            self._chat_completion_tools_enabled_by_default()
            if allow_builtin_tools is None
            else allow_builtin_tools
        )
        data = sanitize_openai_chat_parameters(
            data,
            allow_builtin_tools=builtin_tools_enabled,
            allow_namespace_tools=builtin_tools_enabled,
        )
        data = self._map_chat_token_limit(data)
        transformed = self._transform_common_parameters(data)
        if builtin_tools_enabled:
            builtin_tools = self._build_chat_completion_builtin_tool_payloads(
                data.get("tools")
            )
            if builtin_tools:
                transformed["_gpt2giga_builtin_tools"] = builtin_tools

        response_format: dict | None = transformed.pop("response_format", None)
        if response_format:
            if response_format.get("type") == "json_schema":
                schema_name, schema, strict = self._extract_json_schema_response_format(
                    response_format
                )
                if self._structured_output_mode() == "native":
                    self._apply_json_schema_natively(transformed, schema, strict)
                else:
                    self._apply_json_schema_as_function(
                        transformed, schema_name, schema
                    )
            elif response_format.get("type") == "json_object":
                self._reject_json_object_response_format("response_format.type")
            else:
                transformed["response_format"] = {
                    "type": response_format.get("type"),
                    **response_format.get("json_schema", {}),
                }

        return transformed

    @staticmethod
    def _map_chat_token_limit(data: Dict) -> Dict:
        """Map OpenAI Chat max_completion_tokens to GigaChat max_tokens."""
        if "max_completion_tokens" not in data:
            return data

        transformed = data.copy()
        max_completion_tokens = transformed.pop("max_completion_tokens")
        if max_completion_tokens is None:
            return transformed

        for conflict_param in ("max_tokens", "max_output_tokens"):
            if transformed.get(conflict_param) is not None:
                return transformed

        transformed["max_tokens"] = max_completion_tokens
        return transformed

    def transform_responses_parameters(
        self, data: Dict, *, allow_builtin_tools: Optional[bool] = None
    ) -> Dict:
        """Transforms responses parameters (Responses API)."""
        builtin_tools_enabled = (
            self._responses_chat_completion_tools_enabled_by_default()
            if allow_builtin_tools is None
            else allow_builtin_tools
        )
        data = sanitize_openai_responses_parameters(
            data,
            allow_builtin_tools=builtin_tools_enabled,
            allow_stateful=builtin_tools_enabled,
        )
        transformed = self._transform_common_parameters(data)
        if builtin_tools_enabled:
            builtin_tools = self._build_chat_completion_builtin_tool_payloads(
                data.get("tools")
            )
            if builtin_tools:
                transformed["_gpt2giga_builtin_tools"] = builtin_tools

        response_format_responses: dict | None = transformed.pop("text", None)
        if response_format_responses:
            response_format = response_format_responses.get("format", {})
            if response_format.get("type") == "json_schema":
                schema_name, schema, strict = self._extract_json_schema_response_format(
                    response_format
                )
                if self._structured_output_mode() == "native":
                    self._apply_json_schema_natively(transformed, schema, strict)
                else:
                    self._apply_json_schema_as_function(
                        transformed, schema_name, schema
                    )
            elif response_format.get("type") == "json_object":
                self._reject_json_object_response_format("text.format.type")
            else:
                transformed["response_format"] = response_format

        top_level_response_format = transformed.get("response_format")
        if (
            isinstance(top_level_response_format, dict)
            and top_level_response_format.get("type") == "json_object"
        ):
            self._reject_json_object_response_format("response_format.type")

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
            last_tools_state_id: Optional[str] = None
            tool_state_by_call_id: dict[str, tuple[Optional[str], Optional[str]]] = {}
            for message in input_:
                message_type = message.get("type")
                if message_type == "function_call_output":
                    call_state_id = None
                    call_function_name = None
                    call_id = message.get("call_id")
                    if isinstance(call_id, str):
                        call_state_id, call_function_name = tool_state_by_call_id.get(
                            call_id, (None, None)
                        )

                    tools_state_id = (
                        call_state_id
                        or self._extract_responses_tools_state_id(message)
                        or last_tools_state_id
                    )
                    fn_name = message.get("name") or call_function_name
                    fn_name = fn_name or last_function_name
                    fn_name = map_tool_name_to_gigachat(fn_name) if fn_name else fn_name
                    payload = {
                        "role": "function",
                        "name": fn_name,
                        "content": ensure_json_object_str(message.get("output")),
                    }
                    self._set_backend_state_id(payload, tools_state_id)
                    message_payload.append(payload)
                    continue
                if message_type == "function_call":
                    last_function_name = message.get("name") or last_function_name
                    tools_state_id = (
                        self._extract_responses_tools_state_id(message)
                        or last_tools_state_id
                    )
                    last_tools_state_id = tools_state_id
                    call_id = message.get("call_id")
                    if isinstance(call_id, str):
                        tool_state_by_call_id[call_id] = (
                            tools_state_id,
                            last_function_name,
                        )

                    completion_payload = self.mock_completion(message)
                    self._set_backend_state_id(completion_payload, tools_state_id)
                    message_payload.append(completion_payload)
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
        raw_arguments = message.get("arguments", {})
        if isinstance(raw_arguments, str):
            arguments = json.loads(raw_arguments)
        else:
            arguments = raw_arguments
        name = map_tool_name_to_gigachat(message.get("name"))
        return Messages(
            role=MessagesRole.ASSISTANT,
            function_call=FunctionCall(name=name, arguments=arguments),
        ).model_dump()

    @staticmethod
    def _extract_responses_tools_state_id(message: dict) -> Optional[str]:
        for field_name in (
            "tools_state_id",
            "tool_state_id",
            "functions_state_id",
            "function_state_id",
            "tool_call_id",
        ):
            state_id = RequestTransformer._normalize_backend_state_id(
                message.get(field_name)
            )
            if state_id:
                return state_id

        item_id = message.get("id")
        state_id = RequestTransformer._normalize_backend_state_id(item_id)
        if state_id:
            return state_id

        return None

    async def _finalize_chat_transformation(
        self, transformed_data: dict, giga_client: Optional[GigaChat] = None
    ) -> Dict[str, Any]:
        """Common logic for message transformation and logging."""
        transformed_data.pop("_gpt2giga_builtin_tools", None)
        transformed_data.pop("_gpt2giga_tool_config", None)
        if "functions" in transformed_data:
            functions = normalize_gigachat_function_definitions(
                transformed_data.get("functions")
            )
            if functions:
                transformed_data["functions"] = functions
            else:
                transformed_data.pop("functions", None)
        transformed_data["messages"] = await self.transform_messages(
            transformed_data.get("messages", []), giga_client
        )
        self._sanitize_legacy_message_state_ids(transformed_data["messages"])
        if self._has_legacy_function_call_replay(transformed_data["messages"]):
            transformed_data.pop("functions", None)

        messages_objs = [
            Messages.model_validate(m) for m in transformed_data["messages"]
        ]
        collapsed_objs = collapse_user_messages(messages_objs)
        transformed_data["messages"] = [
            m.model_dump(exclude_none=True) for m in collapsed_objs
        ]

        msg_count = len(transformed_data.get("messages", []))
        has_functions = bool(transformed_data.get("functions"))
        log_debug_payload(
            self.logger,
            self.config,
            event="gigachat_request",
            message="Sending request to GigaChat API",
            payload_key="payload",
            payload=transformed_data,
            message_count=msg_count,
            has_functions=has_functions,
        )

        return transformed_data

    @staticmethod
    def _sanitize_legacy_message_state_ids(messages: list[dict[str, Any]]) -> None:
        """Keep legacy GigaChat function state ids only on roles accepted by v1."""
        for message in messages:
            if message.get("role") not in {"user", "function"}:
                message.pop("functions_state_id", None)

    @classmethod
    def _has_legacy_function_call_replay(cls, messages: list[dict[str, Any]]) -> bool:
        """Return true when the current v1 turn is a completed tool result."""
        if not messages or messages[-1].get("role") != "function":
            return False

        for index, message in enumerate(messages[:-1]):
            if cls._is_legacy_assistant_function_call_replay(
                message,
                messages[index + 1 :],
            ):
                return True
        return False

    @classmethod
    def _is_legacy_assistant_function_call_replay(
        cls,
        message: dict[str, Any],
        following_messages: list[dict[str, Any]],
    ) -> bool:
        if message.get("role") != "assistant":
            return False

        function_call = message.get("function_call")
        if not isinstance(function_call, dict) or not function_call.get("name"):
            return False

        state_id = cls._extract_tool_call_id(message)
        function_name = function_call.get("name")
        for following_message in following_messages:
            if following_message.get("role") != "function":
                continue

            result_state_id = cls._extract_tool_call_id(following_message)
            if state_id and result_state_id == state_id:
                return True
            if following_message.get("name") == function_name:
                return True

        return False

    async def _finalize_chat_completion_transformation(
        self, transformed_data: dict, giga_client: Optional[GigaChat] = None
    ) -> ChatCompletionRequest:
        """Build a GigaChat chat completion request."""
        transformed_data["messages"] = await self.transform_messages(
            transformed_data.get("messages", []), giga_client
        )

        messages = self._build_chat_completion_messages(transformed_data["messages"])
        request_payload = self._build_chat_completion_request_payload(
            transformed_data,
            messages,
        )
        chat_request = ChatCompletionRequest.model_validate(request_payload)

        msg_count = len(chat_request.messages)
        has_tools = bool(chat_request.tools)
        log_debug_payload(
            self.logger,
            self.config,
            event="gigachat_chat_completion_request",
            message="Sending chat completion request to GigaChat API",
            payload_key="payload",
            payload=chat_request,
            exclude_none=True,
            message_count=msg_count,
            has_tools=has_tools,
        )

        return chat_request

    def _build_chat_completion_messages(
        self,
        messages: List[Dict],
    ) -> List[ChatMessage]:
        return [
            ChatMessage.model_validate(
                self._build_chat_completion_message_payload(message)
            )
            for message in messages
        ]

    def _build_chat_completion_message_payload(self, message: Dict) -> Dict[str, Any]:
        role = str(message.get("role", "user"))
        is_function_result = role in {"function", "tool"}
        payload_role = "tool" if is_function_result else role
        payload: Dict[str, Any] = {"role": payload_role}
        content_parts: list[dict[str, Any]] = []

        function_call_part = None
        function_call = message.get("function_call")
        if isinstance(function_call, dict):
            name = function_call.get("name")
            if name:
                function_call_part = {
                    "function_call": {
                        "name": map_tool_name_to_gigachat(name),
                        "arguments": function_call.get("arguments", {}),
                    }
                }

        if is_function_result:
            function_name = message.get("name")
            if function_name:
                content_parts.append(
                    {
                        "function_result": {
                            "name": map_tool_name_to_gigachat(function_name),
                            "result": self._parse_function_result(
                                message.get("content")
                            ),
                        }
                    }
                )
        else:
            content = message.get("content")
            if content is None:
                content = ""
            if content or function_call_part is None:
                content_parts.append({"text": str(content)})
            if function_call_part is not None:
                content_parts.append(function_call_part)

        attachments = message.get("attachments")
        if isinstance(attachments, list) and attachments:
            content_parts.append(
                {
                    "files": [
                        {"id": attachment}
                        for attachment in attachments
                        if isinstance(attachment, str) and attachment
                    ]
                }
            )

        if content_parts:
            payload["content"] = content_parts

        tool_state_id = self._extract_tool_call_id(message)
        if tool_state_id:
            payload["tools_state_id"] = tool_state_id

        for field_name in ("message_id", "inline_data"):
            if field_name in message:
                payload[field_name] = message[field_name]

        return payload

    @staticmethod
    def _parse_function_result(content: Any) -> Any:
        if isinstance(content, str):
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return content
        return content

    def _build_chat_completion_request_payload(
        self, transformed_data: Dict[str, Any], messages: List[ChatMessage]
    ) -> Dict[str, Any]:
        request_payload: Dict[str, Any] = {"messages": messages}
        model_options: Dict[str, Any] = {}

        for field_name in ("model", "stream"):
            if field_name in transformed_data:
                request_payload[field_name] = transformed_data[field_name]

        for field_name in ("temperature", "top_p", "max_tokens", "response_format"):
            if field_name in transformed_data:
                model_options[field_name] = transformed_data[field_name]

        reasoning_effort = transformed_data.get("reasoning_effort")
        if reasoning_effort is not None:
            model_options["reasoning"] = {"effort": reasoning_effort}

        tools = self._build_chat_completion_tools(
            transformed_data.get("functions"),
            transformed_data.get("_gpt2giga_builtin_tools"),
        )
        if tools:
            request_payload["tools"] = tools

        tool_config = self._build_chat_completion_tool_config(
            transformed_data.get("function_call"),
            transformed_data.get("_gpt2giga_tool_config"),
        )
        if tool_config:
            request_payload["tool_config"] = tool_config

        self._apply_chat_completion_additional_fields(
            transformed_data.get("additional_fields"),
            request_payload,
            model_options,
        )
        self._apply_chat_completion_profanity_check_default(request_payload)
        storage = self._build_chat_completion_storage(
            transformed_data,
            existing_storage=request_payload.get("storage"),
        )
        if storage is not None:
            request_payload["storage"] = storage
        else:
            request_payload.pop("storage", None)

        if self._chat_completion_storage_has_thread_id(storage):
            request_payload.pop("model", None)

        if model_options:
            request_payload["model_options"] = model_options

        return request_payload

    @classmethod
    def _build_chat_completion_storage(
        cls,
        transformed_data: Dict[str, Any],
        *,
        existing_storage: Any = None,
    ) -> Any:
        is_responses_api = bool(transformed_data.get("_gpt2giga_responses_api"))
        store_enabled = False
        if is_responses_api:
            store_enabled = transformed_data.get("store") is True
        previous_response_id = transformed_data.get("previous_response_id")
        if not store_enabled and previous_response_id is None:
            return existing_storage

        if isinstance(existing_storage, dict):
            storage = dict(existing_storage)
        elif existing_storage is None or existing_storage is True:
            storage = {}
        else:
            return existing_storage

        thread_id = cls._responses_thread_id_from_response_id(previous_response_id)
        if thread_id:
            storage.setdefault("thread_id", thread_id)
        return storage

    @staticmethod
    def _chat_completion_storage_has_thread_id(storage: Any) -> bool:
        if isinstance(storage, dict):
            thread_id = storage.get("thread_id")
            return isinstance(thread_id, str) and bool(thread_id)
        if hasattr(storage, "thread_id"):
            thread_id = getattr(storage, "thread_id")
            return isinstance(thread_id, str) and bool(thread_id)
        return False

    @staticmethod
    def _responses_thread_id_from_response_id(response_id: Any) -> Optional[str]:
        if not isinstance(response_id, str) or not response_id:
            return None
        if response_id.startswith("resp_"):
            return response_id.removeprefix("resp_") or None
        return response_id

    def _apply_chat_completion_additional_fields(
        self,
        additional_fields: Any,
        request_payload: Dict[str, Any],
        model_options: Dict[str, Any],
    ) -> None:
        if not isinstance(additional_fields, dict):
            return

        explicit_disable_filter = (
            "disable_filter" in additional_fields or "disable_filter" in request_payload
        )
        for key, value in additional_fields.items():
            if key == "profanity_check":
                disable_filter = self._disable_filter_from_profanity_check(value)
                if disable_filter is not None and not explicit_disable_filter:
                    request_payload["disable_filter"] = disable_filter
                continue
            if key in self._CHAT_COMPLETION_MODEL_OPTION_FIELDS:
                model_options.setdefault(key, value)
            elif key in self._CHAT_COMPLETION_REQUEST_FIELDS:
                request_payload.setdefault(key, value)
            else:
                request_payload.setdefault(key, value)

    def _apply_chat_completion_profanity_check_default(
        self, request_payload: Dict[str, Any]
    ) -> None:
        if "disable_filter" in request_payload:
            return

        profanity_check = getattr(
            self.config.gigachat_settings,
            "profanity_check",
            None,
        )
        disable_filter = self._disable_filter_from_profanity_check(profanity_check)
        if disable_filter is not None:
            request_payload["disable_filter"] = disable_filter

    @staticmethod
    def _disable_filter_from_profanity_check(value: Any) -> Optional[bool]:
        if isinstance(value, bool):
            return not value
        return None

    def _build_chat_completion_builtin_tool_payloads(
        self,
        tools: Any,
    ) -> list[dict[str, Any]]:
        if not isinstance(tools, list) or not tools:
            return []

        builtin_tools: list[dict[str, Any]] = []
        seen_fields: set[str] = set()
        for tool in tools:
            tool_payload = self._dump_mapping(tool)
            if not tool_payload:
                continue

            builtin_payload = build_gigachat_builtin_tool_payload(tool_payload)
            if not builtin_payload:
                continue

            field_name = next(iter(builtin_payload))
            if field_name in seen_fields:
                continue
            seen_fields.add(field_name)
            builtin_tools.append(builtin_payload)

        return builtin_tools

    def _build_chat_completion_tools(
        self, functions: Any, builtin_tools: Any = None
    ) -> list[ChatTool]:
        tools: list[ChatTool] = []
        if isinstance(builtin_tools, list):
            for tool in builtin_tools:
                if isinstance(tool, ChatTool):
                    tools.append(tool)
                elif isinstance(tool, dict):
                    tools.append(ChatTool.model_validate(tool))

        if not isinstance(functions, list) or not functions:
            return tools

        specifications = []
        seen_names: set[str] = set()
        for function in functions:
            function_payload = self._dump_mapping(function)
            if not function_payload:
                continue
            if "function" in function_payload:
                function_payload = self._dump_mapping(function_payload["function"])

            name = function_payload.get("name")
            if not isinstance(name, str) or not name:
                continue
            mapped_name = map_tool_name_to_gigachat(name)
            if mapped_name in seen_names:
                continue
            seen_names.add(mapped_name)

            parameters = self._normalize_chat_completion_function_schema(
                function_payload.get("parameters") or {}
            )
            spec_payload = {
                "name": mapped_name,
                "parameters": parameters,
            }
            for field_name in (
                "description",
                "few_shot_examples",
                "return_parameters",
            ):
                if field_name in function_payload:
                    spec_payload[field_name] = function_payload[field_name]

            specifications.append(
                ChatFunctionSpecification.model_validate(spec_payload)
            )

        if not specifications:
            return tools

        tools.append(
            ChatTool.model_validate(
                {
                    "functions": {
                        "specifications": specifications,
                    }
                }
            )
        )
        return tools

    @staticmethod
    def _normalize_chat_completion_function_schema(schema: Any) -> dict[str, Any]:
        return normalize_tool_parameters_schema(schema)

    @staticmethod
    def _dump_mapping(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        if hasattr(value, "model_dump"):
            return value.model_dump(exclude_none=True, by_alias=True)
        return {}

    def _build_chat_completion_tool_config(
        self, function_call: Any, builtin_tool_config: Any = None
    ) -> dict[str, str]:
        if not isinstance(function_call, dict):
            return builtin_tool_config if isinstance(builtin_tool_config, dict) else {}

        name = function_call.get("name")
        if not isinstance(name, str) or not name:
            return builtin_tool_config if isinstance(builtin_tool_config, dict) else {}

        return {
            "mode": "function",
            "function_name": map_tool_name_to_gigachat(name),
        }

    async def prepare_chat(
        self, data: dict, giga_client: Optional[GigaChat] = None
    ) -> Dict[str, Any]:
        """Prepare a legacy GigaChat chat request."""
        transformed_data = self.transform_chat_parameters(
            data, allow_builtin_tools=False
        )
        return await self._finalize_chat_transformation(transformed_data, giga_client)

    async def prepare_chat_completion(
        self, data: dict, giga_client: Optional[GigaChat] = None
    ) -> ChatCompletionRequest:
        """Prepare a GigaChat chat completion request."""
        transformed_data = self.transform_chat_parameters(
            data, allow_builtin_tools=True
        )
        return await self._finalize_chat_completion_transformation(
            transformed_data,
            giga_client,
        )

    async def prepare_response_chat(
        self, data: dict, giga_client: Optional[GigaChat] = None
    ) -> Dict[str, Any]:
        """Prepare a Responses API request for the legacy GigaChat chat path."""
        transformed_data = self.transform_responses_parameters(
            data, allow_builtin_tools=False
        )
        transformed_data["messages"] = self.transform_response_format(transformed_data)
        return await self._finalize_chat_transformation(transformed_data, giga_client)

    async def prepare_response_chat_completion(
        self, data: dict, giga_client: Optional[GigaChat] = None
    ) -> ChatCompletionRequest:
        """Prepare a Responses API request for the GigaChat chat completion path."""
        transformed_data = self.transform_responses_parameters(
            data, allow_builtin_tools=True
        )
        transformed_data["_gpt2giga_responses_api"] = True
        transformed_data["messages"] = self.transform_response_format(transformed_data)
        return await self._finalize_chat_completion_transformation(
            transformed_data,
            giga_client,
        )
