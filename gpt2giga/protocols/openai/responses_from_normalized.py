"""Map normalized chat-like results to OpenAI Responses payloads."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Mapping
from typing import Any

from gpt2giga.common.client_params import merge_openai_response_metadata
from gpt2giga.common.json_schema import normalize_tool_parameters_schema
from gpt2giga.core.context import RequestContext
from gpt2giga.protocols.normalized import (
    NormalizedChatRequest,
    NormalizedContentPart,
    NormalizedGenerationConfig,
    NormalizedMessage,
    NormalizedResponse,
    NormalizedResponseFormat,
    NormalizedTool,
    NormalizedToolCall,
    NormalizedUsage,
)

_RESPONSES_TOP_LEVEL_FIELDS = {
    "additional_fields",
    "extra_body",
    "input",
    "instructions",
    "max_output_tokens",
    "metadata",
    "model",
    "parallel_tool_calls",
    "plugins",
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
    "truncation",
    "user",
}


def responses_request_to_normalized(
    payload: Mapping[str, Any],
    *,
    context: RequestContext | None = None,
) -> NormalizedChatRequest:
    """Convert an OpenAI Responses request to a normalized chat-like request."""
    metadata = (
        dict(payload["metadata"])
        if isinstance(payload.get("metadata"), Mapping)
        else {}
    )
    raw_extensions = _build_raw_extensions(payload)
    provider_metadata = _build_provider_metadata(payload)
    return NormalizedChatRequest(
        id=context.request_id if context is not None else None,
        protocol="openai",
        operation="responses",
        model=_string_or_none(payload.get("model")),
        stream=bool(payload.get("stream", False)),
        messages=_responses_input_to_messages(payload),
        tools=_responses_tools_to_normalized(payload.get("tools")),
        tool_choice=payload.get("tool_choice"),
        response_format=_responses_response_format(payload.get("text")),
        generation_config=NormalizedGenerationConfig(
            temperature=payload.get("temperature"),
            top_p=payload.get("top_p"),
            max_tokens=payload.get("max_output_tokens"),
        ),
        user=_string_or_none(payload.get("user")),
        metadata=metadata,
        raw_extensions=raw_extensions,
        provider_metadata=provider_metadata,
    )


def normalized_response_to_openai_response(
    response: NormalizedResponse,
    *,
    request_payload: Mapping[str, Any],
    requested_model: str,
    response_id: str,
) -> dict[str, Any]:
    """Convert a normalized non-streaming result to OpenAI Responses shape."""
    output = _response_output(response, response_id=response_id)
    status = "failed" if response.error is not None else "completed"
    result = _base_response_payload(
        request_payload=request_payload,
        requested_model=requested_model,
        response_id=response_id,
        status=status,
        output=output,
        usage=_usage_to_responses(response.usage),
        response_metadata=_metadata_to_responses(response),
    )
    if response.error is not None:
        result["error"] = {
            "type": response.error.type,
            "message": response.error.message,
            "code": response.error.code,
            "param": response.error.param,
        }
    output_text = _output_text(output)
    if output_text:
        result["output_text"] = output_text
    return result


async def buffered_response_sse_from_normalized_response(
    response: NormalizedResponse,
    *,
    request_payload: Mapping[str, Any],
    requested_model: str,
    response_id: str,
) -> AsyncIterator[str]:
    """Emit buffered OpenAI Responses SSE frames from a completed result."""
    final_response = normalized_response_to_openai_response(
        response,
        request_payload=request_payload,
        requested_model=requested_model,
        response_id=response_id,
    )
    sequence = 0
    in_progress = {
        **final_response,
        "status": "in_progress",
        "output": [],
        "usage": None,
        "error": None,
    }
    in_progress.pop("output_text", None)
    yield _sse_event(
        "response.created",
        {
            "type": "response.created",
            "response": in_progress,
            "sequence_number": sequence,
        },
    )
    sequence += 1
    yield _sse_event(
        "response.in_progress",
        {
            "type": "response.in_progress",
            "response": in_progress,
            "sequence_number": sequence,
        },
    )
    sequence += 1

    if response.error is not None:
        failed = {**final_response, "status": "failed"}
        yield _sse_event(
            "response.failed",
            {
                "type": "response.failed",
                "response": failed,
                "sequence_number": sequence,
            },
        )
        return

    for output_index, item in enumerate(final_response.get("output") or []):
        for event in _output_item_sse_events(
            item,
            output_index=output_index,
            sequence_start=sequence,
        ):
            yield event
            sequence += 1

    yield _sse_event(
        "response.completed",
        {
            "type": "response.completed",
            "response": final_response,
            "sequence_number": sequence,
        },
    )


def _build_raw_extensions(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in _RESPONSES_TOP_LEVEL_FIELDS and value is not None
    }


def _build_provider_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    additional_fields: dict[str, Any] = {}
    extra_body = payload.get("extra_body")
    if isinstance(extra_body, Mapping):
        additional_fields.update(dict(extra_body))

    existing_additional = payload.get("additional_fields")
    if isinstance(existing_additional, Mapping):
        additional_fields.update(dict(existing_additional))

    if not additional_fields:
        return {}
    return {"gigachat": {"additional_fields": additional_fields}}


def _responses_input_to_messages(payload: Mapping[str, Any]) -> list[NormalizedMessage]:
    messages: list[NormalizedMessage] = []
    instructions = payload.get("instructions")
    if instructions is not None:
        messages.append(
            NormalizedMessage(role="system", content=_content_to_text(instructions))
        )

    input_value = payload.get("input")
    if isinstance(input_value, list):
        for item in input_value:
            message = _responses_input_item_to_message(item)
            if message is not None:
                messages.append(message)
    elif input_value is not None:
        messages.append(
            NormalizedMessage(role="user", content=_content_to_text(input_value))
        )
    return messages


def _responses_input_item_to_message(value: Any) -> NormalizedMessage | None:
    if not isinstance(value, Mapping):
        return NormalizedMessage(role="user", content=_content_to_text(value))

    item_type = value.get("type")
    if item_type == "function_call":
        return NormalizedMessage(
            role="assistant",
            content=None,
            tool_calls=[
                NormalizedToolCall(
                    id=_string_or_none(value.get("call_id") or value.get("id")),
                    name=_string_or_none(value.get("name")),
                    arguments=value.get("arguments"),
                )
            ],
            raw_extensions=_raw_extensions(
                value, {"type", "call_id", "id", "name", "arguments"}
            ),
        )
    if item_type == "function_call_output":
        return NormalizedMessage(
            role="tool",
            content=_content_to_text(value.get("output")),
            tool_call_id=_string_or_none(value.get("call_id") or value.get("id")),
            raw_extensions=_raw_extensions(value, {"type", "output", "call_id", "id"}),
        )

    role = _string_or_none(value.get("role")) or "user"
    return NormalizedMessage(
        role=role,
        content=_normalize_responses_content(value.get("content", value.get("text"))),
        raw_extensions=_raw_extensions(value, {"role", "content", "text"}),
    )


def _normalize_responses_content(
    value: Any,
) -> str | list[NormalizedContentPart] | None:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return _content_to_text(value)

    parts: list[NormalizedContentPart] = []
    for part in value:
        if not isinstance(part, Mapping):
            parts.append(
                NormalizedContentPart(type="text", text=_content_to_text(part))
            )
            continue
        part_type = str(part.get("type", "text"))
        if part_type in {"input_text", "output_text", "text"}:
            parts.append(
                NormalizedContentPart(
                    type="text",
                    text=_string_or_none(part.get("text")) or "",
                    raw_extensions=_raw_extensions(part, {"type", "text"}),
                )
            )
            continue
        if part_type in {"input_image", "image_url"}:
            image_url = part.get("image_url") or part.get("url") or part
            parts.append(
                NormalizedContentPart(
                    type="image_url",
                    data=image_url,
                    raw_extensions=_raw_extensions(
                        part,
                        {"type", "image_url", "url"},
                    ),
                )
            )
            continue
        parts.append(
            NormalizedContentPart(
                type=part_type,
                data=dict(part),
                raw_extensions=_raw_extensions(part, {"type"}),
            )
        )
    return parts


def _responses_tools_to_normalized(value: Any) -> list[NormalizedTool]:
    if not isinstance(value, list):
        return []
    tools: list[NormalizedTool] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        function = item.get("function")
        data = function if isinstance(function, Mapping) else item
        name = data.get("name") or item.get("name") or item.get("type")
        if not isinstance(name, str) or not name:
            continue
        parameters = (
            data.get("parameters") or data.get("input_schema") or data.get("schema")
        )
        tools.append(
            NormalizedTool(
                type=_string_or_none(item.get("type")) or "function",
                name=name,
                description=_string_or_none(data.get("description")),
                parameters=normalize_tool_parameters_schema(parameters)
                if isinstance(parameters, Mapping)
                else {},
                raw_extensions=_raw_extensions(
                    item,
                    {
                        "type",
                        "function",
                        "name",
                        "description",
                        "parameters",
                        "input_schema",
                        "schema",
                    },
                ),
            )
        )
    return tools


def _responses_response_format(value: Any) -> NormalizedResponseFormat | None:
    if not isinstance(value, Mapping):
        return None
    format_value = value.get("format")
    if not isinstance(format_value, Mapping):
        return None
    response_type = format_value.get("type")
    if not isinstance(response_type, str):
        return None
    json_schema = format_value.get("json_schema") or format_value.get("schema")
    return NormalizedResponseFormat(
        type=response_type,
        json_schema=dict(json_schema) if isinstance(json_schema, Mapping) else None,
        raw_extensions=_raw_extensions(format_value, {"type", "json_schema", "schema"}),
    )


def _response_output(
    response: NormalizedResponse,
    *,
    response_id: str,
) -> list[dict[str, Any]]:
    if response.error is not None:
        return []
    output: list[dict[str, Any]] = []
    message = _first_response_message(response)
    if message is None:
        return output

    reasoning = _string_or_none(message.raw_extensions.get("reasoning_content"))
    if reasoning:
        output.append(
            {
                "id": f"rs_{response_id}",
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": reasoning}],
            }
        )
    for index, tool_call in enumerate(message.tool_calls):
        output.append(
            _tool_call_to_output_item(
                tool_call,
                response_id=response_id,
                index=index,
            )
        )

    content = _message_content_text(message)
    if content or not output:
        output.append(
            {
                "type": "message",
                "id": f"msg_{response_id}",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": content,
                        "annotations": [],
                        "logprobs": [],
                    }
                ],
            }
        )
    return output


def _first_response_message(response: NormalizedResponse) -> NormalizedMessage | None:
    for choice in response.choices:
        if choice.message is not None:
            return choice.message
    return None


def _tool_call_to_output_item(
    tool_call: NormalizedToolCall,
    *,
    response_id: str,
    index: int,
) -> dict[str, Any]:
    call_id = tool_call.id or f"call_{response_id}_{index}"
    return {
        "id": f"fc_{call_id}",
        "type": "function_call",
        "status": "completed",
        "call_id": call_id,
        "name": tool_call.name or "",
        "arguments": _tool_arguments_to_json(tool_call.arguments),
    }


def _base_response_payload(
    *,
    request_payload: Mapping[str, Any],
    requested_model: str,
    response_id: str,
    status: str,
    output: list[dict[str, Any]],
    usage: dict[str, Any] | None,
    response_metadata: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "id": f"resp_{response_id}",
        "object": "response",
        "created_at": int(time.time()),
        "status": status,
        "error": None,
        "incomplete_details": None,
        "instructions": request_payload.get("instructions"),
        "max_output_tokens": request_payload.get("max_output_tokens"),
        "model": requested_model,
        "output": output,
        "parallel_tool_calls": request_payload.get("parallel_tool_calls", True),
        "previous_response_id": request_payload.get("previous_response_id"),
        "reasoning": _build_reasoning_config(request_payload),
        "store": request_payload.get("store", True),
        "temperature": request_payload.get("temperature", 1),
        "text": _response_text_config(request_payload),
        "tool_choice": request_payload.get("tool_choice", "auto"),
        "tools": request_payload.get("tools", []),
        "top_p": request_payload.get("top_p", 1),
        "truncation": request_payload.get("truncation", "disabled"),
        "usage": usage,
        "user": request_payload.get("user"),
        "metadata": merge_openai_response_metadata(
            request_payload.get("metadata", {}),
            response_metadata,
        ),
    }


def _build_reasoning_config(request_payload: Mapping[str, Any]) -> dict[str, Any]:
    reasoning_data = request_payload.get("reasoning")
    if isinstance(reasoning_data, Mapping):
        return {
            "effort": reasoning_data.get("effort"),
            "summary": reasoning_data.get("summary"),
        }
    return {"effort": request_payload.get("reasoning_effort"), "summary": None}


def _response_text_config(request_payload: Mapping[str, Any]) -> dict[str, Any]:
    text = request_payload.get("text")
    if isinstance(text, Mapping):
        return dict(text)
    return {"format": {"type": "text"}}


def _output_text(output: list[dict[str, Any]]) -> str:
    texts: list[str] = []
    for item in output:
        if item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, Mapping) and isinstance(part.get("text"), str):
                texts.append(part["text"])
    return "".join(texts)


def _output_item_sse_events(
    item: Mapping[str, Any],
    *,
    output_index: int,
    sequence_start: int,
) -> list[str]:
    sequence = sequence_start
    in_progress_item = dict(item)
    if in_progress_item.get("status") == "completed":
        in_progress_item["status"] = "in_progress"
    events = [
        _sse_event(
            "response.output_item.added",
            {
                "type": "response.output_item.added",
                "output_index": output_index,
                "item": in_progress_item,
                "sequence_number": sequence,
            },
        )
    ]
    sequence += 1

    if item.get("type") == "message":
        content = item.get("content")
        part = content[0] if isinstance(content, list) and content else None
        if isinstance(part, Mapping):
            events.append(
                _sse_event(
                    "response.content_part.added",
                    {
                        "type": "response.content_part.added",
                        "item_id": item.get("id"),
                        "output_index": output_index,
                        "content_index": 0,
                        "part": {**dict(part), "text": ""},
                        "sequence_number": sequence,
                    },
                )
            )
            sequence += 1
            text = _string_or_none(part.get("text")) or ""
            if text:
                events.append(
                    _sse_event(
                        "response.output_text.delta",
                        {
                            "type": "response.output_text.delta",
                            "item_id": item.get("id"),
                            "output_index": output_index,
                            "content_index": 0,
                            "delta": text,
                            "sequence_number": sequence,
                        },
                    )
                )
                sequence += 1
            events.extend(
                [
                    _sse_event(
                        "response.output_text.done",
                        {
                            "type": "response.output_text.done",
                            "item_id": item.get("id"),
                            "output_index": output_index,
                            "content_index": 0,
                            "text": text,
                            "sequence_number": sequence,
                        },
                    ),
                    _sse_event(
                        "response.content_part.done",
                        {
                            "type": "response.content_part.done",
                            "item_id": item.get("id"),
                            "output_index": output_index,
                            "content_index": 0,
                            "part": dict(part),
                            "sequence_number": sequence + 1,
                        },
                    ),
                ]
            )
            sequence += 2
    elif item.get("type") == "function_call":
        arguments = _string_or_none(item.get("arguments")) or ""
        if arguments:
            events.append(
                _sse_event(
                    "response.function_call_arguments.delta",
                    {
                        "type": "response.function_call_arguments.delta",
                        "item_id": item.get("id"),
                        "output_index": output_index,
                        "delta": arguments,
                        "sequence_number": sequence,
                    },
                )
            )
            sequence += 1
        events.append(
            _sse_event(
                "response.function_call_arguments.done",
                {
                    "type": "response.function_call_arguments.done",
                    "item_id": item.get("id"),
                    "output_index": output_index,
                    "name": item.get("name"),
                    "arguments": arguments,
                    "sequence_number": sequence,
                },
            )
        )
        sequence += 1

    done_item = dict(item)
    if done_item.get("status") is None:
        done_item["status"] = "completed"
    events.append(
        _sse_event(
            "response.output_item.done",
            {
                "type": "response.output_item.done",
                "output_index": output_index,
                "item": done_item,
                "sequence_number": sequence,
            },
        )
    )
    return events


def _usage_to_responses(usage: NormalizedUsage | None) -> dict[str, Any] | None:
    if usage is None:
        return None
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "prompt_tokens_details": {
            "cached_tokens": usage.raw_extensions.get("precached_prompt_tokens", 0)
        },
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens_details": {"reasoning_tokens": 0},
    }


def _metadata_to_responses(response: NormalizedResponse) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for container in (response.metadata, response.provider_metadata.get("gigachat")):
        if not isinstance(container, Mapping):
            continue
        for key, value in container.items():
            if isinstance(key, str) and isinstance(value, str):
                metadata[key] = value
    return metadata


def _message_content_text(message: NormalizedMessage | None) -> str:
    if message is None:
        return ""
    content = message.content
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for part in content:
        if part.text:
            parts.append(part.text)
        elif part.data is not None:
            parts.append(json.dumps(part.data, ensure_ascii=False, default=str))
    return "".join(parts)


def _tool_arguments_to_json(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value or {}, ensure_ascii=False)


def _content_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def _raw_extensions(value: Mapping[str, Any], excluded: set[str]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key not in excluded}


def _sse_event(event_type: str, data: Mapping[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
