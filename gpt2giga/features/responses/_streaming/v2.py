"""Responses streaming public entrypoint and v2 implementation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, MutableMapping
from typing import Any, Optional, cast
from gigachat.models import Chat, ChatV2
from starlette.requests import Request

from gpt2giga.app.dependencies import (
    get_logger_from_state,
    get_response_processor_from_state,
)
from gpt2giga.app.observability import (
    set_request_audit_model,
    set_request_audit_usage,
)
from gpt2giga.core.http.sse import format_responses_stream_event
from gpt2giga.core.logging.setup import rquid_context
from gpt2giga.features.responses._streaming.events import (
    ResponsesStreamEventSequencer,
)
from gpt2giga.features.responses._streaming.failures import (
    emit_stream_failure_event,
)
from gpt2giga.features.responses._streaming.state import ResponsesV2StreamState
from gpt2giga.features.responses._streaming.v1 import stream_responses_generator_v1
from gpt2giga.features.responses.store import get_response_store
from gpt2giga.providers.gigachat.client import get_gigachat_client
from gpt2giga.providers.gigachat.streaming import (
    GigaChatResponsesStreamProcessor,
    ResponsesFunctionCallUpdate,
    ResponsesTextUpdate,
    ResponsesToolUpdate,
    iter_responses_stream_chunks,
    iter_stream_with_disconnect,
)


async def stream_responses_generator(
    request: Request,
    chat_messages: ChatV2 | Chat | Any,
    response_id: str,
    giga_client: Any = None,
    request_data: Optional[dict[str, Any]] = None,
    response_store: MutableMapping[str, Any] | None = None,
    response_processor: Any = None,
    api_mode: str = "v2",
) -> AsyncGenerator[str, None]:
    """Stream Responses API events as SSE lines."""
    logger = None
    rquid = rquid_context.get()
    processor = response_processor or get_response_processor_from_state(
        request.app.state
    )
    stream_processor = cast(GigaChatResponsesStreamProcessor, processor)
    if request_data is not None:
        set_request_audit_model(request, request_data.get("model"))
    response_store = (
        response_store if response_store is not None else get_response_store(request)
    )

    if api_mode == "v1":
        async for line in stream_responses_generator_v1(
            request,
            chat_messages,
            response_id=response_id,
            giga_client=giga_client,
            request_data=request_data,
            response_processor=processor,
        ):
            yield line
        return

    typed_response_store = cast(dict[Any, Any], response_store)
    state = ResponsesV2StreamState(
        response_id=response_id,
        request_data=request_data,
        response_store=typed_response_store,
    )
    emitter = ResponsesStreamEventSequencer(format_responses_stream_event)

    try:
        if giga_client is None:
            giga_client = get_gigachat_client(request)
        logger = get_logger_from_state(request.app.state)

        yield emitter.emit(
            "response.created",
            {"response": state.build_current_response(processor, "in_progress")},
        )
        yield emitter.emit(
            "response.in_progress",
            {"response": state.build_current_response(processor, "in_progress")},
        )

        async for chunk in iter_stream_with_disconnect(
            request,
            iter_responses_stream_chunks(
                giga_client,
                chat_messages,
                response_processor=stream_processor,
                response_id=response_id,
            ),
            logger=logger,
            rquid=rquid,
        ):
            state.model = chunk.model or state.model
            if isinstance(chunk.model, str) and chunk.model:
                set_request_audit_model(request, chunk.model)
            state.created_at = chunk.created_at or state.created_at
            state.thread_id = chunk.thread_id or state.thread_id
            state.finish_reason = chunk.finish_reason or state.finish_reason
            if chunk.usage is not None:
                state.usage = chunk.usage
                set_request_audit_usage(request, state.usage)

            for update in chunk.updates:
                if isinstance(update, ResponsesTextUpdate):
                    for event in state.handle_text_update(update, emitter=emitter):
                        yield event
                    continue

                if isinstance(update, ResponsesFunctionCallUpdate):
                    for event in state.handle_function_call_update(
                        update,
                        emitter=emitter,
                    ):
                        yield event
                    continue

                if isinstance(update, ResponsesToolUpdate):
                    for event in await state.handle_tool_update(
                        update,
                        emitter=emitter,
                        giga_client=giga_client,
                    ):
                        yield event

        for event in state.finalize(processor, emitter=emitter):
            yield event

        response_status, _ = stream_processor._build_response_status(
            state.finish_reason
        )
        final_response = state.build_current_response(stream_processor, response_status)
        stream_processor.store_response_metadata(typed_response_store, final_response)
        if response_status == "incomplete":
            yield emitter.emit("response.incomplete", {"response": final_response})
        else:
            yield emitter.emit("response.completed", {"response": final_response})

    except asyncio.CancelledError:
        raise

    except Exception as exc:
        yield emit_stream_failure_event(
            request=request,
            exc=exc,
            emitter=emitter,
            logger=logger,
            rquid=rquid,
        )
