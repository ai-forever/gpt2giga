"""OpenAI responses endpoint."""

from types import SimpleNamespace

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from gpt2giga.app_state import get_gigachat_client, get_model_concurrency_limiter
from gpt2giga.common.api_mode import resolve_gigachat_api_mode
from gpt2giga.common.client_params import (
    ClientCompatibilityError,
    client_compatibility_response,
)
from gpt2giga.common.conversation import (
    commit_responses_response,
    stitch_responses_payload,
    stitch_responses_stream,
)
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.gigachat_options import (
    extract_gigachat_request_options,
    gigachat_request_options,
)
from gpt2giga.common.request_json import read_request_json
from gpt2giga.common.streaming import (
    stream_responses_generator,
    stream_responses_chat_completion_generator,
)
from gpt2giga.core.context import get_request_context, update_request_context
from gpt2giga.logger import rquid_context
from gpt2giga.openapi_specs.openai import responses_openapi_extra
from gpt2giga.openapi_tags import OPENAPI_TAG_OPENAI_RESPONSES
from gpt2giga.protocol.response import (
    adapt_chat_completion_to_chat_shape,
    extract_chat_completion_thread_id,
    hydrate_chat_completion_image_files,
)
from gpt2giga.protocols.openai import (
    OpenAIProtocolAdapter,
    ResponsesStreamProjector,
    ResponsesStreamProtocolError,
    normalized_chat_response_to_responses,
)
from gpt2giga.providers.gigachat import GigaChatProviderAdapter
from gpt2giga.providers.gigachat.model_resolution import resolve_upstream_model
from gpt2giga.routers.openai.helpers import (
    populate_giga_functions,
    request_attachment_ids,
)
from gpt2giga.sinks.observability.responses import (
    emit_openai_response_observability,
    observe_openai_response_stream,
)

router = APIRouter(tags=[OPENAPI_TAG_OPENAI_RESPONSES])


@router.post("/responses", openapi_extra=responses_openapi_extra())
@exceptions_handler
async def responses(request: Request):
    """Create through normalized startup owners.

    The integration-owned ``provider_registry`` supplies the provider adapter.
    """
    data = await read_request_json(request)
    stream = data.get("stream", False)
    state = request.app.state
    legacy_responses_enabled = getattr(state, "legacy_responses_enabled", False) is True
    if legacy_responses_enabled:
        return await _legacy_responses(request, data)

    protocol_adapter = (
        getattr(
            state,
            "openai_protocol_adapter",
            None,
        )
        or OpenAIProtocolAdapter()
    )
    try:
        if stream:
            return await _normalized_stream_response(
                request,
                data,
                protocol_adapter=protocol_adapter,
            )
        return await _normalized_non_stream_response(
            request,
            data,
            protocol_adapter=protocol_adapter,
        )
    except ClientCompatibilityError as exc:
        return client_compatibility_response(exc)


async def _legacy_responses(request: Request, data: dict):
    """Run the explicitly selected pre-0.3 Responses compatibility path."""
    stream = data.get("stream", False)
    state = request.app.state

    request_options = extract_gigachat_request_options(request, data)
    current_rquid = rquid_context.get()
    giga_client = get_gigachat_client(request)
    model_limiter = get_model_concurrency_limiter(request)
    mode = resolve_gigachat_api_mode(request)
    conversation_turn = await stitch_responses_payload(request, data, mode=mode)

    populate_giga_functions(data, getattr(state, "logger", None))
    attachment_ids = request_attachment_ids(request)
    attachment_kwargs = {"attachment_ids": attachment_ids} if attachment_ids else {}
    if mode == "v2":
        async with gigachat_request_options(giga_client, request_options):
            chat_request = (
                await state.request_transformer.prepare_response_chat_completion(
                    data,
                    giga_client,
                    **attachment_kwargs,
                )
            )
        model_resolution = resolve_upstream_model(
            chat_request,
            state.config,
            api_mode="v2",
        )
        update_request_context(
            model_effective=model_resolution.model,
            metadata={"model_source": model_resolution.source},
        )
        if stream:
            acquired_model_limit = model_limiter.limit(
                model_resolution.limiter_key,
                provider="openai",
            )
            await acquired_model_limit.__aenter__()
            return StreamingResponse(
                observe_openai_response_stream(
                    state,
                    stream_responses_chat_completion_generator(
                        request,
                        chat_request,
                        current_rquid,
                        giga_client,
                        request_data=data,
                        request_options=request_options,
                        model_limiter=model_limiter,
                        effective_model=model_resolution.limiter_key,
                        acquired_model_limit=acquired_model_limit,
                    ),
                    request_payload=data,
                    context=get_request_context(),
                ),
                media_type="text/event-stream",
            )
        async with model_limiter.limit(
            model_resolution.limiter_key,
            provider="openai",
        ):
            async with gigachat_request_options(giga_client, request_options):
                response = await giga_client.achat.create(chat_request)
        adapted = adapt_chat_completion_to_chat_shape(
            response,
            default_model=data["model"],
        )
        async with gigachat_request_options(giga_client, request_options):
            await hydrate_chat_completion_image_files(
                adapted,
                giga_client,
                getattr(state, "logger", None),
            )
        response_id = extract_chat_completion_thread_id(response) or current_rquid
        result = state.response_processor.process_response_api(
            data,
            SimpleNamespace(model_dump=lambda: adapted),
            data["model"],
            response_id,
        )
        await commit_responses_response(request, conversation_turn, result)
        await emit_openai_response_observability(
            state,
            data,
            result,
            context=get_request_context(),
        )
        return result

    async with gigachat_request_options(giga_client, request_options):
        chat_messages = await state.request_transformer.prepare_response_chat(
            data,
            giga_client,
            **attachment_kwargs,
        )
    model_resolution = resolve_upstream_model(
        chat_messages,
        state.config,
        api_mode="v1",
    )
    update_request_context(
        model_effective=model_resolution.model,
        metadata={"model_source": model_resolution.source},
    )
    if not stream:
        async with model_limiter.limit(
            model_resolution.limiter_key,
            provider="openai",
        ):
            async with gigachat_request_options(giga_client, request_options):
                response = await giga_client.achat(chat_messages)
        result = state.response_processor.process_response_api(
            data, response, data["model"], current_rquid
        )
        await commit_responses_response(request, conversation_turn, result)
        await emit_openai_response_observability(
            state,
            data,
            result,
            context=get_request_context(),
        )
        return result

    acquired_model_limit = model_limiter.limit(
        model_resolution.limiter_key,
        provider="openai",
    )
    await acquired_model_limit.__aenter__()
    stream = stream_responses_generator(
        request,
        chat_messages,
        current_rquid,
        giga_client,
        request_data=data,
        request_options=request_options,
        model_limiter=model_limiter,
        effective_model=model_resolution.limiter_key,
        acquired_model_limit=acquired_model_limit,
    )
    return StreamingResponse(
        observe_openai_response_stream(
            state,
            stitch_responses_stream(request, conversation_turn, stream),
            request_payload=data,
            context=get_request_context(),
        ),
        media_type="text/event-stream",
    )


