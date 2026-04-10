"""Streaming helpers for the chat feature."""

from __future__ import annotations

import asyncio
import traceback
from typing import Any, AsyncGenerator, Optional

from gigachat import GigaChat
from starlette.requests import Request

from gpt2giga.app.dependencies import get_logger_from_state
from gpt2giga.app.observability import (
    set_request_audit_error,
    set_request_audit_model,
    set_request_audit_usage,
)
from gpt2giga.core.logging.setup import rquid_context
from gpt2giga.features.chat.contracts import ChatProviderMapper
from gpt2giga.providers.gigachat.client import get_gigachat_client
from gpt2giga.providers.gigachat.streaming import (
    GigaChatStreamError,
    iter_chat_v2_stream_chunks,
    iter_chat_stream_chunks,
    map_chat_stream_chunk,
)


async def stream_chat_completion_generator(
    request: Request,
    model: str,
    chat_messages: Any,
    response_id: str,
    giga_client: Optional[GigaChat] = None,
    *,
    mapper: ChatProviderMapper,
    api_mode: str = "v1",
) -> AsyncGenerator[str, None]:
    """Stream chat-completions chunks as SSE lines."""
    from gpt2giga.api.openai.streaming import (
        format_chat_stream_chunk,
        format_chat_stream_done,
    )

    logger = None
    rquid = rquid_context.get()
    set_request_audit_model(request, model)

    try:
        if giga_client is None:
            giga_client = get_gigachat_client(request)
        logger = get_logger_from_state(request.app.state)

        stream_iter = (
            iter_chat_v2_stream_chunks(giga_client, chat_messages)
            if api_mode == "v2"
            else iter_chat_stream_chunks(giga_client, chat_messages)
        )
        async for chunk in stream_iter:
            if await request.is_disconnected():
                if logger:
                    logger.info(f"[{rquid}] Client disconnected during streaming")
                break
            processed = map_chat_stream_chunk(
                chunk,
                mapper=mapper,
                model=model,
                response_id=response_id,
            )
            chunk_model = processed.get("model")
            if isinstance(chunk_model, str) and chunk_model:
                set_request_audit_model(request, chunk_model)
            set_request_audit_usage(request, processed.get("usage"))
            yield format_chat_stream_chunk(processed)

        yield format_chat_stream_done()

    except GigaChatStreamError as exc:
        set_request_audit_error(request, exc.error_type)
        error_type = exc.error_type
        error_message = exc.message
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
        yield format_chat_stream_chunk(error_response)
        yield format_chat_stream_done()

    except asyncio.CancelledError:
        raise

    except Exception as exc:
        error_type = type(exc).__name__
        set_request_audit_error(request, error_type)
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
        yield format_chat_stream_chunk(error_response)
        yield format_chat_stream_done()
