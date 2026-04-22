"""GigaChat request mapping entry point."""

import json
from typing import Any, Dict, List, Optional

from gigachat import GigaChat
from gigachat.models import FunctionCall, Messages, MessagesRole

from gpt2giga.core.contracts import to_backend_payload
from gpt2giga.core.config.settings import ProxyConfig
from gpt2giga.core.logging.setup import sanitize_for_utf8
from gpt2giga.providers.gigachat.attachments import AttachmentProcessor
from gpt2giga.providers.gigachat.chat_request_mapper import (
    RequestTransformerMessagesMixin,
)
from gpt2giga.providers.gigachat.content_utils import ensure_json_object_str
from gpt2giga.providers.gigachat.message_utils import collapse_user_messages
from gpt2giga.providers.gigachat.request_mapping_base import (
    RequestTransformerBaseMixin,
)
from gpt2giga.providers.gigachat.responses import (
    RequestTransformerResponsesV2Mixin,
)
from gpt2giga.providers.gigachat.tool_mapping import map_tool_name_to_gigachat


class RequestTransformer(
    RequestTransformerResponsesV2Mixin,
    RequestTransformerMessagesMixin,
    RequestTransformerBaseMixin,
):
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

    def transform_chat_parameters(self, data: Dict) -> Dict:
        """Transform chat-completions parameters."""
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
        """Transform Responses API parameters."""
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
        """Transform Responses API input items into chat-style messages."""
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
                if not role:
                    continue
                content = message.get("content")
                if isinstance(content, list):
                    contents: list[dict[str, Any]] = []
                    append = contents.append
                    for content_part in content:
                        ctype = content_part.get("type")
                        if ctype == "input_text":
                            append({"type": "text", "text": content_part.get("text")})
                        elif ctype == "input_image":
                            append(
                                {
                                    "type": "image_url",
                                    "image_url": {"url": content_part.get("image_url")},
                                }
                            )

                    message_payload.append({"role": role, "content": contents})
                else:
                    message_payload.append({"role": role, "content": content})

        return message_payload

    @staticmethod
    def mock_completion(message: dict) -> dict:
        """Create a mock assistant function-call message."""
        raw_arguments = message.get("arguments")
        if isinstance(raw_arguments, (str, bytes, bytearray)):
            arguments = json.loads(raw_arguments)
        else:
            arguments = raw_arguments or {}

        raw_name = message.get("name")
        name = map_tool_name_to_gigachat(raw_name) if isinstance(raw_name, str) else ""
        return Messages(
            role=MessagesRole.ASSISTANT,
            function_call=FunctionCall(name=name, arguments=arguments),
        ).model_dump()

    async def _finalize_transformation(
        self, transformed_data: dict, giga_client: Optional[GigaChat] = None
    ) -> Dict[str, Any]:
        """Apply common post-processing and logging for transformed payloads."""
        transformed_data["messages"] = await self.transform_messages(
            transformed_data.get("messages", []), giga_client
        )

        messages_objs = [
            Messages.model_validate(message) for message in transformed_data["messages"]
        ]
        collapsed_objs = collapse_user_messages(messages_objs)
        transformed_data["messages"] = [
            message.model_dump(exclude_none=True) for message in collapsed_objs
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
        self, data: Any, giga_client: Any = None
    ) -> Dict[str, Any]:
        """Prepare a Chat Completions payload."""
        transformed_data = self.transform_chat_parameters(to_backend_payload(data))
        return await self._finalize_transformation(transformed_data, giga_client)

    @staticmethod
    def _coerce_functions_to_tools(functions: Any) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        if not isinstance(functions, list):
            return tools
        for function in functions:
            if hasattr(function, "model_dump"):
                function = function.model_dump(exclude_none=True, by_alias=True)
            if isinstance(function, dict):
                tools.append({"type": "function", "function": function})
        return tools

    def _build_chat_v2_request_data(self, data: dict[str, Any]) -> dict[str, Any]:
        request_data = data.copy()
        messages = request_data.pop("messages", None)
        input_ = request_data.pop("input", None)
        if messages is None:
            if isinstance(input_, list):
                messages = input_
            elif input_ is not None:
                messages = [{"role": "user", "content": input_}]
            else:
                messages = []
        request_data["input"] = messages

        if "max_tokens" in request_data and "max_output_tokens" not in request_data:
            request_data["max_output_tokens"] = request_data["max_tokens"]

        if "reasoning" not in request_data:
            reasoning_effort = request_data.get("reasoning_effort")
            if reasoning_effort in {"low", "medium", "high"}:
                request_data["reasoning"] = {"effort": reasoning_effort}

        response_format = request_data.pop("response_format", None)
        if isinstance(response_format, dict):
            if response_format.get("type") == "json_object":
                request_data["text"] = {"format": {"type": "text"}}
            else:
                request_data["text"] = {"format": response_format}

        if "tools" not in request_data and "functions" in request_data:
            request_data["tools"] = self._coerce_functions_to_tools(
                request_data.get("functions")
            )

        function_call = request_data.pop("function_call", None)
        if "tool_choice" not in request_data:
            if isinstance(function_call, str):
                request_data["tool_choice"] = function_call
            elif isinstance(function_call, dict):
                name = function_call.get("name")
                if isinstance(name, str) and name:
                    request_data["tool_choice"] = {"type": "function", "name": name}

        return request_data

    async def prepare_chat_completion_v2(self, data: Any, giga_client: Any = None):
        """Prepare a native GigaChat v2 payload for chat-like endpoints."""
        request_data = self._build_chat_v2_request_data(to_backend_payload(data))
        return await self.prepare_response_v2(request_data, giga_client)

    async def prepare_response(
        self, data: Any, giga_client: Any = None
    ) -> Dict[str, Any]:
        """Prepare a legacy Responses API payload."""
        transformed_data = self.transform_responses_parameters(to_backend_payload(data))
        transformed_data["messages"] = self.transform_response_format(transformed_data)
        return await self._finalize_transformation(transformed_data, giga_client)
