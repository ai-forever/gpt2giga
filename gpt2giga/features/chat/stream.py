"""Streaming helpers for the chat feature."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator, Optional

from gigachat import GigaChat
from starlette.requests import Request

from gpt2giga.app.dependencies import get_logger_from_state
from gpt2giga.app.observability import (
    set_request_audit_model,
    set_request_audit_usage,
)
from gpt2giga.core.http.sse import format_chat_stream_chunk, format_chat_stream_done
from gpt2giga.core.logging.setup import rquid_context
from gpt2giga.features.chat.contracts import ChatProviderMapper
from gpt2giga.providers.gigachat.client import get_gigachat_client
from gpt2giga.providers.gigachat.streaming import (
    iter_chat_v2_stream_chunks,
    iter_chat_stream_chunks,
    iter_stream_with_disconnect,
    map_chat_stream_chunk,
    report_stream_failure,
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
        async for chunk in iter_stream_with_disconnect(
            request,
            stream_iter,
            logger=logger,
            rquid=rquid,
        ):
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

    except asyncio.CancelledError:
        raise

    except Exception as exc:
        failure = report_stream_failure(
            request,
            exc,
            logger=logger,
            rquid=rquid,
        )
        error_response = {
            "error": {
                "message": failure.message,
                "type": failure.error_type,
                "code": failure.code,
            }
        }
        yield format_chat_stream_chunk(error_response)
        yield format_chat_stream_done()
