"""Responses API v2 backend-request assembly helpers."""

from typing import Any, Dict, List, Optional

from gigachat import GigaChat
from gigachat.models import ChatV2, ChatV2Storage, ChatV2Tool, ChatV2UserInfo

from gpt2giga.core.contracts import to_backend_payload
from gpt2giga.core.logging.setup import sanitize_for_utf8
from gpt2giga.providers.gigachat.request_mapping_base import RequestTransformerBaseMixin
from gpt2giga.providers.gigachat.responses.input_normalizer import (
    ResponsesV2InputNormalizerMixin,
)
from gpt2giga.providers.gigachat.responses.model_options import (
    ResponsesV2ModelOptionsMixin,
)
from gpt2giga.providers.gigachat.responses.threading import (
    ResponsesV2ThreadingMixin,
)
from gpt2giga.providers.gigachat.responses.tool_mapping import (
    ResponsesV2ToolMappingMixin,
)


class ResponsesV2BackendRequestMixin(
    ResponsesV2ModelOptionsMixin,
    ResponsesV2InputNormalizerMixin,
    ResponsesV2ThreadingMixin,
    ResponsesV2ToolMappingMixin,
    RequestTransformerBaseMixin,
):
    """Build the final GigaChat v2 request payload for Responses API calls."""

    async def prepare_response_v2(
        self,
        data: dict,
        giga_client: Optional[GigaChat] = None,
        response_store: Optional[Dict[str, Any]] = None,
    ) -> ChatV2:
        """Prepare a native GigaChat v2 payload for the Responses API."""
        request_data = to_backend_payload(data)

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

        payload: Dict[str, Any] = {
            "messages": await self._build_response_v2_messages(
                request_data,
                giga_client,
            ),
            "stream": bool(request_data.get("stream", False)),
            "additional_fields": self._merge_additional_fields(request_data),
        }

        storage = self._resolve_response_storage(request_data, response_store)
        if storage is not None:
            payload["storage"] = ChatV2Storage(**storage)

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
