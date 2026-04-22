"""Gemini content generation and embedding routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from gpt2giga.api.gemini.openapi import (
    gemini_batch_embed_contents_openapi_extra,
    gemini_count_tokens_openapi_extra,
    gemini_generate_content_openapi_extra,
)
from gpt2giga.api.gemini.request import (
    GeminiAPIError,
    model_resource_name,
    normalize_model_name,
    read_gemini_request_json,
)
from gpt2giga.api.gemini.response import (
    build_batch_embed_contents_response,
    build_generate_content_response,
    build_single_embed_content_response,
    gemini_exceptions_handler,
)
from gpt2giga.api.gemini.streaming import stream_gemini_generate_content
from gpt2giga.api.tags import (
    PROVIDER_GEMINI,
    TAG_CHAT,
    TAG_COUNT_TOKENS,
    TAG_EMBEDDINGS,
    provider_tag,
)
from gpt2giga.app.dependencies import (
    get_logger_from_state,
)
from gpt2giga.app.observability import (
    annotate_request_audit_request_payload,
    annotate_request_audit_from_payload,
    set_request_audit_model,
)
from gpt2giga.core.logging.setup import rquid_context
from gpt2giga.features.chat.service import get_chat_service_from_state
from gpt2giga.features.embeddings import get_embeddings_service_from_state
from gpt2giga.providers.gemini import gemini_provider_adapters
from gpt2giga.providers.gigachat.client import get_gigachat_client
from gpt2giga.providers.token_counting import count_input_tokens

router = APIRouter()


def _ensure_route_model_matches_body(route_model: str, body_model: str | None) -> str:
    """Validate a route model against an optional body model."""
    normalized_route_model = normalize_model_name(route_model)
    normalized_body_model = normalize_model_name(body_model)
    if normalized_body_model and normalized_body_model != normalized_route_model:
        raise GeminiAPIError(
            status_code=400,
            status="INVALID_ARGUMENT",
            message=(
                f"Request model `{body_model}` does not match route model "
                f"`{model_resource_name(route_model)}`."
            ),
        )
    return normalized_route_model


@router.post(
    "/models/{model}:generateContent",
    openapi_extra=gemini_generate_content_openapi_extra(),
    tags=[provider_tag(TAG_CHAT, PROVIDER_GEMINI)],
)
@gemini_exceptions_handler
async def generate_content(model: str, request: Request):
    """Gemini Developer API compatible generateContent endpoint."""
    data = await read_gemini_request_json(request)
    annotate_request_audit_request_payload(request, data)
    normalized_model = _ensure_route_model_matches_body(model, data.get("model"))
    data["model"] = normalized_model
    set_request_audit_model(request, normalized_model)

    giga_client = get_gigachat_client(request)
    app_state = request.app.state
    chat_service = get_chat_service_from_state(app_state)
    normalized_request = gemini_provider_adapters.chat.build_normalized_request(
        data,
        logger=get_logger_from_state(app_state),
    )
    chat_messages = await chat_service.prepare_request(
        normalized_request,
        giga_client=giga_client,
    )
    response = await chat_service.execute_prepared_request(
        chat_messages,
        giga_client=giga_client,
    )
    giga_dict = chat_service.normalize_provider_response(response)
    gemini_response = build_generate_content_response(
        giga_dict,
        normalized_model,
        rquid_context.get(),
        request_data=data,
    )
    annotate_request_audit_from_payload(
        request,
        gemini_response,
        fallback_model=normalized_model,
    )
    return gemini_response


@router.post(
    "/models/{model}:streamGenerateContent",
    openapi_extra=gemini_generate_content_openapi_extra(),
    tags=[provider_tag(TAG_CHAT, PROVIDER_GEMINI)],
)
@gemini_exceptions_handler
async def stream_generate_content(model: str, request: Request):
    """Gemini Developer API compatible streaming endpoint."""
    data = await read_gemini_request_json(request)
    normalized_model = _ensure_route_model_matches_body(model, data.get("model"))
    data["model"] = normalized_model
    set_request_audit_model(request, normalized_model)

    giga_client = get_gigachat_client(request)
    app_state = request.app.state
    chat_service = get_chat_service_from_state(app_state)
    api_mode = chat_service.backend_mode
    normalized_request = gemini_provider_adapters.chat.build_normalized_request(
        data,
        logger=get_logger_from_state(app_state),
    )
    chat_messages = await chat_service.prepare_request(
        normalized_request,
        giga_client=giga_client,
    )
    response_id = rquid_context.get()
    return StreamingResponse(
        stream_gemini_generate_content(
            request,
            normalized_model,
            chat_messages,
            response_id,
            giga_client,
            request_data=data,
            api_mode=api_mode,
            response_processor=chat_service.response_processor,
        ),
        media_type="text/event-stream",
    )


@router.post(
    "/models/{model}:countTokens",
    openapi_extra=gemini_count_tokens_openapi_extra(),
    tags=[provider_tag(TAG_COUNT_TOKENS, PROVIDER_GEMINI)],
)
@gemini_exceptions_handler
async def count_tokens(model: str, request: Request):
    """Gemini Developer API compatible countTokens endpoint."""
    data = await read_gemini_request_json(request)
    normalized_model = _ensure_route_model_matches_body(model, data.get("model"))
    set_request_audit_model(request, normalized_model)
    count_payload = data.get("generateContentRequest") or data
    if not isinstance(count_payload, dict):
        raise GeminiAPIError(
            status_code=400,
            status="INVALID_ARGUMENT",
            message="`generateContentRequest` must be an object when provided.",
        )

    giga_client = get_gigachat_client(request)
    chat_adapter = gemini_provider_adapters.chat
    assert chat_adapter is not None
    return {
        "totalTokens": await count_input_tokens(
            chat_adapter,
            count_payload,
            giga_client=giga_client,
            model=normalized_model,
        )
    }


@router.post(
    "/models/{model}:batchEmbedContents",
    openapi_extra=gemini_batch_embed_contents_openapi_extra(),
    tags=[provider_tag(TAG_EMBEDDINGS, PROVIDER_GEMINI)],
)
@gemini_exceptions_handler
async def batch_embed_contents(model: str, request: Request):
    """Gemini Developer API compatible batch embeddings endpoint."""
    data = await read_gemini_request_json(request)
    set_request_audit_model(request, normalize_model_name(model))
    requests_payload = data.get("requests")
    if not isinstance(requests_payload, list) or not requests_payload:
        raise GeminiAPIError(
            status_code=400,
            status="INVALID_ARGUMENT",
            message="`requests` must be a non-empty array.",
        )

    embeddings_service = get_embeddings_service_from_state(request.app.state)
    giga_client = get_gigachat_client(request)
    normalized_request = gemini_provider_adapters.embeddings.build_batch_request(
        requests_payload,
        model,
    )
    result = await embeddings_service.create_embeddings(
        normalized_request,
        giga_client=giga_client,
    )
    return build_batch_embed_contents_response(result)


@router.post(
    "/models/{model}:embedContent",
    tags=[provider_tag(TAG_EMBEDDINGS, PROVIDER_GEMINI)],
)
@gemini_exceptions_handler
async def embed_content(model: str, request: Request):
    """Gemini REST alias for single-item embeddings."""
    data = await read_gemini_request_json(request)
    set_request_audit_model(request, normalize_model_name(model))
    embeddings_service = get_embeddings_service_from_state(request.app.state)
    giga_client = get_gigachat_client(request)
    normalized_request = gemini_provider_adapters.embeddings.build_single_request(
        data, model_resource_name(model)
    )
    result = await embeddings_service.create_embeddings(
        normalized_request,
        giga_client=giga_client,
    )
    return build_single_embed_content_response(result)
