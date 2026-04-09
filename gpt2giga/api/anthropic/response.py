"""Anthropic response and error helpers."""

import json
import uuid
from typing import Optional

from fastapi.responses import JSONResponse

from gpt2giga.core.logging.setup import rquid_context
from gpt2giga.providers.gigachat.tool_mapping import map_tool_name_from_gigachat


def _map_stop_reason(finish_reason: Optional[str]) -> str:
    """Map GigaChat finish_reason to Anthropic stop_reason."""
    mapping = {
        "stop": "end_turn",
        "length": "max_tokens",
        "function_call": "tool_use",
        "content_filter": "end_turn",
    }
    return mapping.get(finish_reason or "stop", "end_turn")


def _build_anthropic_response(
    giga_dict: dict,
    model: str,
    response_id: str,
) -> dict:
    """Build Anthropic Messages API response from a GigaChat response."""
    choice = giga_dict["choices"][0]
    message = choice.get("message", {})
    finish_reason = choice.get("finish_reason", "stop")
    usage = giga_dict.get("usage", {})

    content_blocks: list[dict] = []
    reasoning = message.get("reasoning_content")
    if reasoning:
        content_blocks.append({"type": "thinking", "thinking": reasoning})

    text_content = message.get("content", "") or ""
    if text_content:
        content_blocks.append({"type": "text", "text": text_content})

    tool_calls = list(message.get("tool_calls") or [])
    if message.get("function_call"):
        tool_calls.append({"function": message["function_call"]})

    if tool_calls:
        for tool_call in tool_calls:
            function = tool_call.get("function", {})
            arguments = function.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}
            elif not isinstance(arguments, dict):
                arguments = {}

            content_blocks.append(
                {
                    "type": "tool_use",
                    "id": tool_call.get("id") or f"toolu_{uuid.uuid4().hex[:24]}",
                    "name": map_tool_name_from_gigachat(function.get("name", "")),
                    "input": arguments,
                }
            )
        stop_reason = "tool_use"
    else:
        if not content_blocks:
            content_blocks.append({"type": "text", "text": ""})
        stop_reason = _map_stop_reason(finish_reason)

    return {
        "id": f"msg_{response_id}",
        "type": "message",
        "role": "assistant",
        "content": content_blocks,
        "model": model,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }


def _anthropic_http_exception(
    status_code: int,
    error_type: str,
    message: str,
) -> JSONResponse:
    """Build an Anthropic-style error response."""
    return JSONResponse(
        status_code=status_code,
        content={
            "type": "error",
            "error": {
                "type": error_type,
                "message": message,
            },
            "request_id": rquid_context.get(),
        },
    )
