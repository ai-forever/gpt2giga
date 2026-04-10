"""Gemini Developer API response helpers."""

from __future__ import annotations

import json
from functools import wraps
from typing import Any, Optional

import gigachat
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import JSONResponse

from gpt2giga.api.gemini.request import (
    GeminiAPIError,
    model_resource_name,
    normalize_model_name,
)
from gpt2giga.app.observability import set_request_audit_error
from gpt2giga.core.logging.setup import sanitize_for_utf8
from gpt2giga.providers.gigachat.tool_mapping import map_tool_name_from_gigachat

_GIGACHAT_ERROR_STATUS = {
    gigachat.exceptions.BadRequestError: "INVALID_ARGUMENT",
    gigachat.exceptions.AuthenticationError: "UNAUTHENTICATED",
    gigachat.exceptions.ForbiddenError: "PERMISSION_DENIED",
    gigachat.exceptions.NotFoundError: "NOT_FOUND",
    gigachat.exceptions.RequestEntityTooLargeError: "INVALID_ARGUMENT",
    gigachat.exceptions.RateLimitError: "RESOURCE_EXHAUSTED",
    gigachat.exceptions.UnprocessableEntityError: "INVALID_ARGUMENT",
    gigachat.exceptions.ServerError: "INTERNAL",
}


def gemini_error_response(
    *,
    status_code: int,
    status: str,
    message: str,
    details: Optional[list[dict[str, Any]]] = None,
) -> JSONResponse:
    """Build a Gemini-style error response."""
    error: dict[str, Any] = {
        "code": status_code,
        "message": sanitize_for_utf8(message),
        "status": status,
    }
    if details:
        error["details"] = sanitize_for_utf8(details)
    return JSONResponse(status_code=status_code, content={"error": error})


def gemini_exceptions_handler(func):
    """Return Gemini-style JSON errors for route exceptions."""

    @wraps(func)
    async def wrapper(*args, **kwargs):
        request = _find_request_arg(args, kwargs)
        try:
            return await func(*args, **kwargs)
        except GeminiAPIError as exc:
            _annotate_request_error(request, type(exc).__name__)
            return gemini_error_response(
                status_code=exc.status_code,
                status=exc.status,
                message=exc.message,
                details=exc.details,
            )
        except HTTPException as exc:
            _annotate_request_error(request, type(exc).__name__)
            message = exc.detail if isinstance(exc.detail, str) else "Request failed"
            status = "INVALID_ARGUMENT" if 400 <= exc.status_code < 500 else "INTERNAL"
            return gemini_error_response(
                status_code=exc.status_code,
                status=status,
                message=message,
            )
        except gigachat.exceptions.GigaChatException as exc:
            _annotate_request_error(request, type(exc).__name__)
            status = "INTERNAL"
            for error_class, mapped_status in _GIGACHAT_ERROR_STATUS.items():
                if isinstance(exc, error_class):
                    status = mapped_status
                    break
            status_code = getattr(exc, "status_code", None)
            if not isinstance(status_code, int):
                status_code = 500 if status == "INTERNAL" else 400
            return gemini_error_response(
                status_code=status_code,
                status=status,
                message=str(exc),
            )
        except Exception as exc:
            _annotate_request_error(request, type(exc).__name__)
            return gemini_error_response(
                status_code=500,
                status="INTERNAL",
                message=str(exc),
            )

    return wrapper


def _find_request_arg(args, kwargs) -> Request | None:
    for value in kwargs.values():
        if isinstance(value, Request):
            return value
    for value in args:
        if isinstance(value, Request):
            return value
    return None


def _annotate_request_error(request: Request | None, error_type: str) -> None:
    if request is not None:
        set_request_audit_error(request, error_type)


def _is_structured_output_request(request_data: Optional[dict[str, Any]]) -> bool:
    """Return true when the request asked for JSON-structured output."""
    if not isinstance(request_data, dict):
        return False
    generation_config = request_data.get("generationConfig")
    if not isinstance(generation_config, dict):
        return False
    return (
        generation_config.get("responseJsonSchema") is not None
        or generation_config.get("responseSchema") is not None
    )


