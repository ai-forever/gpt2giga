"""Map normalized responses to OpenAI Chat Completions payloads."""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

from gpt2giga.core.context import RequestContext
from gpt2giga.protocols.normalized import (
    NormalizedChoice,
    NormalizedMessage,
    NormalizedResponse,
    NormalizedToolCall,
    NormalizedUsage,
)


def normalized_chat_response_to_openai(
    response: NormalizedResponse,
    *,
    requested_model: str,
    context: RequestContext | None = None,
) -> dict[str, Any]:
    """Convert a normalized non-streaming chat response to OpenAI shape."""
    if response.error is not None:
        return {
            "error": {
                "message": response.error.message,
                "type": response.error.type,
                "param": response.error.param,
                "code": response.error.code,
            }
        }

    response_id = response.id or (context.request_id if context is not None else None)
    response_id = response_id or "normalized"
    result: dict[str, Any] = {
        "id": f"chatcmpl-{response_id}",
        "object": "chat.completion",
        "created": _created_timestamp(response.created_at),
        "model": requested_model,
        "choices": [_choice_to_openai(choice) for choice in response.choices],
        "usage": _usage_to_openai(response.usage),
        "system_fingerprint": f"fp_{response_id}",
    }
    metadata = _metadata_to_openai(response)
    if metadata:
        result["metadata"] = metadata
    return result


def _choice_to_openai(choice: NormalizedChoice) -> dict[str, Any]:
    return {
        "index": choice.index,
        "message": _message_to_openai(choice.message),
        "finish_reason": choice.finish_reason,
        "logprobs": None,
    }


def _message_to_openai(message: NormalizedMessage | None) -> dict[str, Any]:
    if message is None:
        return {"role": "assistant", "content": "", "refusal": None}

    payload: dict[str, Any] = {
        "role": message.role,
        "content": message.content,
        "refusal": None,
    }
    if message.name is not None:
        payload["name"] = message.name
    if message.tool_call_id is not None:
        payload["tool_call_id"] = message.tool_call_id
    if message.tool_calls:
        payload["tool_calls"] = [
            _tool_call_to_openai(index, tool_call)
            for index, tool_call in enumerate(message.tool_calls)
        ]
        payload["content"] = message.content
    return payload


def _tool_call_to_openai(
    index: int,
    tool_call: NormalizedToolCall,
) -> dict[str, Any]:
    call_id = tool_call.id or f"call_{index}"
    return {
        "index": index,
        "id": call_id,
        "type": tool_call.type,
        "function": {
            "name": tool_call.name or "",
            "arguments": _tool_arguments_to_json(tool_call.arguments),
        },
    }


def _tool_arguments_to_json(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value or {}, ensure_ascii=False)


def _usage_to_openai(usage: NormalizedUsage | None) -> dict[str, Any] | None:
    if usage is None:
        return None
    return {
        "prompt_tokens": usage.input_tokens,
        "completion_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "prompt_tokens_details": {
            "cached_tokens": usage.raw_extensions.get("precached_prompt_tokens", 0)
        },
        "completion_tokens_details": {"reasoning_tokens": 0},
    }


def _metadata_to_openai(response: NormalizedResponse) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for key, value in response.metadata.items():
        if isinstance(key, str) and isinstance(value, str):
            metadata[key] = value

    gigachat_metadata = response.provider_metadata.get("gigachat")
    if isinstance(gigachat_metadata, dict):
        for key, value in gigachat_metadata.items():
            if isinstance(key, str) and isinstance(value, str):
                metadata[key] = value
    return metadata


def _created_timestamp(value: datetime) -> int:
    return int(value.timestamp() if isinstance(value, datetime) else time.time())
