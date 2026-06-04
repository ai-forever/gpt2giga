"""OpenAI responses endpoint."""

from types import SimpleNamespace

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from gpt2giga.app_state import get_gigachat_client
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.gigachat_options import (
    extract_gigachat_request_options,
    gigachat_request_options,
)
from gpt2giga.common.request_json import read_request_json
from gpt2giga.common.streaming import (
    stream_responses_generator,
    stream_responses_v2_generator,
)
from gpt2giga.logger import rquid_context
from gpt2giga.openapi_specs.openai import responses_openapi_extra
from gpt2giga.protocol.response import (
    adapt_v2_completion_to_v1_shape,
    extract_v2_thread_id,
    hydrate_v2_image_files,
)
from gpt2giga.routers.openai.helpers import populate_giga_functions

router = APIRouter(tags=["OpenAI"])


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
    settings = state.config.proxy_settings
    mode = settings.resolve_responses_api_mode()

    populate_giga_functions(data, getattr(state, "logger", None))
    if mode == "v2":
        async with gigachat_request_options(giga_client, request_options):
            chat_request = await state.request_transformer.prepare_response_v2(
                data, giga_client
            )
        if stream:
            return StreamingResponse(
                stream_responses_v2_generator(
                    request,
                    chat_request,
                    current_rquid,
                    giga_client,
                    request_data=data,
                    request_options=request_options,
                ),
                media_type="text/event-stream",
            )
        async with gigachat_request_options(giga_client, request_options):
            response = await giga_client.achat.create(chat_request)
        adapted = adapt_v2_completion_to_v1_shape(
            response,
            default_model=data["model"],
        )
        async with gigachat_request_options(giga_client, request_options):
            await hydrate_v2_image_files(
                adapted,
                giga_client,
                getattr(state, "logger", None),
            )
        response_id = extract_v2_thread_id(response) or current_rquid
        return state.response_processor.process_response_api(
            data,
            SimpleNamespace(model_dump=lambda: adapted),
            data["model"],
            response_id,
        )

    async with gigachat_request_options(giga_client, request_options):
        chat_messages = await state.request_transformer.prepare_response(
            data, giga_client
        )
    if not stream:
        async with gigachat_request_options(giga_client, request_options):
            response = await giga_client.achat(chat_messages)
        return state.response_processor.process_response_api(
            data, response, data["model"], current_rquid
        )

    return StreamingResponse(
        stream_responses_generator(
            request,
            chat_messages,
            current_rquid,
            giga_client,
            request_data=data,
            request_options=request_options,
        ),
        media_type="text/event-stream",
    )
