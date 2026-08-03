"""Fail-closed OpenAI Responses request decoding for normalized execution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, NoReturn

from gpt2giga.common.client_params import ClientCompatibilityError
from gpt2giga.core.context import RequestContext
from gpt2giga.protocols.normalized import (
    NormalizedChatRequest,
    NormalizedContentPart,
    NormalizedGenerationConfig,
    NormalizedMessage,
    NormalizedResponseFormat,
    NormalizedToolCall,
)
from gpt2giga.protocols.normalized.models import (
    NormalizedReasoningIntent,
    NormalizedStateIntent,
)
from gpt2giga.protocols.openai.responses_tools import (
    normalize_responses_tool_choice,
    normalize_responses_tools,
)


_RESPONSES_FIELDS = frozenset(
    {
        "input",
        "background",
        "conversation",
        "include",
        "instructions",
        "max_output_tokens",
        "metadata",
        "model",
        "previous_response_id",
        "reasoning",
        "reasoning_effort",
        "store",
        "stream",
        "temperature",
        "text",
        "tool_choice",
        "tools",
        "top_p",
    }
)
_REASONING_EFFORTS = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh", "max"}
)
_REASONING_SUMMARIES = frozenset({"auto", "concise", "detailed"})
_REASONING_CONTEXTS = frozenset({"auto", "current_turn", "all_turns"})
_RESPONSE_INCLUDES = frozenset(
    {
        "code_interpreter_call.outputs",
        "computer_call_output.output.image_url",
        "file_search_call.results",
        "message.input_image.image_url",
        "message.output_text.logprobs",
        "reasoning.encrypted_content",
        "web_search_call.action.sources",
        "web_search_call.results",
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
    _reject_unknown_fields(data, _RESPONSES_FIELDS)

    model = data.get("model")
    if not isinstance(model, str) or not model.strip():
        _invalid("model")
    if "input" not in data:
        _invalid("input")

    messages = _normalize_instructions(data.get("instructions"))
    messages.extend(_normalize_input(data["input"]))
    tools = normalize_responses_tools(data.get("tools"))
    tool_choice = normalize_responses_tool_choice(data.get("tool_choice"), tools)

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
        reasoning=_normalize_reasoning_intent(data),
        response_state=_normalize_state_intent(data),
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


def _normalize_reasoning_intent(
    data: Mapping[str, Any],
) -> NormalizedReasoningIntent | None:
    reasoning = data.get("reasoning")
    effort_alias = data.get("reasoning_effort")
    if reasoning is None and effort_alias is None:
        return None
    if reasoning is not None and not isinstance(reasoning, Mapping):
        _invalid("reasoning")
    reasoning_data = dict(reasoning) if isinstance(reasoning, Mapping) else {}
    _reject_unknown_fields(
        reasoning_data,
        {"context", "effort", "generate_summary", "mode", "summary"},
        path="reasoning",
    )

    effort = reasoning_data.get("effort")
    if effort is not None and effort not in _REASONING_EFFORTS:
        _invalid("reasoning.effort")
    if effort_alias is not None:
        if effort_alias not in _REASONING_EFFORTS:
            _invalid("reasoning_effort")
        if effort is not None and effort_alias != effort:
            _invalid("reasoning_effort")
        effort = effort_alias
    summary = reasoning_data.get("summary")
    if summary is not None and summary not in _REASONING_SUMMARIES:
        _invalid("reasoning.summary")
    generate_summary = reasoning_data.get("generate_summary")
    if generate_summary is not None and generate_summary not in _REASONING_SUMMARIES:
        _invalid("reasoning.generate_summary")
    context = reasoning_data.get("context")
    if context is not None and context not in _REASONING_CONTEXTS:
        _invalid("reasoning.context")
    mode = reasoning_data.get("mode")
    if mode is not None:
        _required_string(mode, "reasoning.mode")
    return NormalizedReasoningIntent(
        effort=effort,
        summary=summary,
        generate_summary=generate_summary,
        context=context,
        mode=mode,
    )


def _normalize_state_intent(data: Mapping[str, Any]) -> NormalizedStateIntent | None:
    state_fields = {
        "background",
        "conversation",
        "include",
        "previous_response_id",
        "store",
    }
    if not any(field in data for field in state_fields):
        return None

    previous_response_id = data.get("previous_response_id")
    if previous_response_id is not None:
        previous_response_id = _required_string(
            previous_response_id,
            "previous_response_id",
        )
    conversation = data.get("conversation")
    conversation_id: str | None = None
    if isinstance(conversation, str):
        conversation_id = _required_string(conversation, "conversation")
    elif isinstance(conversation, Mapping):
        _reject_unknown_fields(conversation, {"id"}, path="conversation")
        conversation_id = _required_string(conversation.get("id"), "conversation.id")
    elif conversation is not None:
        _invalid("conversation")
    if previous_response_id is not None and conversation_id is not None:
        _invalid("conversation")

    include = data.get("include")
    include_values: list[str] = []
    if include is not None:
        if not isinstance(include, list) or any(
            not isinstance(value, str) or not value for value in include
        ):
            _invalid("include")
        unknown_includes = sorted(set(include) - _RESPONSE_INCLUDES)
        if unknown_includes:
            _unsupported("include")
        include_values = list(include)

    store = data.get("store")
    if store is not None and not isinstance(store, bool):
        _invalid("store")
    background = data.get("background")
    if background is not None and not isinstance(background, bool):
        _invalid("background")
    return NormalizedStateIntent(
        previous_response_id=previous_response_id,
        conversation_id=conversation_id,
        include=include_values,
        store=store,
        background=background,
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
