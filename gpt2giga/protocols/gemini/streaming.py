"""Map normalized stream events to Gemini-compatible SSE chunks."""

from __future__ import annotations

import json
from typing import Any

from gpt2giga.protocols.gemini.response_adapter import _usage_to_gemini
from gpt2giga.protocols.normalized import NormalizedStreamEvent, NormalizedToolCall


def normalized_stream_event_to_gemini_sse(
    event: NormalizedStreamEvent,
    *,
    requested_model: str,
    response_id: str,
) -> str | None:
    """Return one Gemini-compatible SSE frame for a normalized stream event."""
    payload = normalized_stream_event_to_gemini_chunk(
        event,
        requested_model=requested_model,
        response_id=response_id,
    )
    if payload is None:
        return None
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def normalized_stream_event_to_gemini_chunk(
    event: NormalizedStreamEvent,
    *,
    requested_model: str,
    response_id: str,
) -> dict[str, Any] | None:
    """Return one Gemini GenerateContentResponse chunk."""
    if event.type in {"heartbeat", "message_start"}:
        return None
    if event.type == "error":
        error = event.error
        return {
            "error": {
                "code": error.code if error else "stream_error",
                "message": error.message if error else "Stream interrupted",
                "status": error.type if error else "stream_error",
            }
        }
    if event.type == "usage":
        return _base_chunk(
            event,
            requested_model=requested_model,
            response_id=response_id,
            usage=_usage_to_gemini(event.usage),
        )
    if event.type == "content_delta":
        return _base_chunk(
            event,
            requested_model=requested_model,
            response_id=response_id,
            candidates=[
                {
                    "index": event.choice_index,
                    "content": {
                        "role": "model",
                        "parts": [{"text": event.content_delta or ""}],
                    },
                }
            ],
        )
    if event.type in {"tool_call_start", "tool_call_delta"}:
        return _base_chunk(
            event,
            requested_model=requested_model,
            response_id=response_id,
            candidates=[
                {
                    "index": event.choice_index,
                    "content": {
                        "role": "model",
                        "parts": [_tool_call_part(event.tool_call)],
                    },
                }
            ],
        )
    if event.type == "message_end":
        candidate = {
            "index": event.choice_index,
            "finishReason": _finish_reason(event.finish_reason),
        }
        if event.content_delta:
            candidate["content"] = {
                "role": "model",
                "parts": [{"text": event.content_delta}],
            }
        return _base_chunk(
            event,
            requested_model=requested_model,
            response_id=response_id,
            candidates=[candidate],
            usage=_usage_to_gemini(event.usage),
        )
    return None


def _base_chunk(
    event: NormalizedStreamEvent,
    *,
    requested_model: str,
    response_id: str,
    candidates: list[dict[str, Any]] | None = None,
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "candidates": candidates or [],
        "modelVersion": event.model or requested_model,
        "responseId": event.id or response_id,
    }
    if usage:
        payload["usageMetadata"] = usage
    return payload


def _tool_call_part(tool_call: NormalizedToolCall | None) -> dict[str, Any]:
    if tool_call is None:
        return {"functionCall": {"name": "", "args": {}}}
    args = tool_call.arguments
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {"arguments": args}
    if not isinstance(args, dict):
        args = {} if args is None else {"arguments": args}
    return {
        "functionCall": {
            "name": tool_call.name or "",
            "args": args,
        }
    }


def _finish_reason(value: str | None) -> str:
    return {
        "content_filter": "SAFETY",
        "length": "MAX_TOKENS",
        "stop": "STOP",
        "tool_calls": "STOP",
    }.get(value or "stop", str(value or "stop").upper())
