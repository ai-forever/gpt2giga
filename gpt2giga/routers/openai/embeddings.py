"""OpenAI embeddings endpoint."""

from fastapi import APIRouter, Request

from gpt2giga.app_state import get_gigachat_client
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.request_json import read_request_json
from gpt2giga.openapi_specs.openai import embeddings_openapi_extra
from gpt2giga.protocol.embeddings import (
    apply_embedding_encoding_format,
    normalize_embedding_response,
    transform_embedding_body,
)

router = APIRouter(tags=["OpenAI"])


@router.post("/embeddings", openapi_extra=embeddings_openapi_extra())
@exceptions_handler
async def embeddings(request: Request):
    """Create embeddings."""
    data = await read_request_json(request)
    giga_client = get_gigachat_client(request)
    proxy_settings = request.app.state.config.proxy_settings
    transformed = await transform_embedding_body(
        data,
        proxy_settings.embeddings,
        pass_model=proxy_settings.pass_model,
    )
    response = await giga_client.aembeddings(
        texts=transformed["input"], model=transformed["model"]
    )
    normalized = normalize_embedding_response(response, model=transformed["model"])
    return apply_embedding_encoding_format(normalized, data.get("encoding_format"))
