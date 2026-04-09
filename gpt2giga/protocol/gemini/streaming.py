"""Gemini Developer API streaming helpers."""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator, Dict, Optional

import gigachat
from fastapi import Request
from gigachat import GigaChat

from gpt2giga.app.dependencies import get_logger_from_state
from gpt2giga.common.tools import map_tool_name_from_gigachat
from gpt2giga.core.logging.setup import rquid_context
from gpt2giga.protocol.gemini.response import (
    _is_structured_output_request,
    _map_finish_reason,
)


async def stream_gemini_generate_content(
    request: Request,
    model: str,
    chat_messages: Dict[str, Any],
    response_id: str,
    giga_client: GigaChat,
    request_data: Optional[dict[str, Any]] = None,
) -> AsyncGenerator[str, None]:
    """Yield Gemini-compatible SSE chunks from a GigaChat stream."""
    logger = get_logger_from_state(request.app.state)
    rquid = rquid_context.get()
    structured_output = _is_structured_output_request(request_data)

    try:
        async for chunk in giga_client.astream(chat_messages):
            if await request.is_disconnected():
                if logger:
                    logger.info(f"[{rquid}] Client disconnected during streaming")
                break

            giga_dict = chunk.model_dump()
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
                payload["usageMetadata"] = {
                    "promptTokenCount": usage.get("prompt_tokens", 0),
                    "candidatesTokenCount": usage.get("completion_tokens", 0),
                    "totalTokenCount": usage.get("total_tokens", 0),
                }

            if parts or finish_reason is not None or usage:
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    except gigachat.exceptions.GigaChatException as exc:
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
