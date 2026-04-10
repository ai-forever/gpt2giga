"""Gemini Developer API streaming helpers."""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator, Optional

import gigachat
from fastapi import Request
from gigachat import GigaChat

from gpt2giga.api.gemini.response import (
    _is_structured_output_request,
    _map_finish_reason,
)
from gpt2giga.app.dependencies import get_logger_from_state
from gpt2giga.app.observability import (
    set_request_audit_error,
    set_request_audit_model,
    set_request_audit_usage,
)
from gpt2giga.core.logging.setup import rquid_context
from gpt2giga.providers.gigachat.tool_mapping import map_tool_name_from_gigachat


async def stream_gemini_generate_content(
    request: Request,
    model: str,
    chat_messages: Any,
    response_id: str,
    giga_client: GigaChat,
    request_data: Optional[dict[str, Any]] = None,
    *,
    api_mode: str = "v1",
    response_processor: Any = None,
) -> AsyncGenerator[str, None]:
    """Yield Gemini-compatible SSE chunks from a GigaChat stream."""
    logger = get_logger_from_state(request.app.state)
    rquid = rquid_context.get()
    structured_output = _is_structured_output_request(request_data)
    set_request_audit_model(request, model)

    try:
        stream_iter = (
            giga_client.astream_v2(chat_messages)
            if api_mode == "v2"
            else giga_client.astream(chat_messages)
        )
        async for chunk in stream_iter:
            if await request.is_disconnected():
                if logger:
                    logger.info(f"[{rquid}] Client disconnected during streaming")
                break

            giga_dict = (
                response_processor.normalize_chat_v2_stream_chunk(chunk)
                if api_mode == "v2" and response_processor is not None
                else chunk.model_dump()
            )
            choice = (giga_dict.get("choices") or [{}])[0]
            delta = choice.get("delta") or {}

            parts: list[dict[str, Any]] = []
            reasoning = delta.get("reasoning_content")
            if reasoning:
                parts.append({"text": reasoning, "thought": True})

            function_call = delta.get("function_call")
            if function_call:
                arguments = function_call.get("arguments", {})
                if structured_output:
                    if isinstance(arguments, dict):
                        parts.append(
                            {"text": json.dumps(arguments, ensure_ascii=False)}
                        )
                    elif arguments:
                        parts.append({"text": str(arguments)})
                else:
                    if isinstance(arguments, str):
                        try:
                            arguments = json.loads(arguments)
                        except json.JSONDecodeError:
                            arguments = {"value": arguments}
                    elif not isinstance(arguments, dict):
                        arguments = {}
                    parts.append(
                        {
                            "functionCall": {
                                "name": map_tool_name_from_gigachat(
                                    function_call.get("name", "")
                                ),
                                "args": arguments,
                            }
                        }
                    )

            content = delta.get("content")
            if content:
                parts.append({"text": content})

            payload: dict[str, Any] = {
                "candidates": [
                    {
                        "index": choice.get("index", 0),
                    }
                ],
                "modelVersion": model,
                "responseId": response_id,
            }

            candidate = payload["candidates"][0]
            if parts:
                candidate["content"] = {"role": "model", "parts": parts}

            finish_reason = choice.get("finish_reason")
            if finish_reason is not None:
                candidate["finishReason"] = _map_finish_reason(finish_reason)

            usage = giga_dict.get("usage")
            if usage:
                set_request_audit_usage(request, usage)
                payload["usageMetadata"] = {
                    "promptTokenCount": usage.get("prompt_tokens", 0),
                    "candidatesTokenCount": usage.get("completion_tokens", 0),
                    "totalTokenCount": usage.get("total_tokens", 0),
                }

            if parts or finish_reason is not None or usage:
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    except gigachat.exceptions.GigaChatException as exc:
        set_request_audit_error(request, type(exc).__name__)
        if logger:
            logger.error(
                f"[{rquid}] GigaChat streaming error: {type(exc).__name__}: {exc}"
            )
        payload = {
            "error": {
                "code": getattr(exc, "status_code", 500) or 500,
                "message": str(exc),
                "status": "INTERNAL",
            }
        }
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    except Exception as exc:
        set_request_audit_error(request, type(exc).__name__)
        if logger:
            logger.error(f"[{rquid}] Unexpected Gemini streaming error: {exc}")
        payload = {
            "error": {
                "code": 500,
                "message": "Stream interrupted",
                "status": "INTERNAL",
            }
        }
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
