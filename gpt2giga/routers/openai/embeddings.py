"""OpenAI embeddings endpoint."""

from fastapi import APIRouter, Request

from gpt2giga.app_state import get_gigachat_client, get_model_concurrency_limiter
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.gigachat_options import (
    extract_gigachat_request_options,
    gigachat_request_options,
)
from gpt2giga.common.debug_logging import log_debug_payload
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
    request_options = extract_gigachat_request_options(request, data)
    giga_client = get_gigachat_client(request)
    model_limiter = get_model_concurrency_limiter(request)
    proxy_settings = request.app.state.config.proxy_settings
    transformed = await transform_embedding_body(
        data,
        proxy_settings.embeddings,
        pass_model=proxy_settings.pass_model,
    )
    effective_model = transformed["model"]
    log_debug_payload(
        getattr(request.app.state, "logger", None),
        request.app.state.config,
        event="gigachat_embeddings_request",
        message="Sending embeddings request to GigaChat API",
        payload_key="payload",
        payload=transformed,
        input_count=len(transformed["input"]),
        model=effective_model,
    )
    async with model_limiter.limit(effective_model, provider="openai"):
        async with gigachat_request_options(giga_client, request_options):
            response = await giga_client.aembeddings(
                texts=transformed["input"], model=effective_model
            )
    normalized = normalize_embedding_response(response, model=effective_model)
    result = apply_embedding_encoding_format(normalized, data.get("encoding_format"))
    log_debug_payload(
        getattr(request.app.state, "logger", None),
        request.app.state.config,
        event="embeddings_response",
        message="Processed embeddings response",
        payload_key="response",
        payload=result,
        model=effective_model,
    )
    return result
