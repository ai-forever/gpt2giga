"""Streaming helpers for the chat feature."""

from __future__ import annotations

import asyncio
import json
import traceback
from typing import Any, AsyncGenerator, Optional

import gigachat
from gigachat import GigaChat
from starlette.requests import Request

from gpt2giga.core.logging.setup import rquid_context
from gpt2giga.features.chat.contracts import ChatProviderMapper
from gpt2giga.providers.gigachat.client import get_gigachat_client


async def stream_chat_completion_generator(
    request: Request,
    model: str,
    chat_messages: Any,
    response_id: str,
    giga_client: Optional[GigaChat] = None,
    *,
    mapper: ChatProviderMapper,
) -> AsyncGenerator[str, None]:
    """Stream chat-completions chunks as SSE lines."""
    logger = None
    rquid = rquid_context.get()

    try:
        if giga_client is None:
            giga_client = get_gigachat_client(request)
        logger = getattr(request.app.state, "logger", None)

        async for chunk in giga_client.astream(chat_messages):
            if await request.is_disconnected():
                if logger:
                    logger.info(f"[{rquid}] Client disconnected during streaming")
                break
            processed = mapper.process_stream_chunk(chunk, model, response_id)
            yield f"data: {json.dumps(processed)}\n\n"

        yield "data: [DONE]\n\n"

    except gigachat.exceptions.GigaChatException as exc:
        error_type = type(exc).__name__
        error_message = str(exc)
        if logger:
            logger.error(
                f"[{rquid}] GigaChat streaming error: {error_type}: {error_message}"
            )
        error_response = {
            "error": {
                "message": error_message,
                "type": error_type,
                "code": "stream_error",
            }
        }
        yield f"data: {json.dumps(error_response)}\n\n"
        yield "data: [DONE]\n\n"

    except asyncio.CancelledError:
        raise

    except Exception as exc:
        error_type = type(exc).__name__
        tb = traceback.format_exc()
        if logger:
            logger.error(
                f"[{rquid}] Unexpected streaming error: {error_type}: {exc}\n{tb}"
            )
        error_response = {
            "error": {
                "message": "Stream interrupted",
                "type": error_type,
                "code": "internal_error",
            }
        }
        yield f"data: {json.dumps(error_response)}\n\n"
        yield "data: [DONE]\n\n"
