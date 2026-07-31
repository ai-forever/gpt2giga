"""Map normalized responses to Anthropic Messages payloads."""

from __future__ import annotations

import json
import uuid
from typing import Any

from gpt2giga.common.reasoning import (
    extract_reasoning_from_content,
    merge_reasoning_text,
)
from gpt2giga.common.sources import render_text_with_sources
from gpt2giga.common.tools import map_tool_name_from_gigachat
from gpt2giga.core.context import RequestContext
from gpt2giga.protocols.normalized import (
    NormalizedChoice,
    NormalizedContentPart,
    NormalizedMessage,
    NormalizedResponse,
    NormalizedToolCall,
    NormalizedUsage,
)


def normalized_chat_response_to_anthropic(
    response: NormalizedResponse,
    *,
    requested_model: str,
    context: RequestContext | None = None,
    structured_output: bool = False,
) -> dict[str, Any]:
    """Convert one normalized response to Anthropic Messages shape."""
    if response.error is not None:
        return {
            "type": "error",
            "error": {
                "type": response.error.type,
                "message": response.error.message,
                **(
                    {"code": response.error.code}
                    if response.error.code is not None
                    else {}
                ),
            },
            "request_id": _response_id(response, context),
        }

    choice = response.choices[0] if response.choices else NormalizedChoice()
    message = choice.message or NormalizedMessage(role="assistant", content="")
    content = _message_content(message, structured_output=structured_output)
    stop_reason = _stop_reason(choice, has_tool_calls=bool(message.tool_calls))
    if structured_output and message.tool_calls:
        stop_reason = "end_turn"
    response_id = _response_id(response, context)
    return {
        "id": response_id if response_id.startswith("msg_") else f"msg_{response_id}",
        "type": "message",
        "role": "assistant",
        "content": content,
        "model": requested_model,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": _usage_to_anthropic(response.usage),
    }


def _message_content(
    message: NormalizedMessage,
    *,
    structured_output: bool,
) -> list[dict[str, Any]]:
    if structured_output and message.tool_calls:
        return [
            {
                "type": "text",
                "text": _tool_arguments_to_text(message.tool_calls[0].arguments),
            }
        ]

    content: list[dict[str, Any]] = []
    text, reasoning = _normalized_text_and_reasoning(message)
    if reasoning:
        content.append({"type": "thinking", "thinking": reasoning})
    if text:
        content.append({"type": "text", "text": text})
    content.extend(_tool_call_to_anthropic(call) for call in message.tool_calls)
    return content or [{"type": "text", "text": ""}]


def _normalized_text_and_reasoning(
    message: NormalizedMessage,
) -> tuple[str, str | None]:
    text = _content_text(message.content)
    parsed = extract_reasoning_from_content(text)
    reasoning = merge_reasoning_text(
        _string_or_none(message.raw_extensions.get("reasoning_content")),
        parsed.reasoning_content,
    )
    inline_data = message.raw_extensions.get("inline_data")
    rendered = render_text_with_sources(
        parsed.content,
        inline_data if isinstance(inline_data, dict) else {},
    )
    return rendered, reasoning


def _content_text(value: str | list[NormalizedContentPart] | None) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    return "\n".join(part.text or "" for part in value if part.type == "text")


def _tool_call_to_anthropic(call: NormalizedToolCall) -> dict[str, Any]:
    return {
        "type": "tool_use",
        "id": call.id or f"toolu_{uuid.uuid4().hex[:24]}",
        "name": map_tool_name_from_gigachat(call.name or ""),
        "input": _tool_arguments(call.arguments),
    }


def _tool_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _tool_arguments_to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value or {}, ensure_ascii=False)


def _stop_reason(
    choice: NormalizedChoice,
    *,
    has_tool_calls: bool,
) -> str:
    if has_tool_calls:
        return "tool_use"
    value = choice.stop_reason or choice.finish_reason or "stop"
    return {
        "stop": "end_turn",
        "length": "max_tokens",
        "max_tokens": "max_tokens",
        "tool_calls": "tool_use",
        "content_filter": "end_turn",
    }.get(value, "end_turn")


def _usage_to_anthropic(usage: NormalizedUsage | None) -> dict[str, int]:
    return {
        "input_tokens": int(usage.input_tokens or 0) if usage else 0,
        "output_tokens": int(usage.output_tokens or 0) if usage else 0,
    }


def _response_id(
    response: NormalizedResponse,
    context: RequestContext | None,
) -> str:
    return response.id or (context.request_id if context is not None else None) or "-"


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None