def _map_finish_reason(finish_reason: Optional[str]) -> str:
    """Map GigaChat finish reasons to Gemini finish reasons."""
    mapping = {
        "stop": "STOP",
        "length": "MAX_TOKENS",
        "content_filter": "SAFETY",
        "function_call": "STOP",
    }
    return mapping.get(finish_reason or "stop", "STOP")


def _coerce_function_args(arguments: Any) -> Any:
    """Normalize function call arguments for Gemini wire format."""
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return {"value": arguments}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    return {}


def build_generate_content_response(
    giga_dict: dict[str, Any],
    model: str,
    response_id: str,
    request_data: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build a Gemini GenerateContent response from a GigaChat response."""
    choice = (giga_dict.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    structured_output = _is_structured_output_request(request_data)

    parts: list[dict[str, Any]] = []
    reasoning = message.get("reasoning_content")
    if reasoning:
        parts.append({"text": reasoning, "thought": True})

    text_content = message.get("content", "") or ""
    if text_content:
        parts.append({"text": text_content})

    function_calls = list(message.get("tool_calls") or [])
    if message.get("function_call"):
        function_calls.append({"function": message["function_call"]})

    if function_calls:
        for tool_call in function_calls:
            function = tool_call.get("function") or {}
            args = _coerce_function_args(function.get("arguments"))
            if structured_output:
                parts.append({"text": json.dumps(args, ensure_ascii=False)})
            else:
                parts.append(
                    {
                        "functionCall": {
                            "name": map_tool_name_from_gigachat(
                                function.get("name", "")
                            ),
                            "args": args,
                        }
                    }
                )

    if not parts:
        parts.append({"text": ""})

    usage = giga_dict.get("usage") or {}
    return {
        "candidates": [
            {
                "content": {"role": "model", "parts": parts},
                "finishReason": _map_finish_reason(choice.get("finish_reason")),
                "index": choice.get("index", 0),
            }
        ],
        "usageMetadata": {
            "promptTokenCount": usage.get("prompt_tokens", 0),
            "candidatesTokenCount": usage.get("completion_tokens", 0),
            "totalTokenCount": usage.get("total_tokens", 0),
        },
        "modelVersion": normalize_model_name(model),
        "responseId": response_id,
    }


def build_batch_embed_contents_response(result: Any) -> dict[str, Any]:
    """Translate a GigaChat embeddings result to Gemini batchEmbedContents."""
    payload = result if isinstance(result, dict) else result.model_dump()
    embeddings = payload.get("data") or []
    return {
        "embeddings": [
            {"values": item.get("embedding", [])}
            for item in embeddings
            if isinstance(item, dict)
        ]
    }


def build_single_embed_content_response(result: Any) -> dict[str, Any]:
    """Translate a GigaChat embeddings result to Gemini embedContent."""
    payload = build_batch_embed_contents_response(result)
    first_embedding = payload.get("embeddings") or [{}]
    return {"embedding": first_embedding[0]}


def build_gemini_model(
    model_id: str,
    *,
    supported_generation_methods: list[str],
    input_token_limit: int,
    output_token_limit: int,
    description: str,
    thinking: bool = False,
) -> dict[str, Any]:
    """Build a stable Gemini model descriptor."""
    payload = {
        "name": model_resource_name(model_id),
        "baseModelId": model_id,
        "version": "gpt2giga",
        "displayName": model_id,
        "description": description,
        "inputTokenLimit": input_token_limit,
        "outputTokenLimit": output_token_limit,
        "supportedGenerationMethods": supported_generation_methods,
        "thinking": thinking,
    }
    if "generateContent" in supported_generation_methods:
        payload.update({"temperature": 1.0, "topP": 1.0, "topK": 64})
    return payload
