"""OpenAI chat completions endpoint."""

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from gpt2giga.api.openai.helpers import populate_giga_functions
from gpt2giga.api.openai.openapi import chat_completions_openapi_extra
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.request_json import read_request_json
from gpt2giga.core.logging.setup import rquid_context
from gpt2giga.features.chat.service import get_chat_service_from_state
from gpt2giga.providers.gigachat.client import get_gigachat_client

router = APIRouter(tags=["OpenAI"])


@router.post("/chat/completions", openapi_extra=chat_completions_openapi_extra())
@exceptions_handler
async def chat_completions(request: Request):
    """Create a chat completion."""
    data = await read_request_json(request)
    current_rquid = rquid_context.get()
    state = request.app.state
    giga_client = get_gigachat_client(request)
    chat_service = get_chat_service_from_state(state)

    populate_giga_functions(data, getattr(state, "logger", None))
    if not data.get("stream", False):
        return await chat_service.create_completion(
            data,
            giga_client=giga_client,
            response_id=current_rquid,
        )

    return StreamingResponse(
        chat_service.stream_completion(
            request,
            data,
            giga_client=giga_client,
            response_id=current_rquid,
        ),
        media_type="text/event-stream",
    )
