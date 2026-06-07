"""OpenAI chat completions endpoint."""

from copy import deepcopy
from types import SimpleNamespace

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from gpt2giga.app_state import get_gigachat_client, get_model_concurrency_limiter
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.gigachat_options import (
    extract_gigachat_request_options,
    gigachat_request_options,
)
from gpt2giga.common.model_concurrency import resolve_gigachat_model
from gpt2giga.common.request_json import read_request_json
from gpt2giga.common.streaming import (
    stream_chat_completion_generator,
    stream_chat_completion_v2_generator,
)
from gpt2giga.core.context import get_request_context
from gpt2giga.logger import rquid_context
from gpt2giga.openapi_specs.openai import chat_completions_openapi_extra
from gpt2giga.protocol.response import adapt_v2_completion_to_v1_shape
from gpt2giga.protocols.openai import (
    normalized_chat_response_to_openai,
    normalized_stream_done_sse,
    normalized_stream_event_to_openai_sse,
)
from gpt2giga.protocols.normalized import run_openai_chat_shadow_normalization
from gpt2giga.providers.gigachat import GigaChatProviderAdapter
from gpt2giga.routers.openai.helpers import populate_giga_functions
from gpt2giga.sinks.observability.factory import emit_observability_event
from gpt2giga.sinks.observability.llm import (
    NORMALIZE_REQUEST_SPAN_NAME,
    NORMALIZE_RESPONSE_SPAN_NAME,
    STREAM_SPAN_NAME,
    build_llm_request_attributes,
    build_llm_response_attributes,
    build_stream_span_events,
)

router = APIRouter(tags=["OpenAI"])


@router.post("/chat/completions", openapi_extra=chat_completions_openapi_extra())
@exceptions_handler
async def chat_completions(request: Request):
    """Create a chat completion."""
    data = await read_request_json(request)
    request_data = deepcopy(data)
    request_options = extract_gigachat_request_options(request, data)
    stream = data.get("stream", False)
    current_rquid = rquid_context.get()
    state = request.app.state
    giga_client = get_gigachat_client(request)
    model_limiter = get_model_concurrency_limiter(request)
    mode = getattr(state.config.proxy_settings, "gigachat_api_mode", "v1")

    normalized_response = await _try_normalized_non_stream_chat(
        request,
        request_data,
        request_options,
        giga_client,
        model_limiter,
    )
    if normalized_response is not None:
        return normalized_response

    normalized_stream_response = await _try_normalized_stream_chat(
        request,
        request_data,
        request_options,
        giga_client,
        model_limiter,
    )
    if normalized_stream_response is not None:
        return normalized_stream_response

    await run_openai_chat_shadow_normalization(request, request_data)
    populate_giga_functions(data, getattr(state, "logger", None))
    if mode == "v2":
        async with gigachat_request_options(giga_client, request_options):
            chat_request = await state.request_transformer.prepare_chat_completion_v2(
                data, giga_client
            )
        effective_model = resolve_gigachat_model(chat_request, state.config)
        if stream:
            acquired_model_limit = model_limiter.limit(
                effective_model,
                provider="openai",
            )
            await acquired_model_limit.__aenter__()
            return StreamingResponse(
                stream_chat_completion_v2_generator(
                    request,
                    data["model"],
                    chat_request,
                    current_rquid,
                    giga_client,
                    request_options,
                    request_data=request_data,
                    model_limiter=model_limiter,
                    effective_model=effective_model,
                    acquired_model_limit=acquired_model_limit,
                ),
                media_type="text/event-stream",
            )
        async with model_limiter.limit(effective_model, provider="openai"):
            async with gigachat_request_options(giga_client, request_options):
                response = await giga_client.achat.create(chat_request)
        adapted = adapt_v2_completion_to_v1_shape(
            response,
            default_model=data["model"],
        )
        return state.response_processor.process_response(
            SimpleNamespace(model_dump=lambda: adapted),
            data["model"],
            current_rquid,
            request_data=request_data,
        )

    async with gigachat_request_options(giga_client, request_options):
        chat_messages = await state.request_transformer.prepare_chat_completion(
            data, giga_client
        )
    effective_model = resolve_gigachat_model(chat_messages, state.config)
    if not stream:
        async with model_limiter.limit(effective_model, provider="openai"):
            async with gigachat_request_options(giga_client, request_options):
                response = await giga_client.achat(chat_messages)
        return state.response_processor.process_response(
            response, data["model"], current_rquid, request_data=request_data
        )

    acquired_model_limit = model_limiter.limit(effective_model, provider="openai")
    await acquired_model_limit.__aenter__()
    return StreamingResponse(
        stream_chat_completion_generator(
            request,
            data["model"],
            chat_messages,
            current_rquid,
            giga_client,
            request_options,
            request_data=request_data,
            model_limiter=model_limiter,
            effective_model=effective_model,
            acquired_model_limit=acquired_model_limit,
        ),
        media_type="text/event-stream",
    )


