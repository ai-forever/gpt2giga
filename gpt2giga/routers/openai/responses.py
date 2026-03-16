"""OpenAI responses endpoint."""

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from gpt2giga.app_state import get_gigachat_client
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.request_json import read_request_json
from gpt2giga.common.streaming import stream_responses_generator
from gpt2giga.logger import rquid_context
from gpt2giga.openapi_specs.openai import responses_openapi_extra
from gpt2giga.routers.openai.helpers import populate_giga_functions

router = APIRouter(tags=["OpenAI"])


@router.post("/responses", openapi_extra=responses_openapi_extra())
@exceptions_handler
async def responses(request: Request):
    """Create a Responses API response."""
    data = await read_request_json(request)
    stream = data.get("stream", False)
    current_rquid = rquid_context.get()
    state = request.app.state
    giga_client = get_gigachat_client(request)

    populate_giga_functions(data, getattr(state, "logger", None))
    chat_messages = await state.request_transformer.prepare_response(data, giga_client)
    if not stream:
        response = await giga_client.achat(chat_messages)
        return state.response_processor.process_response_api(
            data, response, data["model"], current_rquid
        )

    return StreamingResponse(
        stream_responses_generator(
            request, chat_messages, current_rquid, giga_client, request_data=data
        ),
        media_type="text/event-stream",
    )
