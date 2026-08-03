"""Map normalized responses to OpenAI Chat Completions payloads."""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

from gpt2giga.core.context import RequestContext
from gpt2giga.protocol.response.processor import ResponseProcessor
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


def normalized_chat_response_to_responses(
    response: NormalizedResponse,
    *,
    request_payload: dict[str, Any],
    requested_model: str,
    response_id: str,
) -> dict[str, Any]:
    """Convert one normalized result to the admitted Responses object shape."""
    if response.error is not None:
        return {
            "error": {
                "message": response.error.message,
                "type": response.error.type,
                "param": response.error.param,
                "code": response.error.code,
            }
        }

    status, incomplete_details = _responses_status(response)
    output: list[dict[str, Any]] = []
    for choice_index, choice in enumerate(response.choices):
        message = choice.message
        if message is None:
            continue
        hosted_items = ResponseProcessor.create_hosted_tool_response_items(
            message.raw_extensions,
            response_id,
            request_data=request_payload,
        )
        output.extend(hosted_items)
        text = _responses_message_text(message)
        if text or not hosted_items:
            output.append(
                {
                    "type": "message",
                    "id": f"msg_{response_id}_{choice_index}",
                    "status": "completed",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": text or "",
                            "annotations": [],
                            "logprobs": [],
                        }
                    ],
                }
            )
        output.extend(_responses_tool_calls(message, choice_index=choice_index))

    metadata = dict(request_payload.get("metadata") or {})
    metadata.update(_metadata_to_openai(response))
    response_text = request_payload.get("text")
    if not isinstance(response_text, dict):
        response_text = {"format": {"type": "text"}}
    return {
        "id": f"resp_{response_id}",
        "object": "response",
        "created_at": _created_timestamp(response.created_at),
        "status": status,
        "error": None,
        "incomplete_details": incomplete_details,
        "instructions": request_payload.get("instructions"),
        "max_output_tokens": request_payload.get("max_output_tokens"),
        "model": requested_model,
        "output": output,
        "parallel_tool_calls": True,
        "previous_response_id": None,
        "reasoning": {"effort": None, "summary": None},
        "store": True,
        "temperature": request_payload.get("temperature", 1),
        "text": response_text,
        "tool_choice": request_payload.get("tool_choice", "auto"),
        "tools": request_payload.get("tools", []),
        "top_p": request_payload.get("top_p", 1),
        "truncation": "disabled",
        "usage": _responses_usage(response.usage),
        "user": None,
        "metadata": metadata,
    }


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


def _responses_tool_arguments_to_json(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value or {}, ensure_ascii=False, separators=(",", ":"))


def _responses_tool_calls(
    message: NormalizedMessage,
    *,
    choice_index: int,
) -> list[dict[str, Any]]:
    items = []
    for call_index, tool_call in enumerate(message.tool_calls):
        call_id = tool_call.id or f"call_{choice_index}_{call_index}"
        items.append(
            {
                "id": f"fc_{call_id}",
                "type": "function_call",
                "status": "completed",
                "call_id": call_id,
                "name": tool_call.name or "",
                "arguments": _responses_tool_arguments_to_json(tool_call.arguments),
            }
        )
    return items


def _responses_message_text(message: NormalizedMessage) -> str | None:
    if isinstance(message.content, str):
        return message.content
    if not isinstance(message.content, list):
        return None
    parts = [
        part.text
        for part in message.content
        if part.type == "text" and part.text is not None
    ]
    return "".join(parts) if parts else None


def _responses_status(
    response: NormalizedResponse,
) -> tuple[str, dict[str, str] | None]:
    reasons = {
        choice.stop_reason or choice.finish_reason for choice in response.choices
    }
    if reasons & {"max_tokens", "length"}:
        return "incomplete", {"reason": "max_output_tokens"}
    if "content_filter" in reasons:
        return "incomplete", {"reason": "content_filter"}
    return "completed", None


def _responses_usage(usage: NormalizedUsage | None) -> dict[str, int] | None:
    if usage is None:
        return None
    values = {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
    }
    return {key: value for key, value in values.items() if value is not None}


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
