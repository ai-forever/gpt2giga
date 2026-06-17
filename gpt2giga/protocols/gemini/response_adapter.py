"""Map normalized responses to Gemini GenerateContent payloads."""

from __future__ import annotations

import json
from typing import Any

from gpt2giga.core.context import RequestContext
from gpt2giga.protocols.normalized import (
    NormalizedChoice,
    NormalizedContentPart,
    NormalizedError,
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


def gemini_response_to_normalized(
    payload: dict[str, Any],
    *,
    requested_model: str | None = None,
) -> NormalizedResponse:
    """Convert a Gemini GenerateContent response to normalized form."""
    if isinstance(payload.get("error"), dict):
        error = payload["error"]
        return NormalizedResponse(
            id=_string_or_none(payload.get("responseId")),
            model=_string_or_none(payload.get("modelVersion")) or requested_model,
            provider="gemini",
            error=NormalizedError(
                type=str(error.get("status") or "error"),
                message=str(error.get("message") or ""),
                code=error.get("code"),
            ),
            metadata=_metadata_from_gemini(payload),
        )

    candidates = payload.get("candidates")
    choices = [
        _gemini_candidate_to_normalized(candidate, index=index)
        for index, candidate in enumerate(
            candidates if isinstance(candidates, list) else []
        )
        if isinstance(candidate, dict)
    ]
    return NormalizedResponse(
        id=_string_or_none(payload.get("responseId")),
        model=_string_or_none(payload.get("modelVersion")) or requested_model,
        provider="gemini",
        choices=choices,
        usage=_gemini_usage_to_normalized(payload.get("usageMetadata")),
        metadata=_metadata_from_gemini(payload),
    )


def _gemini_candidate_to_normalized(
    candidate: dict[str, Any],
    *,
    index: int,
) -> NormalizedChoice:
    candidate_index = candidate.get("index")
    if not isinstance(candidate_index, int):
        candidate_index = index
    return NormalizedChoice(
        index=candidate_index,
        message=_gemini_content_to_normalized_message(candidate.get("content")),
        finish_reason=_gemini_finish_reason_to_normalized(
            _string_or_none(candidate.get("finishReason"))
        ),
        raw_extensions={
            key: value
            for key, value in {
                "safetyRatings": candidate.get("safetyRatings"),
                "citationMetadata": candidate.get("citationMetadata"),
                "groundingMetadata": candidate.get("groundingMetadata"),
            }.items()
            if value is not None
        },
    )


def _gemini_content_to_normalized_message(value: Any) -> NormalizedMessage:
    if not isinstance(value, dict):
        return NormalizedMessage(role="assistant", content="")
    role = _gemini_role_to_normalized(_string_or_none(value.get("role")) or "model")
    text_parts: list[str] = []
    content_parts: list[NormalizedContentPart] = []
    tool_calls: list[NormalizedToolCall] = []
    parts = value.get("parts")
    if isinstance(parts, dict):
        parts = [parts]
    for part in parts if isinstance(parts, list) else []:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str):
            text_parts.append(text)
            content_parts.append(NormalizedContentPart(type="text", text=text))
            continue
        function_call = part.get("functionCall") or part.get("function_call")
        if isinstance(function_call, dict):
            tool_calls.append(_gemini_function_call_to_normalized(function_call))
            continue
        inline_data = part.get("inlineData") or part.get("inline_data")
        if isinstance(inline_data, dict):
            content_parts.append(
                NormalizedContentPart(
                    type="image_url",
                    data={"url": _inline_data_to_data_url(inline_data)},
                    mime_type=_string_or_none(inline_data.get("mimeType"))
                    or _string_or_none(inline_data.get("mime_type")),
                    raw_extensions={"inlineData": inline_data},
                )
            )
            continue
        file_data = part.get("fileData") or part.get("file_data")
        if isinstance(file_data, dict):
            content_parts.append(
                NormalizedContentPart(
                    type="file",
                    raw_extensions={"gemini_file_data": file_data},
                )
            )
    content: str | list[NormalizedContentPart]
    content = "\n".join(text_parts)
    if len(content_parts) != len(text_parts):
        content = content_parts
    return NormalizedMessage(role=role, content=content, tool_calls=tool_calls)


def _gemini_function_call_to_normalized(value: dict[str, Any]) -> NormalizedToolCall:
    return NormalizedToolCall(
        id=_string_or_none(value.get("id")),
        name=_string_or_none(value.get("name")),
        arguments=value.get("args", {}),
    )


def _gemini_usage_to_normalized(value: Any) -> NormalizedUsage | None:
    if not isinstance(value, dict):
        return None
    usage = NormalizedUsage(
        input_tokens=_int_or_none(value.get("promptTokenCount")),
        output_tokens=_int_or_none(value.get("candidatesTokenCount")),
        total_tokens=_int_or_none(value.get("totalTokenCount")),
    )
    if (
        usage.input_tokens is None
        and usage.output_tokens is None
        and usage.total_tokens is None
    ):
        return None
    return usage


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


def _gemini_role_to_normalized(role: str) -> str:
    normalized = role.strip().lower()
    if normalized == "model":
        return "assistant"
    if normalized == "function":
        return "tool"
    return normalized or "assistant"


def _gemini_finish_reason_to_normalized(value: str | None) -> str | None:
    if value is None:
        return None
    return {
        "MAX_TOKENS": "length",
        "SAFETY": "content_filter",
        "STOP": "stop",
    }.get(value.upper(), value.lower())


def _metadata_from_gemini(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("gpt2gigaMetadata")
    return dict(metadata) if isinstance(metadata, dict) else {}


def _inline_data_to_data_url(value: dict[str, Any]) -> str | None:
    data = value.get("data")
    if not isinstance(data, str):
        return None
    mime_type = (
        _string_or_none(value.get("mimeType"))
        or _string_or_none(value.get("mime_type"))
        or "application/octet-stream"
    )
    return f"data:{mime_type};base64,{data}"


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) else None
