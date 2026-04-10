"""OpenAI embeddings endpoint."""

from fastapi import APIRouter, Request

from gpt2giga.api.openai.openapi import embeddings_openapi_extra
from gpt2giga.api.openai.request_adapter import build_normalized_embeddings_request
from gpt2giga.core.errors import exceptions_handler
from gpt2giga.core.http.json_body import read_request_json
from gpt2giga.features.embeddings import get_embeddings_service_from_state
from gpt2giga.providers.gigachat.client import get_gigachat_client

router = APIRouter(tags=["OpenAI"])


@router.post("/embeddings", openapi_extra=embeddings_openapi_extra())
@exceptions_handler
async def embeddings(request: Request):
    """Create embeddings."""
    data = build_normalized_embeddings_request(await read_request_json(request))
    embeddings_service = get_embeddings_service_from_state(request.app.state)
    giga_client = get_gigachat_client(request)
    return await embeddings_service.create_embeddings(
        data,
        giga_client=giga_client,
    )