async def _normalized_non_stream_response(
    request: Request,
    data: dict,
    *,
    protocol_adapter,
) -> dict:
    state = request.app.state
    context = get_request_context()
    normalized_request = await protocol_adapter.responses_to_normalized_async(
        data,
        context=context,
    )
    if request_attachment_ids(request):
        raise ClientCompatibilityError(
            "The selected bridge route cannot preserve this semantic.",
            param="x-gpt2giga-attachment-ids",
            code="unsupported_semantic",
        )

    conversation_turn = await stitch_responses_payload(
        request,
        data,
        mode=resolve_gigachat_api_mode(request),
    )
    request_options = extract_gigachat_request_options(request, data)
    provider_adapter = _normalized_provider_adapter(
        request,
        request_options=request_options,
    )
    normalized_response = await provider_adapter.chat(
        normalized_request,
        context=context,
    )
    response_id = _normalized_response_id(normalized_response, context=context)
    result = normalized_chat_response_to_responses(
        normalized_response,
        request_payload=data,
        requested_model=data["model"],
        response_id=response_id,
    )
    await commit_responses_response(request, conversation_turn, result)
    await emit_openai_response_observability(
        state,
        data,
        result,
        context=context,
    )
    return result


async def _normalized_stream_response(
    request: Request,
    data: dict,
    *,
    protocol_adapter,
) -> StreamingResponse:
    state = request.app.state
    context = get_request_context()
    normalized_request = await protocol_adapter.responses_to_normalized_async(
        data,
        context=context,
    )
    if request_attachment_ids(request):
        raise ClientCompatibilityError(
            "The selected bridge route cannot preserve this semantic.",
            param="x-gpt2giga-attachment-ids",
            code="unsupported_semantic",
        )

    conversation_turn = await stitch_responses_payload(
        request,
        data,
        mode=resolve_gigachat_api_mode(request),
    )
    request_options = extract_gigachat_request_options(request, data)
    provider_adapter = _normalized_provider_adapter(
        request,
        request_options=request_options,
        require_streaming=True,
    )
    response_id = (
        context.request_id
        if context is not None and context.request_id
        else rquid_context.get()
    )
    projector = ResponsesStreamProjector(
        request_payload=data,
        requested_model=data["model"],
        response_id=response_id,
    )

    async def emit_stream():
        try:
            async for event in provider_adapter.stream_chat(
                normalized_request,
                context=context,
                is_disconnected=request.is_disconnected,
                logger=getattr(state, "logger", None),
            ):
                for frame in projector.project(event):
                    yield frame
            if await request.is_disconnected():
                return
            projector.finish()
        except ResponsesStreamProtocolError:
            if projector.terminal:
                raise
            yield projector.protocol_error_frame()

    stream = stitch_responses_stream(request, conversation_turn, emit_stream())
    return StreamingResponse(
        observe_openai_response_stream(
            state,
            stream,
            request_payload=data,
            context=context,
        ),
        media_type="text/event-stream",
    )


def _normalized_provider_adapter(
    request: Request,
    *,
    request_options,
    require_streaming: bool = False,
):
    state = request.app.state
    injected = getattr(state, "responses_provider_adapter", None)
    if injected is not None:
        return injected
    configured_model = getattr(
        getattr(state.config, "gigachat_settings", None),
        "model",
        None,
    )
    return GigaChatProviderAdapter(
        config=state.config,
        request_transformer=state.request_transformer,
        giga_client=get_gigachat_client(request),
        model_limiter=get_model_concurrency_limiter(request),
        request_options=request_options,
        response_processor=state.response_processor if require_streaming else None,
        api_mode=resolve_gigachat_api_mode(request),
        forced_model=configured_model,
    )


def _normalized_response_id(normalized_response, *, context) -> str:
    gigachat_metadata = normalized_response.provider_metadata.get("gigachat")
    if isinstance(gigachat_metadata, dict):
        thread_id = gigachat_metadata.get("thread_id")
        if isinstance(thread_id, str) and thread_id:
            return thread_id
    if normalized_response.id:
        return normalized_response.id
    if context is not None and context.request_id:
        return context.request_id
    return rquid_context.get()
