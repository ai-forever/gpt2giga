"""Anthropic response and error helpers."""

import json
import uuid
from typing import Any, Dict, List, Optional

from fastapi.responses import JSONResponse

from gpt2giga.common.debug_logging import log_debug_payload
from gpt2giga.common.reasoning import (
    extract_reasoning_from_content,
    merge_reasoning_text,
)
from gpt2giga.common.sources import render_text_with_sources
from gpt2giga.common.tools import map_tool_name_from_gigachat
from gpt2giga.logger import rquid_context


def _map_stop_reason(finish_reason: Optional[str]) -> str:
    """Map GigaChat finish_reason to Anthropic stop_reason."""
    mapping = {
        "stop": "end_turn",
        "length": "max_tokens",
        "function_call": "tool_use",
        "content_filter": "end_turn",
    }
    return mapping.get(finish_reason or "stop", "end_turn")


def _tool_call_arguments_to_text(tool_call: Dict) -> str:
    """Extract function-call arguments as JSON text."""
    function = tool_call.get("function", {})
    arguments = function.get("arguments", {})
    if isinstance(arguments, str):
        return arguments
    return json.dumps(arguments, ensure_ascii=False)


def _build_anthropic_response(
    giga_dict: Dict,
    model: str,
    response_id: str,
    *,
    is_structured_output: bool = False,
    logger: Any = None,
    mode: str = "DEV",
) -> Dict:
    """Build Anthropic Messages API response from a GigaChat response."""
    choice = giga_dict["choices"][0]
    message = choice.get("message", {})
    finish_reason = choice.get("finish_reason", "stop")
    usage = giga_dict.get("usage", {})

    content_blocks: List[Dict] = []
    text_content = message.get("content", "") or ""
    parsed_content = extract_reasoning_from_content(text_content)
    reasoning = merge_reasoning_text(
        message.get("reasoning_content"), parsed_content.reasoning_content
    )
    if reasoning:
        content_blocks.append({"type": "thinking", "thinking": reasoning})

    text_content = render_text_with_sources(
        parsed_content.content,
        message.get("inline_data") or {},
    )

    tool_calls = list(message.get("tool_calls") or [])
    if message.get("function_call"):
        tool_calls.append({"function": message["function_call"]})

    if is_structured_output and tool_calls:
        content_blocks.append(
            {
                "type": "text",
                "text": _tool_call_arguments_to_text(tool_calls[0]),
            }
        )
        stop_reason = "end_turn"
    elif tool_calls:
        if text_content:
            content_blocks.append({"type": "text", "text": text_content})
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
        if text_content:
            content_blocks.append({"type": "text", "text": text_content})
        if not content_blocks:
            content_blocks.append({"type": "text", "text": ""})
        stop_reason = _map_stop_reason(finish_reason)

    result = {
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
    log_debug_payload(
        logger,
        mode,
        event="anthropic_message_response",
        message="Processed Anthropic message response",
        payload_key="response",
        payload=result,
        response_id=result["id"],
        content_block_count=len(content_blocks),
    )
    return result


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
