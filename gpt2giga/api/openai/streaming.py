"""OpenAI-compatible SSE formatting helpers."""

from __future__ import annotations

import json
from typing import Any


def format_chat_stream_chunk(payload: dict[str, Any]) -> str:
    """Serialize a chat chunk as an OpenAI SSE data line."""
    return f"data: {json.dumps(payload)}\n\n"


def format_chat_stream_done() -> str:
    """Serialize the OpenAI chat stream terminator."""
    return "data: [DONE]\n\n"


def format_responses_stream_event(event_type: str, payload: dict[str, Any]) -> str:
    """Serialize a Responses API event as SSE."""
    return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
