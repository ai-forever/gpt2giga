"""Fail-closed OpenAI Responses request decoding for normalized execution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, NoReturn

from gpt2giga.common.client_params import ClientCompatibilityError
from gpt2giga.common.json_schema import normalize_tool_parameters_schema
from gpt2giga.core.context import RequestContext
from gpt2giga.protocols.normalized import (
    NormalizedChatRequest,
    NormalizedContentPart,
    NormalizedGenerationConfig,
    NormalizedMessage,
    NormalizedResponseFormat,
    NormalizedTool,
    NormalizedToolCall,
)


_RESPONSES_FIELDS = frozenset(
    {
        "input",
        "instructions",
        "max_output_tokens",
        "metadata",
        "model",
        "stream",
        "temperature",
        "text",
        "tool_choice",
        "tools",
        "top_p",
    }
)
_UNSUPPORTED_STATE_AND_REASONING_FIELDS = frozenset(
    {
        "background",
        "conversation",
        "include",
        "previous_response_id",
        "reasoning",
        "reasoning_effort",
        "store",
    }
)
_UNSUPPORTED_MESSAGE = "The selected bridge route cannot preserve this semantic."
_INVALID_MESSAGE = "The Responses request is invalid for normalized execution."


def responses_request_to_normalized(
    payload: Mapping[str, Any],
    *,
    context: RequestContext | None = None,
) -> NormalizedChatRequest:
    """Decode the pinned Responses subset without consulting provider state."""
    if not isinstance(payload, Mapping):
        _invalid("request")
    data = dict(payload)
    for field in _UNSUPPORTED_STATE_AND_REASONING_FIELDS:
        if field in data:
            _unsupported(field)
    _reject_unknown_fields(data, _RESPONSES_FIELDS)

    model = data.get("model")
    if not isinstance(model, str) or not model.strip():
        _invalid("model")
    if "input" not in data:
        _invalid("input")

    messages = _normalize_instructions(data.get("instructions"))
    messages.extend(_normalize_input(data["input"]))
    tools = _normalize_responses_tools(data.get("tools"))
    tool_choice = _normalize_responses_tool_choice(data.get("tool_choice"), tools)

    stream = data.get("stream", False)
    if not isinstance(stream, bool):
        _invalid("stream")
    metadata = data.get("metadata")
    if metadata is not None and not isinstance(metadata, Mapping):
        _invalid("metadata")

    return NormalizedChatRequest(
        id=context.request_id if context is not None else None,
        protocol="openai",
        operation="responses",
        model=model,
        stream=stream,
        messages=messages,
        tools=tools,
        tool_choice=tool_choice,
        response_format=_normalize_text_format(data.get("text")),
        generation_config=_normalize_generation_config(data),
        metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
    )


def _normalize_instructions(value: Any) -> list[NormalizedMessage]:
    if value is None:
        return []
    if not isinstance(value, str):
        _invalid("instructions")
    return [NormalizedMessage(role="system", content=value)]


def _normalize_input(value: Any) -> list[NormalizedMessage]:
    if isinstance(value, str):
        return [NormalizedMessage(role="user", content=value)]
    if not isinstance(value, list) or not value:
        _invalid("input")

    messages: list[NormalizedMessage] = []
    for index, item in enumerate(value):
        path = f"input[{index}]"
        if not isinstance(item, Mapping):
            _invalid(path)
        item_type = item.get("type", "message")
        if item_type == "message":
            messages.append(_normalize_input_message(item, path=path))
        elif item_type == "function_call":
            messages.append(_normalize_function_call(item, path=path))
        elif item_type == "function_call_output":
            messages.append(_normalize_function_output(item, path=path))
        else:
            _unsupported(f"{path}.type")
    return messages


def _normalize_input_message(
    item: Mapping[str, Any],
    *,
    path: str,
) -> NormalizedMessage:
    _reject_unknown_fields(item, {"content", "role", "type"}, path=path)
    role = item.get("role")
    if role not in {"system", "user", "assistant"}:
        if isinstance(role, str):
            _unsupported(f"{path}.role")
        _invalid(f"{path}.role")
    content = item.get("content")
    if isinstance(content, str):
        return NormalizedMessage(role=role, content=content)
    if not isinstance(content, list) or not content:
        _invalid(f"{path}.content")

    parts = [
        _normalize_text_part(part, path=f"{path}.content[{index}]", role=role)
        for index, part in enumerate(content)
    ]
    return NormalizedMessage(role=role, content=parts)


def _normalize_text_part(
    value: Any,
    *,
    path: str,
    role: str,
) -> NormalizedContentPart:
    if not isinstance(value, Mapping):
        _invalid(path)
    _reject_unknown_fields(value, {"text", "type"}, path=path)
    part_type = value.get("type")
    expected_type = "output_text" if role == "assistant" else "input_text"
    if part_type != expected_type:
        if isinstance(part_type, str):
            _unsupported(f"{path}.type")
        _invalid(f"{path}.type")
    text = value.get("text")
    if not isinstance(text, str):
        _invalid(f"{path}.text")
    return NormalizedContentPart(type="text", text=text)


def _normalize_function_call(
    item: Mapping[str, Any],
    *,
    path: str,
) -> NormalizedMessage:
    _reject_unknown_fields(
        item,
        {"arguments", "call_id", "name", "type"},
        path=path,
    )
    call_id = _required_string(item.get("call_id"), f"{path}.call_id")
    name = _required_string(item.get("name"), f"{path}.name")
    arguments = item.get("arguments")
    if not isinstance(arguments, str):
        _invalid(f"{path}.arguments")
    return NormalizedMessage(
        role="assistant",
        content=None,
        tool_calls=[
            NormalizedToolCall(
                id=call_id,
                type="function",
                name=name,
                arguments=arguments,
            )
        ],
    )


def _normalize_function_output(
    item: Mapping[str, Any],
    *,
    path: str,
) -> NormalizedMessage:
    _reject_unknown_fields(item, {"call_id", "output", "type"}, path=path)
    call_id = _required_string(item.get("call_id"), f"{path}.call_id")
    output = item.get("output")
    if not isinstance(output, str):
        _invalid(f"{path}.output")
    return NormalizedMessage(
        role="tool",
        content=output,
        tool_call_id=call_id,
    )


def _normalize_responses_tools(value: Any) -> list[NormalizedTool]:
    if value is None:
        return []
    if not isinstance(value, list):
        _invalid("tools")

    tools: list[NormalizedTool] = []
    names: set[str] = set()
    for index, item in enumerate(value):
        path = f"tools[{index}]"
        if not isinstance(item, Mapping):
            _invalid(path)
        if item.get("type") != "function":
            _unsupported(f"{path}.type")
        _reject_unknown_fields(
            item,
            {"description", "name", "parameters", "strict", "type"},
            path=path,
        )
        name = _required_string(item.get("name"), f"{path}.name")
        if name in names:
            _invalid(f"{path}.name")
        names.add(name)
        description = item.get("description")
        if description is not None and not isinstance(description, str):
            _invalid(f"{path}.description")
        parameters = item.get("parameters", {})
        if not isinstance(parameters, Mapping):
            _invalid(f"{path}.parameters")
        strict = item.get("strict")
        if strict is not None and not isinstance(strict, bool):
            _invalid(f"{path}.strict")
        tools.append(
            NormalizedTool(
                type="function",
                name=name,
                description=description,
                parameters=normalize_tool_parameters_schema(parameters),
                raw_extensions=(
                    {"function": {"strict": strict}} if strict is not None else {}
                ),
            )
        )
    return tools


def _normalize_responses_tool_choice(
    value: Any,
    tools: list[NormalizedTool],
) -> Any | None:
    if value is None:
        return None
    if isinstance(value, str) and value in {"auto", "none", "required"}:
        return value
    if not isinstance(value, Mapping):
        _invalid("tool_choice")
    _reject_unknown_fields(value, {"name", "type"}, path="tool_choice")
    if value.get("type") != "function":
        _unsupported("tool_choice.type")
    name = _required_string(value.get("name"), "tool_choice.name")
    if name not in {tool.name for tool in tools}:
        _invalid("tool_choice.name")
    return {"type": "function", "function": {"name": name}}


def _normalize_text_format(value: Any) -> NormalizedResponseFormat | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        _invalid("text")
    _reject_unknown_fields(value, {"format"}, path="text")
    response_format = value.get("format")
    if response_format is None:
        return None
    if not isinstance(response_format, Mapping):
        _invalid("text.format")
    _reject_unknown_fields(
        response_format,
        {"name", "schema", "strict", "type"},
        path="text.format",
    )
    if response_format.get("type") != "json_schema":
        _unsupported("text.format.type")
    name = _required_string(response_format.get("name"), "text.format.name")
    schema = response_format.get("schema")
    if not isinstance(schema, Mapping):
        _invalid("text.format.schema")
    strict = response_format.get("strict")
    if strict is not None and not isinstance(strict, bool):
        _invalid("text.format.strict")
    json_schema: dict[str, Any] = {"name": name, "schema": dict(schema)}
    if strict is not None:
        json_schema["strict"] = strict
    return NormalizedResponseFormat(type="json_schema", json_schema=json_schema)


def _normalize_generation_config(
    data: Mapping[str, Any],
) -> NormalizedGenerationConfig:
    temperature = _optional_number(data.get("temperature"), "temperature")
    top_p = _optional_number(data.get("top_p"), "top_p")
    max_tokens = data.get("max_output_tokens")
    if max_tokens is not None and (
        isinstance(max_tokens, bool)
        or not isinstance(max_tokens, int)
        or max_tokens <= 0
    ):
        _invalid("max_output_tokens")
    return NormalizedGenerationConfig(
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
    )


def _optional_number(value: Any, param: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _invalid(param)
    return float(value)


def _required_string(value: Any, param: str) -> str:
    if not isinstance(value, str) or not value:
        _invalid(param)
    return value


def _reject_unknown_fields(
    value: Mapping[str, Any],
    allowed: set[str] | frozenset[str],
    *,
    path: str | None = None,
) -> None:
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        field = unknown[0]
        _unsupported(f"{path}.{field}" if path else field)


def _invalid(param: str) -> NoReturn:
    raise ClientCompatibilityError(
        _INVALID_MESSAGE,
        param=param,
        code="invalid_request",
    )


def _unsupported(param: str) -> NoReturn:
    raise ClientCompatibilityError(
        _UNSUPPORTED_MESSAGE,
        param=param,
        code="unsupported_semantic",
    )
