"""OpenAI responses endpoint."""

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from gpt2giga.api.openai.helpers import populate_giga_functions
from gpt2giga.api.openai.openapi import responses_openapi_extra
from gpt2giga.app.dependencies import get_logger_from_state
from gpt2giga.core.errors import exceptions_handler
from gpt2giga.core.http.json_body import read_request_json
from gpt2giga.core.logging.setup import rquid_context
from gpt2giga.features.responses import get_responses_service_from_state
from gpt2giga.features.responses.store import get_response_store
from gpt2giga.providers.gigachat.client import get_gigachat_client

router = APIRouter(tags=["OpenAI"])


@router.post("/responses", openapi_extra=responses_openapi_extra())
@exceptions_handler
async def responses(request: Request):
    """Create a Responses API response."""
    data = await read_request_json(request)
    current_rquid = rquid_context.get()
    giga_client = get_gigachat_client(request)
    app_state = request.app.state
    responses_service = get_responses_service_from_state(app_state)
    response_store = get_response_store(request)

    populate_giga_functions(data, get_logger_from_state(app_state))
    if not data.get("stream", False):
        return await responses_service.create_response(
            data,
            giga_client=giga_client,
            response_id=current_rquid,
            response_store=response_store,
        )

    return StreamingResponse(
        responses_service.stream_response(
            request,
            data,
            giga_client=giga_client,
            response_id=current_rquid,
            response_store=response_store,
        ),
        media_type="text/event-stream",
    )
