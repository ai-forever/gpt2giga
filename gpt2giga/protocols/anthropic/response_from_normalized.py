"""Map normalized chat-like results to Anthropic Messages payloads."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Mapping
from datetime import datetime
from typing import Any

from gpt2giga.common.tools import map_tool_name_from_gigachat
from gpt2giga.protocols.normalized import (
    NormalizedContentPart,
    NormalizedMessage,
    NormalizedResponse,
    NormalizedToolCall,
    NormalizedUsage,
)


def normalized_response_to_anthropic_message(
    response: NormalizedResponse,
    *,
    requested_model: str,
    response_id: str,
    is_structured_output: bool = False,
) -> dict[str, Any]:
    """Convert a normalized non-streaming result to Anthropic Messages shape."""
    message = _first_message(response)
    content_blocks, stop_reason = _message_to_content_blocks(
        message,
        finish_reason=_first_finish_reason(response),
        is_structured_output=is_structured_output,
    )
    return {
        "id": _message_id(response_id),
        "type": "message",
        "role": "assistant",
        "content": content_blocks,
        "model": requested_model,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": _usage_to_anthropic(response.usage),
    }


async def buffered_anthropic_sse_from_normalized_response(
    response: NormalizedResponse,
    *,
    requested_model: str,
    response_id: str,
    is_structured_output: bool = False,
) -> AsyncIterator[str]:
    """Emit buffered Anthropic Messages SSE frames from a completed result."""
    yield _sse_event(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": _message_id(response_id),
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": requested_model,
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {
                    "input_tokens": _usage_input_tokens(response.usage),
                    "output_tokens": 0,
                },
            },
        },
    )
    yield _sse_event("ping", {"type": "ping"})

    if response.error is not None:
        yield _sse_event(
            "error",
            {
                "type": "error",
                "error": {
                    "type": response.error.type,
                    "message": response.error.message,
                    "code": response.error.code,
                },
            },
        )
        return

    final_message = normalized_response_to_anthropic_message(
        response,
        requested_model=requested_model,
        response_id=response_id,
        is_structured_output=is_structured_output,
    )
    for index, block in enumerate(final_message["content"]):
        for event in _content_block_sse_events(block, index=index):
            yield event

    yield _sse_event(
        "message_delta",
        {
            "type": "message_delta",
            "delta": {
                "stop_reason": final_message["stop_reason"],
                "stop_sequence": None,
            },
            "usage": {
                "output_tokens": final_message["usage"]["output_tokens"],
            },
        },
    )
    yield _sse_event("message_stop", {"type": "message_stop"})


def _message_to_content_blocks(
    message: NormalizedMessage | None,
    *,
    finish_reason: str | None,
    is_structured_output: bool,
) -> tuple[list[dict[str, Any]], str]:
    if message is None:
        return ([{"type": "text", "text": ""}], _finish_reason_to_stop_reason(None))

    reasoning = _string_or_none(message.raw_extensions.get("reasoning_content"))
    content_blocks: list[dict[str, Any]] = []
    if reasoning:
        content_blocks.append({"type": "thinking", "thinking": reasoning})

    if is_structured_output and message.tool_calls:
        content_blocks.append(
            {
                "type": "text",
                "text": _tool_arguments_to_json(message.tool_calls[0].arguments),
            }
        )
        return content_blocks, "end_turn"

    text_content = _message_content_text(message)
    if text_content:
        content_blocks.append({"type": "text", "text": text_content})

    if message.tool_calls:
        content_blocks.extend(
            _tool_call_to_content_block(tool_call) for tool_call in message.tool_calls
        )
        return content_blocks, "tool_use"

    if not content_blocks:
        content_blocks.append({"type": "text", "text": ""})
    return content_blocks, _finish_reason_to_stop_reason(finish_reason)


def _content_block_sse_events(
    block: Mapping[str, Any],
    *,
    index: int,
) -> list[str]:
    block_type = block.get("type")
    events = [
        _sse_event(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": index,
                "content_block": _content_block_start_payload(block),
            },
        )
    ]

    if block_type == "text":
        text = _string_or_none(block.get("text")) or ""
        if text:
            events.append(
                _sse_event(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": index,
                        "delta": {"type": "text_delta", "text": text},
                    },
                )
            )
    elif block_type == "thinking":
        thinking = _string_or_none(block.get("thinking")) or ""
        if thinking:
            events.append(
                _sse_event(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": index,
                        "delta": {
                            "type": "thinking_delta",
                            "thinking": thinking,
                        },
                    },
                )
            )
    elif block_type == "tool_use":
        input_json = json.dumps(block.get("input") or {}, ensure_ascii=False)
        if input_json:
            events.append(
                _sse_event(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": index,
                        "delta": {
                            "type": "input_json_delta",
                            "partial_json": input_json,
                        },
                    },
                )
            )

    events.append(
        _sse_event(
            "content_block_stop",
            {"type": "content_block_stop", "index": index},
        )
    )
    return events


def _content_block_start_payload(block: Mapping[str, Any]) -> dict[str, Any]:
    block_type = block.get("type")
    if block_type == "thinking":
        return {"type": "thinking", "thinking": ""}
    if block_type == "tool_use":
        return {
            "type": "tool_use",
            "id": block.get("id"),
            "name": block.get("name"),
            "input": {},
        }
    return {"type": "text", "text": ""}


def _tool_call_to_content_block(tool_call: NormalizedToolCall) -> dict[str, Any]:
    return {
        "type": "tool_use",
        "id": tool_call.id or f"toolu_{uuid.uuid4().hex[:24]}",
        "name": map_tool_name_from_gigachat(tool_call.name or ""),
        "input": _tool_arguments_to_object(tool_call.arguments),
    }


def _first_message(response: NormalizedResponse) -> NormalizedMessage | None:
    for choice in response.choices:
        if choice.message is not None:
            return choice.message
    return None


def _first_finish_reason(response: NormalizedResponse) -> str | None:
    for choice in response.choices:
        if choice.finish_reason is not None:
            return choice.finish_reason
    return None


def _message_content_text(message: NormalizedMessage) -> str:
    content = message.content
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    text_parts: list[str] = []
    for part in content:
        part_text = _content_part_text(part)
        if part_text:
            text_parts.append(part_text)
    return "".join(text_parts)


def _content_part_text(part: NormalizedContentPart) -> str:
    if part.type == "text":
        return part.text or ""
    if part.text:
        return part.text
    if part.data is not None:
        return json.dumps(part.data, ensure_ascii=False)
    return ""


def _tool_arguments_to_json(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value or {}, ensure_ascii=False)


def _tool_arguments_to_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    return {}


def _finish_reason_to_stop_reason(finish_reason: str | None) -> str:
    mapping = {
        "stop": "end_turn",
        "length": "max_tokens",
        "tool_calls": "tool_use",
        "function_call": "tool_use",
        "content_filter": "end_turn",
    }
    return mapping.get(finish_reason or "stop", "end_turn")


def _usage_to_anthropic(usage: NormalizedUsage | None) -> dict[str, int]:
    return {
        "input_tokens": _usage_input_tokens(usage),
        "output_tokens": _usage_output_tokens(usage),
    }


def _usage_input_tokens(usage: NormalizedUsage | None) -> int:
    value = usage.input_tokens if usage is not None else None
    return value if isinstance(value, int) else 0


def _usage_output_tokens(usage: NormalizedUsage | None) -> int:
    value = usage.output_tokens if usage is not None else None
    return value if isinstance(value, int) else 0


def _message_id(response_id: str) -> str:
    return response_id if response_id.startswith("msg_") else f"msg_{response_id}"


def _sse_event(event_type: str, data: Mapping[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
