"""OpenAI responses endpoint."""

from types import SimpleNamespace

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from gpt2giga.app_state import get_gigachat_client, get_model_concurrency_limiter
from gpt2giga.common.api_mode import resolve_responses_api_mode
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
    mode = resolve_responses_api_mode(request)
    conversation_turn = await stitch_responses_payload(request, data, mode=mode)

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
