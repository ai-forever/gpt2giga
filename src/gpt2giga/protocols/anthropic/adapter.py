"""Anthropic Messages adapters for the normalized protocol core."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from gpt2giga.common.content_utils import ensure_json_object_str
from gpt2giga.common.tools import normalize_gigachat_builtin_tool_type
from gpt2giga.core.context import RequestContext
from gpt2giga.protocol.anthropic.params import (
    ANTHROPIC_ACCEPTED_IGNORED_PARAMS,
    sanitize_anthropic_messages_parameters,
)
from gpt2giga.protocol.anthropic.request import (
    _ANTHROPIC_NAMED_BUILTIN_TOOL_TYPES,
    _convert_anthropic_output_format_to_openai_response_format,
)
from gpt2giga.protocols.anthropic.response_adapter import (
    normalized_chat_response_to_anthropic,
)
from gpt2giga.protocols.normalized import (
    NormalizedChatRequest,
    NormalizedContentPart,
    NormalizedGenerationConfig,
    NormalizedImageReference,
    NormalizedMessage,
    NormalizedResponseFormat,
    NormalizedTokenCountRequest,
    NormalizedTool,
    NormalizedToolCall,
)


class AnthropicProtocolAdapter:
    """Convert Anthropic Messages payloads to the normalized v1 contract."""

    name = "anthropic"

    async def to_normalized(
        self,
        payload: Mapping[str, Any],
        *,
        context: RequestContext | None = None,
    ) -> NormalizedChatRequest:
        """Convert one Anthropic Messages request to normalized form."""
        return self.messages_to_normalized(payload, context=context)

    async def from_normalized(
        self,
        payload: Any,
        *,
        context: RequestContext | None = None,
    ) -> Any:
        """Convert one normalized response to Anthropic Messages shape."""
        return normalized_chat_response_to_anthropic(
            payload,
            requested_model=getattr(payload, "model", None) or "unknown",
            context=context,
        )

    def messages_to_normalized(
        self,
        payload: Mapping[str, Any],
        *,
        context: RequestContext | None = None,
    ) -> NormalizedChatRequest:
        """Convert one Anthropic Messages payload to normalized form."""
        original = dict(payload)
        data = sanitize_anthropic_messages_parameters(original)
        tools = _normalize_tools(data.get("tools"))
        tool_choice, parallel_tool_calls = _normalize_tool_choice(
            data.get("tool_choice"),
            tools=tools,
        )
        return NormalizedChatRequest(
            id=context.request_id if context is not None else None,
            protocol="anthropic",
            operation="chat",
            model=_string_or_none(data.get("model")),
            stream=bool(data.get("stream", False)),
            messages=_normalize_messages(data.get("system"), data.get("messages")),
            tools=tools,
            tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls,
            response_format=_normalize_response_format(data),
            generation_config=_normalize_generation_config(data),
            metadata=_mapping_copy(original.get("metadata")),
            raw_extensions=_ignored_extensions(original),
            provider_metadata=_provider_metadata(data),
        )

    def count_tokens_to_normalized(
        self,
        payload: Mapping[str, Any],
        *,
        context: RequestContext | None = None,
    ) -> NormalizedTokenCountRequest:
        """Convert Anthropic count_tokens input to a normalized operation."""
        chat = self.messages_to_normalized(
            {**dict(payload), "stream": False},
            context=context,
        )
        return NormalizedTokenCountRequest(
            id=context.request_id if context is not None else None,
            protocol="anthropic",
            model=chat.model,
            input=chat,
        )


def _normalize_messages(system: Any, value: Any) -> list[NormalizedMessage]:
    messages = _normalize_system(system)
    if not isinstance(value, list):
        return messages

    tool_names: dict[str, str] = {}
    for item in value:
        if not isinstance(item, Mapping):
            continue
        role = str(item.get("role", "user"))
        content = item.get("content", "")
        if role == "assistant":
            message = _normalize_assistant_message(content)
            messages.append(message)
            tool_names.update(
                {
                    call.id: call.name
                    for call in message.tool_calls
                    if call.id and call.name
                }
            )
        elif role == "user":
            messages.extend(_normalize_user_messages(content, tool_names=tool_names))
        else:
            messages.append(
                NormalizedMessage(
                    role=role,
                    content=content if isinstance(content, str) else str(content),
                )
            )
    return messages


def _normalize_system(value: Any) -> list[NormalizedMessage]:
    if isinstance(value, str) and value:
        return [NormalizedMessage(role="system", content=value)]
    if not isinstance(value, list):
        return []
    parts = [
        NormalizedContentPart(type="text", text=str(block.get("text", "")))
        for block in value
        if isinstance(block, Mapping) and block.get("type") == "text"
    ]
    return [NormalizedMessage(role="system", content=parts)] if parts else []


def _normalize_assistant_message(value: Any) -> NormalizedMessage:
    if isinstance(value, str):
        return NormalizedMessage(role="assistant", content=value)
    if not isinstance(value, list):
        return NormalizedMessage(role="assistant", content=str(value))

    text_parts: list[NormalizedContentPart] = []
    tool_calls: list[NormalizedToolCall] = []
    for block in value:
        if not isinstance(block, Mapping):
            continue
        if block.get("type") == "text":
            text_parts.append(
                NormalizedContentPart(type="text", text=str(block.get("text", "")))
            )
        elif block.get("type") == "tool_use" and block.get("name"):
            tool_calls.append(
                NormalizedToolCall(
                    id=_string_or_none(block.get("id")),
                    type="function",
                    name=str(block["name"]),
                    arguments=block.get("input", {}),
                )
            )
    return NormalizedMessage(
        role="assistant",
        content=text_parts or "",
        tool_calls=tool_calls,
    )


def _normalize_user_messages(
    value: Any,
    *,
    tool_names: Mapping[str, str],
) -> list[NormalizedMessage]:
    if isinstance(value, str):
        return [NormalizedMessage(role="user", content=value)]
    if not isinstance(value, list):
        return [NormalizedMessage(role="user", content=str(value))]

    tool_results: list[NormalizedMessage] = []
    parts: list[NormalizedContentPart] = []
    for block in value:
        if not isinstance(block, Mapping):
            continue
        block_type = block.get("type")
        if block_type == "text":
            parts.append(
                NormalizedContentPart(type="text", text=str(block.get("text", "")))
            )
        elif block_type == "image":
            image = _normalize_image(block.get("source"))
            if image is not None:
                parts.append(
                    NormalizedContentPart(
                        type="image_reference",
                        image_reference=image,
                    )
                )
        elif block_type == "tool_result":
            call_id = _string_or_none(block.get("tool_use_id"))
            tool_results.append(
                NormalizedMessage(
                    role="tool",
                    name=tool_names.get(call_id or ""),
                    tool_call_id=call_id,
                    content=ensure_json_object_str(
                        _tool_result_content(block.get("content", ""))
                    ),
                )
            )

    messages = tool_results
    if parts:
        messages.append(NormalizedMessage(role="user", content=parts))
    elif not tool_results:
        messages.append(NormalizedMessage(role="user", content=""))
    return messages


def _normalize_image(value: Any) -> NormalizedImageReference | None:
    if not isinstance(value, Mapping):
        return None
    source_type = value.get("type")
    if source_type == "base64":
        media_type = str(value.get("media_type") or "image/png")
        data = str(value.get("data") or "")
        return NormalizedImageReference(
            source="data_url",
            uri=f"data:{media_type};base64,{data}",
            mime_type=media_type,
        )
    if source_type == "url" and value.get("url"):
        return NormalizedImageReference(
            source="url",
            uri=str(value["url"]),
        )
    return None


def _tool_result_content(value: Any) -> Any:
    if not isinstance(value, list):
        return value
    texts = [
        str(item.get("text", ""))
        for item in value
        if isinstance(item, Mapping) and item.get("type") == "text"
    ]
    return "\n".join(texts)


def _normalize_tools(value: Any) -> list[NormalizedTool]:
    if not isinstance(value, list):
        return []
    tools: list[NormalizedTool] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        builtin = _builtin_tool(item)
        if builtin is not None:
            tools.append(builtin)
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name:
            continue
        schema = item.get("input_schema", {})
        if not isinstance(schema, Mapping):
            schema = {}
        tools.append(
            NormalizedTool(
                type="function",
                name=name,
                description=_string_or_none(item.get("description")),
                parameters=dict(schema),
            )
        )
    return tools


def _builtin_tool(value: Mapping[str, Any]) -> NormalizedTool | None:
    builtin_type = normalize_gigachat_builtin_tool_type(value.get("type"))
    if builtin_type is None and isinstance(value.get("name"), str):
        builtin_type = _ANTHROPIC_NAMED_BUILTIN_TOOL_TYPES.get(value["name"])
    if builtin_type is None:
        return None
    config = {
        key: item
        for key, item in value.items()
        if key not in {"type", "name", "description", "input_schema", "parameters"}
    }
    return NormalizedTool(
        type=builtin_type,
        name=str(value.get("name") or builtin_type),
        raw_extensions=config,
    )


def _normalize_tool_choice(
    value: Any,
    *,
    tools: list[NormalizedTool],
) -> tuple[Any | None, bool | None]:
    if not isinstance(value, Mapping):
        return None, None
    choice_type = value.get("type")
    parallel = None
    if "disable_parallel_tool_use" in value:
        parallel = not bool(value["disable_parallel_tool_use"])
    if choice_type == "auto":
        return "auto", parallel
    if choice_type == "none":
        return "none", parallel
    if choice_type != "tool" or not value.get("name"):
        return None, parallel
    name = str(value["name"])
    selected = next((tool for tool in tools if tool.name == name), None)
    if selected is not None and selected.type != "function":
        return {"type": selected.type}, parallel
    return {"type": "function", "function": {"name": name}}, parallel


def _normalize_response_format(
    data: Mapping[str, Any],
) -> NormalizedResponseFormat | None:
    value = _convert_anthropic_output_format_to_openai_response_format(dict(data))
    if not isinstance(value, Mapping):
        return None
    schema = value.get("schema")
    if not isinstance(schema, Mapping):
        return None
    json_schema = {"schema": dict(schema)}
    for key in ("name", "strict"):
        if key in value:
            json_schema[key] = value[key]
    return NormalizedResponseFormat(
        type="json_schema",
        json_schema=json_schema,
    )


def _normalize_generation_config(
    data: Mapping[str, Any],
) -> NormalizedGenerationConfig:
    reasoning_effort = _reasoning_effort(data.get("thinking"))
    return NormalizedGenerationConfig(
        temperature=_optional_float(data.get("temperature")),
        top_p=_optional_float(data.get("top_p")),
        max_tokens=_optional_int(data.get("max_tokens")),
        stop=data.get("stop_sequences"),
        raw_extensions=(
            {"reasoning_effort": reasoning_effort} if reasoning_effort else {}
        ),
    )


def _reasoning_effort(value: Any) -> str | None:
    if not isinstance(value, Mapping) or value.get("type") != "enabled":
        return None
    budget = value.get("budget_tokens", 10_000)
    if not isinstance(budget, int):
        return None
    if budget >= 8_000:
        return "high"
    if budget >= 3_000:
        return "medium"
    return "low"


def _provider_metadata(data: Mapping[str, Any]) -> dict[str, Any]:
    extra_body = data.get("extra_body")
    if not isinstance(extra_body, Mapping) or not extra_body:
        return {}
    return {"gigachat": {"additional_fields": dict(extra_body)}}


def _ignored_extensions(payload: Mapping[str, Any]) -> dict[str, Any]:
    ignored = {
        key: payload[key]
        for key in ANTHROPIC_ACCEPTED_IGNORED_PARAMS
        if key in payload and key != "metadata"
    }
    return {"accepted_ignored": ignored} if ignored else {}


def _mapping_copy(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _optional_float(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _optional_int(value: Any) -> int | None:
    return (
        int(value) if isinstance(value, int) and not isinstance(value, bool) else None
    )
