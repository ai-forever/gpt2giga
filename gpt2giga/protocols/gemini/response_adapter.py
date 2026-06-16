"""Map normalized responses to Gemini GenerateContent payloads."""

from __future__ import annotations

import json
from typing import Any

from gpt2giga.core.context import RequestContext
from gpt2giga.protocols.normalized import (
    NormalizedChoice,
    NormalizedContentPart,
    NormalizedMessage,
    NormalizedResponse,
    NormalizedToolCall,
    NormalizedUsage,
)


def normalized_chat_response_to_gemini(
    response: NormalizedResponse,
    *,
    requested_model: str,
    context: RequestContext | None = None,
) -> dict[str, Any]:
    """Convert a normalized non-streaming chat response to Gemini shape."""
    if response.error is not None:
        return {
            "error": {
                "code": response.error.code or 500,
                "message": response.error.message,
                "status": response.error.type,
            }
        }

    response_id = response.id or (context.request_id if context is not None else None)
    result: dict[str, Any] = {
        "candidates": [
            _choice_to_gemini(choice)
            for choice in response.choices
            if choice.message is not None
        ],
        "modelVersion": response.model or requested_model,
        "responseId": response_id or "normalized",
    }
    usage = _usage_to_gemini(response.usage)
    if usage:
        result["usageMetadata"] = usage
    metadata = _safe_metadata(response)
    if metadata:
        result["gpt2gigaMetadata"] = metadata
    return result


def _choice_to_gemini(choice: NormalizedChoice) -> dict[str, Any]:
    payload = {
        "index": choice.index,
        "content": _message_to_gemini_content(choice.message),
        "finishReason": _finish_reason_to_gemini(choice.finish_reason),
        "safetyRatings": choice.raw_extensions.get("safetyRatings", []),
    }
    return {key: value for key, value in payload.items() if value is not None}


def _message_to_gemini_content(message: NormalizedMessage | None) -> dict[str, Any]:
    if message is None:
        return {"role": "model", "parts": [{"text": ""}]}
    parts = _content_to_gemini_parts(message.content)
    parts.extend(_tool_calls_to_gemini_parts(message.tool_calls))
    if not parts:
        parts = [{"text": ""}]
    return {
        "role": _role_to_gemini(message.role),
        "parts": parts,
    }


def _content_to_gemini_parts(
    content: str | list[NormalizedContentPart] | None,
) -> list[dict[str, Any]]:
    if content is None:
        return []
    if isinstance(content, str):
        return [{"text": content}]
    return [_content_part_to_gemini(part) for part in content]


def _content_part_to_gemini(part: NormalizedContentPart) -> dict[str, Any]:
    if part.type == "text":
        return {"text": part.text or ""}
    if part.type == "image_url":
        url = part.data.get("url") if isinstance(part.data, dict) else None
        inline_data = _data_url_to_inline_data(url)
        if inline_data:
            return {"inlineData": inline_data}
    if part.type == "file":
        file_data = part.raw_extensions.get("gemini_file_data")
        if isinstance(file_data, dict):
            return {"fileData": file_data}
    return {"text": part.text or ""}


def _tool_calls_to_gemini_parts(
    tool_calls: list[NormalizedToolCall],
) -> list[dict[str, Any]]:
    return [
        {
            "functionCall": _compact_dict(
                {
                    "id": tool_call.id,
                    "name": tool_call.name or "",
                    "args": _tool_arguments(tool_call.arguments),
                }
            )
        }
        for tool_call in tool_calls
    ]


def _tool_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {"arguments": value}
        return parsed if isinstance(parsed, dict) else {"arguments": parsed}
    return {} if value is None else {"arguments": value}


def _compact_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _role_to_gemini(role: str) -> str:
    if role == "assistant":
        return "model"
    if role == "tool":
        return "function"
    if role == "system":
        return "user"
    return role


def _finish_reason_to_gemini(value: str | None) -> str | None:
    if value is None:
        return None
    return {
        "length": "MAX_TOKENS",
        "stop": "STOP",
        "tool_calls": "STOP",
        "content_filter": "SAFETY",
    }.get(value, str(value).upper())


def _usage_to_gemini(usage: NormalizedUsage | None) -> dict[str, Any]:
    if usage is None:
        return {}
    return {
        key: value
        for key, value in {
            "promptTokenCount": usage.input_tokens,
            "candidatesTokenCount": usage.output_tokens,
            "totalTokenCount": usage.total_tokens,
        }.items()
        if value is not None
    }


def _safe_metadata(response: NormalizedResponse) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for source in (response.metadata, response.provider_metadata.get("gigachat", {})):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if isinstance(key, str) and isinstance(value, str):
                metadata[key] = value
    return metadata


def _data_url_to_inline_data(url: Any) -> dict[str, str] | None:
    if not isinstance(url, str) or not url.startswith("data:"):
        return None
    header, separator, data = url.partition(",")
    if separator != ",":
        return None
    mime_type = header.removeprefix("data:").split(";", maxsplit=1)[0]
    if not mime_type:
        return None
    return {"mimeType": mime_type, "data": data}