async def _try_normalized_non_stream_chat(
    request: Request,
    payload: dict,
    request_options,
    giga_client,
    model_limiter,
) -> dict | None:
    state = request.app.state
    settings = getattr(getattr(state, "config", None), "proxy_settings", None)
    if (
        settings is None
        or settings.normalization_mode != "on"
        or payload.get("stream", False)
    ):
        return None

    try:
        protocol_adapter = state.openai_protocol_adapter
        context = get_request_context()
        normalized_request = await protocol_adapter.to_normalized(
            payload,
            context=context,
        )
        await _emit_normalized_request_observability(
            state,
            normalized_request,
            context=context,
        )
        provider_adapter = GigaChatProviderAdapter(
            config=state.config,
            request_transformer=state.request_transformer,
            giga_client=giga_client,
            model_limiter=model_limiter,
            request_options=request_options,
        )
        normalized_response = await provider_adapter.chat(
            normalized_request,
            context=context,
        )
        await _emit_normalized_response_observability(
            state,
            normalized_response,
            context=context,
        )
        return normalized_chat_response_to_openai(
            normalized_response,
            requested_model=payload["model"],
            context=context,
        )
    except Exception as exc:
        if not settings.legacy_chat_fallback:
            raise
        logger = getattr(state, "logger", None)
        if logger is not None:
            logger.bind(
                event="normalized_chat_fallback",
                route=request.url.path,
                error_type=type(exc).__name__,
                request_id=getattr(get_request_context(), "request_id", None),
            ).warning("Normalized chat path failed; using legacy fallback")
        return None


async def _try_normalized_stream_chat(
    request: Request,
    payload: dict,
    request_options,
    giga_client,
    model_limiter,
) -> StreamingResponse | None:
    state = request.app.state
    settings = getattr(getattr(state, "config", None), "proxy_settings", None)
    if (
        settings is None
        or settings.normalization_mode != "on"
        or not payload.get("stream", False)
    ):
        return None

    try:
        protocol_adapter = state.openai_protocol_adapter
        context = get_request_context()
        normalized_request = await protocol_adapter.to_normalized(
            payload,
            context=context,
        )
        await _emit_normalized_request_observability(
            state,
            normalized_request,
            context=context,
        )
        provider_adapter = GigaChatProviderAdapter(
            config=state.config,
            request_transformer=state.request_transformer,
            giga_client=giga_client,
            model_limiter=model_limiter,
            request_options=request_options,
            response_processor=state.response_processor,
        )
        response_id = context.request_id if context is not None else rquid_context.get()

        async def emit_stream():
            seen_content_delta = False
            async for event in provider_adapter.stream_chat(
                normalized_request,
                context=context,
                is_disconnected=request.is_disconnected,
                logger=getattr(state, "logger", None),
            ):
                first_content_delta = (
                    event.type == "content_delta"
                    and bool(event.content_delta)
                    and not seen_content_delta
                )
                span_events = build_stream_span_events(
                    event,
                    settings=settings,
                    first_content_delta=first_content_delta,
                )
                if span_events:
                    await emit_observability_event(
                        getattr(state, "observability_sink", None),
                        STREAM_SPAN_NAME,
                        span_events[0]["attributes"],
                        context=context,
                        events=span_events,
                        logger=getattr(state, "logger", None),
                    )
                if event.type == "content_delta" and event.content_delta:
                    seen_content_delta = True
                sse = normalized_stream_event_to_openai_sse(
                    event,
                    requested_model=payload["model"],
                    response_id=response_id,
                )
                if sse is not None:
                    yield sse
            yield normalized_stream_done_sse()

        return StreamingResponse(emit_stream(), media_type="text/event-stream")
    except Exception as exc:
        if not settings.legacy_chat_fallback:
            raise
        logger = getattr(state, "logger", None)
        if logger is not None:
            logger.bind(
                event="normalized_chat_stream_fallback",
                route=request.url.path,
                error_type=type(exc).__name__,
                request_id=getattr(get_request_context(), "request_id", None),
            ).warning("Normalized chat stream path failed; using legacy fallback")
        return None


async def _emit_normalized_request_observability(
    state,
    normalized_request,
    *,
    context,
) -> None:
    settings = getattr(getattr(state, "config", None), "proxy_settings", None)
    await emit_observability_event(
        getattr(state, "observability_sink", None),
        NORMALIZE_REQUEST_SPAN_NAME,
        build_llm_request_attributes(normalized_request, settings=settings),
        context=context,
        logger=getattr(state, "logger", None),
    )


async def _emit_normalized_response_observability(
    state,
    normalized_response,
    *,
    context,
) -> None:
    settings = getattr(getattr(state, "config", None), "proxy_settings", None)
    await emit_observability_event(
        getattr(state, "observability_sink", None),
        NORMALIZE_RESPONSE_SPAN_NAME,
        build_llm_response_attributes(normalized_response, settings=settings),
        context=context,
        logger=getattr(state, "logger", None),
    )
