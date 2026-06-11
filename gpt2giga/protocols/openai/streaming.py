"""Map normalized stream events to OpenAI-compatible SSE chunks."""

from __future__ import annotations

import json
from datetime import timezone
from typing import Any

from gpt2giga.protocols.normalized import (
    NormalizedMessage,
    NormalizedStreamEvent,
    NormalizedToolCall,
    NormalizedUsage,
)


def normalized_stream_event_to_openai_sse(
    event: NormalizedStreamEvent,
    *,
    requested_model: str,
    response_id: str,
) -> str | None:
    """Return one OpenAI-compatible SSE frame for a normalized stream event."""
    if event.type == "heartbeat":
        return None

    chunk = normalized_stream_event_to_openai_chunk(
        event,
        requested_model=requested_model,
        response_id=response_id,
    )
    if chunk is None:
        return None
    return f"data: {json.dumps(chunk)}\n\n"


def normalized_stream_done_sse() -> str:
    """Return the OpenAI-compatible terminal SSE frame."""
    return "data: [DONE]\n\n"


def normalized_stream_event_to_openai_chunk(
    event: NormalizedStreamEvent,
    *,
    requested_model: str,
    response_id: str,
) -> dict[str, Any] | None:
    """Return an OpenAI Chat Completions stream chunk for one event."""
    legacy_chunk = event.raw_extensions.get("openai_chunk")
    if isinstance(legacy_chunk, dict):
        return legacy_chunk

    if event.type == "message_start":
        return None
    if event.type == "error":
        error = event.error
        return {
            "error": {
                "message": error.message if error else "Stream interrupted",
                "type": error.type if error else "stream_error",
                "code": error.code if error else "stream_error",
            }
        }

    chunk = _base_chunk(event, requested_model=requested_model, response_id=response_id)
    if event.type == "content_delta":
        chunk["choices"] = [
            _choice(
                event,
                delta={"content": event.content_delta or _message_content(event.delta)},
            )
        ]
    elif event.type == "reasoning_delta":
        chunk["choices"] = [
            _choice(
                event,
                delta={
                    "content": "",
                    "reasoning_content": event.reasoning_delta
                    or _message_reasoning(event.delta),
                },
            )
        ]
    elif event.type in {"tool_call_start", "tool_call_delta"}:
        chunk["choices"] = [
            _choice(event, delta={"tool_calls": [_tool_call_delta(event.tool_call)]})
        ]
    elif event.type == "usage":
        chunk["usage"] = _usage(event.usage)
    elif event.type == "message_end":
        chunk["choices"] = [
            _choice(event, delta={}, finish_reason=event.finish_reason or "stop")
        ]
    else:
        return None
    return chunk


def _base_chunk(
    event: NormalizedStreamEvent,
    *,
    requested_model: str,
    response_id: str,
) -> dict[str, Any]:
    created_at = event.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return {
        "id": f"chatcmpl-{event.id or response_id}",
        "object": "chat.completion.chunk",
        "created": int(created_at.timestamp()),
        "model": event.model or requested_model,
        "choices": [],
        "usage": None,
        "system_fingerprint": f"fp_{event.id or response_id}",
    }


def _choice(
    event: NormalizedStreamEvent,
    *,
    delta: dict[str, Any],
    finish_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "index": event.choice_index,
        "delta": {key: value for key, value in delta.items() if value is not None},
        "finish_reason": finish_reason,
        "logprobs": None,
    }


def _message_content(message: NormalizedMessage | None) -> str:
    if message is None:
        return ""
    content = message.content
    return content if isinstance(content, str) else ""


def _message_reasoning(message: NormalizedMessage | None) -> str:
    if message is None:
        return ""
    value = message.raw_extensions.get("reasoning_content")
    return value if isinstance(value, str) else ""


def _tool_call_delta(tool_call: NormalizedToolCall | None) -> dict[str, Any]:
    if tool_call is None:
        return {"index": 0, "function": {}}
    function = {
        "name": tool_call.name,
        "arguments": tool_call.arguments,
    }
    return {
        "index": int(tool_call.raw_extensions.get("index", 0)),
        "id": tool_call.id,
        "type": tool_call.type,
        "function": {
            key: value for key, value in function.items() if value is not None
        },
    }


def _usage(usage: NormalizedUsage | None) -> dict[str, Any] | None:
    if usage is None:
        return None
    return {
        "prompt_tokens": usage.input_tokens,
        "completion_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "prompt_tokens_details": {"cached_tokens": 0},
        "completion_tokens_details": {"reasoning_tokens": 0},
    }
