"""OpenAI responses endpoint."""

from collections.abc import Mapping
from copy import deepcopy
from types import SimpleNamespace

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from gpt2giga.app_state import (
    get_fusion_request_limiter,
    get_gigachat_client,
    get_model_concurrency_limiter,
)
from gpt2giga.common.api_mode import resolve_gigachat_api_mode
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
from gpt2giga.common.model_concurrency import resolve_gigachat_model
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
from gpt2giga.protocols.normalized import NormalizedChatRequest
from gpt2giga.protocols.openai import (
    buffered_response_sse_from_normalized_response,
    normalized_response_to_openai_response,
    responses_request_to_normalized,
)
from gpt2giga.providers.fusion.adapter import FusionProviderAdapter
from gpt2giga.providers.fusion.detection import extract_fusion_request
from gpt2giga.providers.fusion.errors import FusionConfigurationError
from gpt2giga.providers.gigachat import GigaChatProviderAdapter
from gpt2giga.routers.openai.helpers import populate_giga_functions
from gpt2giga.sinks.observability.responses import (
    emit_openai_response_observability,
    observe_openai_response_stream,
)

router = APIRouter(tags=[OPENAPI_TAG_OPENAI_RESPONSES])


@router.post("/responses", openapi_extra=responses_openapi_extra())
@exceptions_handler
async def responses(request: Request):
    """Create a Responses API response."""
    data = await read_request_json(request)
    request_options = extract_gigachat_request_options(request, data)
    stream = data.get("stream", False)
    current_rquid = rquid_context.get()
    state = request.app.state
    giga_client = get_gigachat_client(request)
    model_limiter = get_model_concurrency_limiter(request)
    mode = resolve_gigachat_api_mode(request)
    conversation_turn = await stitch_responses_payload(request, data, mode=mode)
    request_data = deepcopy(data)

    fusion_response = await _try_fusion_responses(
        request,
        request_data,
        request_options,
        giga_client,
        model_limiter,
        conversation_turn,
    )
    if fusion_response is not None:
        return fusion_response

    populate_giga_functions(data, getattr(state, "logger", None))
    if mode == "v2":
        async with gigachat_request_options(giga_client, request_options):
            chat_request = (
                await state.request_transformer.prepare_response_chat_completion(
                    data, giga_client
                )
            )
        effective_model = resolve_gigachat_model(chat_request, state.config)
        update_request_context(model_effective=effective_model)
        if stream:
            acquired_model_limit = model_limiter.limit(
                effective_model,
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
                        effective_model=effective_model,
                        acquired_model_limit=acquired_model_limit,
                    ),
                    request_payload=data,
                    context=get_request_context(),
                ),
                media_type="text/event-stream",
            )
        async with model_limiter.limit(effective_model, provider="openai"):
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
            data, giga_client
        )
    effective_model = resolve_gigachat_model(chat_messages, state.config)
    update_request_context(model_effective=effective_model)
    if not stream:
        async with model_limiter.limit(effective_model, provider="openai"):
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
        effective_model,
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
        effective_model=effective_model,
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


async def _try_fusion_responses(
    request: Request,
    payload: dict,
    request_options,
    giga_client,
    model_limiter,
    conversation_turn,
) -> dict | JSONResponse | StreamingResponse | None:
    state = request.app.state
    settings = getattr(getattr(state, "config", None), "proxy_settings", None)
    if settings is None:
        return None

    fusion_settings = settings.fusion
    try:
        fusion_config = extract_fusion_request(payload, fusion_settings)
    except FusionConfigurationError as exc:
        return _openai_invalid_request_response(
            str(exc),
            code="fusion_configuration_error",
        )
    if fusion_config is None:
        return None

    stream = bool(payload.get("stream", False))
    if stream and fusion_settings.streaming_mode != "buffered":
        return _openai_invalid_request_response(
            "Fusion streaming is disabled.",
            code="fusion_streaming_disabled",
        )

    context = get_request_context()
    normalized_request = responses_request_to_normalized(payload, context=context)
    _strip_fusion_request_artifacts(normalized_request)
    upstream_provider = GigaChatProviderAdapter(
        config=state.config,
        request_transformer=state.request_transformer,
        giga_client=giga_client,
        model_limiter=model_limiter,
        request_options=request_options,
        response_processor=getattr(state, "response_processor", None),
        api_mode=resolve_gigachat_api_mode(request),
        provider_label="openai",
        force_request_model=True,
    )
    fusion_adapter = FusionProviderAdapter(
        settings=fusion_settings,
        upstream_provider=upstream_provider,
        metrics_sink=getattr(state, "metrics_sink", None),
        observability_sink=getattr(state, "observability_sink", None),
        logger=getattr(state, "logger", None),
        request_limiter=get_fusion_request_limiter(request),
    )
    normalized_response = await fusion_adapter.chat(
        normalized_request,
        context=context,
        fusion_config=fusion_config,
        is_disconnected=request.is_disconnected,
    )
    requested_model = str(
        payload.get("model") or normalized_response.model or "GigaChat"
    )
    response_id = normalized_response.id
    if response_id is None:
        response_id = context.request_id if context is not None else rquid_context.get()
    response_id = response_id or "fusion"

    if normalized_response.error is not None:
        openai_response = normalized_response_to_openai_response(
            normalized_response,
            request_payload=payload,
            requested_model=requested_model,
            response_id=response_id,
        )
        await emit_openai_response_observability(
            state,
            payload,
            openai_response,
            context=context,
        )
        return JSONResponse(status_code=502, content=openai_response)

    if not stream:
        openai_response = normalized_response_to_openai_response(
            normalized_response,
            request_payload=payload,
            requested_model=requested_model,
            response_id=response_id,
        )
        await commit_responses_response(request, conversation_turn, openai_response)
        await emit_openai_response_observability(
            state,
            payload,
            openai_response,
            context=context,
        )
        return openai_response

    body_iterator = stitch_responses_stream(
        request,
        conversation_turn,
        buffered_response_sse_from_normalized_response(
            normalized_response,
            request_payload=payload,
            requested_model=requested_model,
            response_id=response_id,
        ),
    )
    return StreamingResponse(
        observe_openai_response_stream(
            state,
            body_iterator,
            request_payload=payload,
            context=context,
        ),
        media_type="text/event-stream",
    )


def _strip_fusion_request_artifacts(normalized_request: NormalizedChatRequest) -> None:
    normalized_request.tools = [
        tool for tool in normalized_request.tools if tool.type != "openrouter:fusion"
    ]
    normalized_request.metadata.pop("gpt2giga_fusion", None)
    gigachat_metadata = normalized_request.provider_metadata.get("gigachat")
    if isinstance(gigachat_metadata, Mapping):
        additional_fields = gigachat_metadata.get("additional_fields")
        if isinstance(additional_fields, dict):
            for key in ("plugins", "gpt2giga_fusion"):
                additional_fields.pop(key, None)
    for key in ("plugins", "gpt2giga_fusion"):
        normalized_request.raw_extensions.pop(key, None)


def _openai_invalid_request_response(
    message: str,
    *,
    code: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "message": message,
                "type": "invalid_request_error",
                "param": "model",
                "code": code,
            }
        },
    )
