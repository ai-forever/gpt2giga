"""OpenAI embeddings endpoint."""

from fastapi import APIRouter, Request

from gpt2giga.app_state import get_gigachat_client
from gpt2giga.api.openai.openapi import embeddings_openapi_extra
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.request_json import read_request_json
from gpt2giga.protocol.batches import transform_embedding_body

router = APIRouter(tags=["OpenAI"])


@router.post("/embeddings", openapi_extra=embeddings_openapi_extra())
@exceptions_handler
async def embeddings(request: Request):
    """Create embeddings."""
    data = await read_request_json(request)
    giga_client = get_gigachat_client(request)
    transformed = await transform_embedding_body(
        data, request.app.state.config.proxy_settings.embeddings
    )
    return await giga_client.aembeddings(
        texts=transformed["input"], model=transformed["model"]
    )
