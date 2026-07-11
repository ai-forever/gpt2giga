"""OpenAI protocol adapters for the normalized shadow layer."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from gpt2giga.common.client_params import ClientCompatibilityError
from gpt2giga.common.json_schema import normalize_tool_parameters_schema
from gpt2giga.core.context import RequestContext
from gpt2giga.protocol.request.params import sanitize_openai_chat_parameters
from gpt2giga.protocols.normalized import (
    NormalizedChatRequest,
    NormalizedContentPart,
    NormalizedGenerationConfig,
    NormalizedMessage,
    NormalizedResponseFormat,
    NormalizedTool,
    NormalizedToolCall,
)
from gpt2giga.protocols.openai.response_adapter import (
    normalized_chat_response_to_openai,
)

_CHAT_TOP_LEVEL_FIELDS = {
    "additional_fields",
    "extra_body",
    "extra_headers",
    "extra_query",
    "function_call",
    "functions",
    "max_output_tokens",
    "max_tokens",
    "messages",
    "metadata",
    "model",
    "presence_penalty",
    "frequency_penalty",
    "reasoning",
    "reasoning_effort",
    "response_format",
    "seed",
    "stop",
    "stream",
    "temperature",
    "tool_choice",
    "tools",
    "top_p",
    "user",
}


class OpenAIProtocolAdapter:
    """Convert OpenAI-compatible request payloads to normalized models."""

    name = "openai"

    async def to_normalized(
        self,
        payload: Mapping[str, Any],
        *,
        context: RequestContext | None = None,
    ) -> NormalizedChatRequest:
        """Convert an OpenAI Chat Completions payload to normalized form."""
        return self.chat_to_normalized(payload, context=context)

    async def from_normalized(
        self,
        payload: Any,
        *,
        context: RequestContext | None = None,
    ) -> Any:
        """Convert normalized responses back to OpenAI payloads."""
        return normalized_chat_response_to_openai(
            payload,
            requested_model=getattr(payload, "model", None) or "GigaChat",
            context=context,
        )

    def chat_to_normalized(
        self,
        payload: Mapping[str, Any],
        *,
        context: RequestContext | None = None,
    ) -> NormalizedChatRequest:
        """Convert an OpenAI Chat Completions payload to normalized form."""
        original = dict(payload)
        sanitized = _map_chat_token_limit(sanitize_openai_chat_parameters(original))
        metadata, metadata_extension = _extract_metadata(original.get("metadata"))
        raw_extensions = _build_raw_extensions(sanitized)
        if metadata_extension is not None:
            raw_extensions["metadata"] = metadata_extension
        provider_metadata = _build_provider_metadata(sanitized)

        return NormalizedChatRequest(
            id=context.request_id if context is not None else None,
            protocol="openai",
            operation="chat",
            model=original.get("model"),
            stream=bool(sanitized.get("stream", False)),
            messages=_normalize_messages(sanitized.get("messages", [])),
            tools=_normalize_tools(sanitized),
            tool_choice=_normalize_tool_choice(original, sanitized),
            response_format=_normalize_response_format(
                sanitized.get("response_format")
            ),
            generation_config=_normalize_generation_config(sanitized),
            user=original.get("user"),
            metadata=metadata,
            raw_extensions=raw_extensions,
            provider_metadata=provider_metadata,
        )


def _map_chat_token_limit(data: dict[str, Any]) -> dict[str, Any]:
    if "max_completion_tokens" not in data:
        return data

    transformed = data.copy()
    max_completion_tokens = transformed.pop("max_completion_tokens")
    if max_completion_tokens is None:
        return transformed

    for conflict_param in ("max_tokens", "max_output_tokens"):
        if transformed.get(conflict_param) is not None:
            raise ClientCompatibilityError(
                f"`max_completion_tokens` cannot be combined with `{conflict_param}`.",
                provider="openai",
                param="max_completion_tokens",
            )

    transformed["max_tokens"] = max_completion_tokens
    return transformed


def _extract_metadata(value: Any) -> tuple[dict[str, Any], Any | None]:
    if value is None:
        return {}, None
    if isinstance(value, Mapping):
        return dict(value), None
    return {}, value


def _build_raw_extensions(data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in data.items()
        if key not in _CHAT_TOP_LEVEL_FIELDS and value is not None
    }


def _build_provider_metadata(data: Mapping[str, Any]) -> dict[str, Any]:
    additional_fields: dict[str, Any] = {}
    extra_body = data.get("extra_body")
    if isinstance(extra_body, Mapping):
        additional_fields.update(dict(extra_body))

    existing_additional = data.get("additional_fields")
    if isinstance(existing_additional, Mapping):
        additional_fields.update(dict(existing_additional))

    if not additional_fields:
        return {}
    return {"gigachat": {"additional_fields": additional_fields}}


def _normalize_messages(value: Any) -> list[NormalizedMessage]:
    if not isinstance(value, list):
        return []
    return [_normalize_message(item) for item in value if isinstance(item, Mapping)]


def _normalize_message(message: Mapping[str, Any]) -> NormalizedMessage:
    tool_calls = [_normalize_tool_call(item) for item in _tool_call_items(message)]
    raw_extensions = {
        key: value
        for key, value in message.items()
        if key
        not in {
            "content",
            "function_call",
            "name",
            "role",
            "tool_call_id",
            "tool_calls",
        }
    }
    return NormalizedMessage(
        role=str(message.get("role", "user")),
        content=_normalize_content(message.get("content")),
        name=_string_or_none(message.get("name")),
        tool_call_id=_string_or_none(message.get("tool_call_id")),
        tool_calls=tool_calls,
        raw_extensions=raw_extensions,
    )


def _tool_call_items(message: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    items: list[Mapping[str, Any]] = []
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        items.extend(item for item in tool_calls if isinstance(item, Mapping))

    function_call = message.get("function_call")
    if isinstance(function_call, Mapping):
        items.append({"type": "function", "function": function_call})
    return items


def _normalize_content(value: Any) -> str | list[NormalizedContentPart] | None:
    if value is None or isinstance(value, str):
        return value
    if not isinstance(value, list):
        return str(value)
    return [
        _normalize_content_part(item) for item in value if isinstance(item, Mapping)
    ]


def _normalize_content_part(part: Mapping[str, Any]) -> NormalizedContentPart:
    part_type = str(part.get("type", "unknown"))
    raw_extensions = {
        key: value
        for key, value in part.items()
        if key not in {"type", "text", "image_url", "file"}
    }
    if part_type == "text":
        return NormalizedContentPart(
            type="text",
            text=_string_or_none(part.get("text")),
            raw_extensions=raw_extensions,
        )
    if part_type == "image_url":
        image_url = part.get("image_url")
        detail = image_url.get("detail") if isinstance(image_url, Mapping) else None
        return NormalizedContentPart(
            type="image_url",
            data=dict(image_url) if isinstance(image_url, Mapping) else image_url,
            detail=_string_or_none(detail),
            raw_extensions=raw_extensions,
        )
    if part_type == "file":
        file_payload = part.get("file")
        return NormalizedContentPart(
            type="file",
            data=dict(file_payload)
            if isinstance(file_payload, Mapping)
            else file_payload,
            raw_extensions=raw_extensions,
        )
    return NormalizedContentPart(
        type=part_type,
        data=dict(part),
        raw_extensions=raw_extensions,
    )


def _normalize_tool_call(tool_call: Mapping[str, Any]) -> NormalizedToolCall:
    function = tool_call.get("function")
    function_data = function if isinstance(function, Mapping) else {}
    raw_extensions = {
        key: value
        for key, value in tool_call.items()
        if key not in {"id", "type", "function"}
    }
    function_extensions = {
        key: value
        for key, value in function_data.items()
        if key not in {"name", "arguments"}
    }
    if function_extensions:
        raw_extensions["function"] = function_extensions
    return NormalizedToolCall(
        id=_string_or_none(tool_call.get("id")),
        type=str(tool_call.get("type", "function")),
        name=_string_or_none(function_data.get("name") or tool_call.get("name")),
        arguments=function_data.get("arguments", tool_call.get("arguments")),
        raw_extensions=raw_extensions,
    )


def _normalize_tools(data: Mapping[str, Any]) -> list[NormalizedTool]:
    source = data.get("tools")
    if not source and data.get("functions"):
        source = data.get("functions")
    if not isinstance(source, list):
        return []
    return [_normalize_tool(item) for item in source if isinstance(item, Mapping)]


def _normalize_tool(tool: Mapping[str, Any]) -> NormalizedTool:
    function = tool.get("function")
    function_data = function if isinstance(function, Mapping) else tool
    raw_extensions = {
        key: value
        for key, value in tool.items()
        if key not in {"type", "function", "name", "description", "parameters"}
    }
    function_extensions = {
        key: value
        for key, value in function_data.items()
        if key not in {"name", "description", "parameters"}
    }
    if function_extensions and function_data is not tool:
        raw_extensions["function"] = function_extensions
    parameters = function_data.get("parameters")
    if not isinstance(parameters, Mapping):
        parameters = {}
    return NormalizedTool(
        type=str(tool.get("type", "function")),
        name=str(function_data.get("name", "")),
        description=_string_or_none(function_data.get("description")),
        parameters=normalize_tool_parameters_schema(parameters),
        raw_extensions=raw_extensions,
    )


def _normalize_tool_choice(
    original: Mapping[str, Any],
    sanitized: Mapping[str, Any],
) -> Any | None:
    function_call = sanitized.get("function_call")
    if isinstance(function_call, Mapping):
        return {"type": "function", "function": dict(function_call)}
    if function_call is not None:
        return function_call
    return original.get("tool_choice")


def _normalize_response_format(value: Any) -> NormalizedResponseFormat | None:
    if not isinstance(value, Mapping):
        return None
    response_type = value.get("type")
    if not isinstance(response_type, str):
        return None

    json_schema = None
    if isinstance(value.get("json_schema"), Mapping):
        json_schema = dict(value["json_schema"])
    elif isinstance(value.get("schema"), Mapping):
        json_schema = {
            key: value[key] for key in ("name", "schema", "strict") if key in value
        }

    raw_extensions = {
        key: item
        for key, item in value.items()
        if key not in {"type", "json_schema", "schema", "name", "strict"}
    }
    return NormalizedResponseFormat(
        type=response_type,
        json_schema=json_schema,
        raw_extensions=raw_extensions,
    )


def _normalize_generation_config(
    data: Mapping[str, Any],
) -> NormalizedGenerationConfig:
    max_tokens = data.get("max_tokens")
    if max_tokens is None:
        max_tokens = data.get("max_output_tokens")
    return NormalizedGenerationConfig(
        temperature=data.get("temperature"),
        top_p=data.get("top_p"),
        max_tokens=max_tokens,
        presence_penalty=data.get("presence_penalty"),
        frequency_penalty=data.get("frequency_penalty"),
        stop=data.get("stop"),
        seed=data.get("seed"),
    )


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
