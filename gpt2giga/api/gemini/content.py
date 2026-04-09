"""Gemini content generation and embedding routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from gpt2giga.api.gemini.openapi import (
    gemini_batch_embed_contents_openapi_extra,
    gemini_count_tokens_openapi_extra,
    gemini_generate_content_openapi_extra,
)
from gpt2giga.app.dependencies import (
    get_logger_from_state,
    get_request_transformer_from_state,
)
from gpt2giga.core.logging.setup import rquid_context
from gpt2giga.features.embeddings import get_embeddings_service_from_state
from gpt2giga.protocol.gemini import (
    GeminiAPIError,
    build_batch_embed_contents_response,
    build_generate_content_response,
    build_openai_data_from_gemini_request,
    build_single_embed_content_response,
    extract_embed_texts,
    extract_text_for_token_count,
    gemini_exceptions_handler,
    model_resource_name,
    normalize_model_name,
    read_gemini_request_json,
    stream_gemini_generate_content,
)
from gpt2giga.providers.gigachat.client import get_gigachat_client

router = APIRouter(tags=["Gemini"])


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
)
@gemini_exceptions_handler
async def generate_content(model: str, request: Request):
    """Gemini Developer API compatible generateContent endpoint."""
    data = await read_gemini_request_json(request)
    normalized_model = _ensure_route_model_matches_body(model, data.get("model"))
    data["model"] = normalized_model

    giga_client = get_gigachat_client(request)
    app_state = request.app.state
    openai_data = build_openai_data_from_gemini_request(
        data, get_logger_from_state(app_state)
    )
    chat_messages = await get_request_transformer_from_state(
        app_state
    ).prepare_chat_completion(openai_data, giga_client)
    response = await giga_client.achat(chat_messages)
    return build_generate_content_response(
        response.model_dump(),
        normalized_model,
        rquid_context.get(),
        request_data=data,
    )


@router.post(
    "/models/{model}:streamGenerateContent",
    openapi_extra=gemini_generate_content_openapi_extra(),
)
@gemini_exceptions_handler
async def stream_generate_content(model: str, request: Request):
    """Gemini Developer API compatible streaming endpoint."""
    data = await read_gemini_request_json(request)
    normalized_model = _ensure_route_model_matches_body(model, data.get("model"))
    data["model"] = normalized_model

    giga_client = get_gigachat_client(request)
    app_state = request.app.state
    openai_data = build_openai_data_from_gemini_request(
        data, get_logger_from_state(app_state)
    )
    chat_messages = await get_request_transformer_from_state(
        app_state
    ).prepare_chat_completion(openai_data, giga_client)
    response_id = rquid_context.get()
    return StreamingResponse(
        stream_gemini_generate_content(
            request,
            normalized_model,
            chat_messages,
            response_id,
            giga_client,
            request_data=data,
        ),
        media_type="text/event-stream",
    )


@router.post(
    "/models/{model}:countTokens",
    openapi_extra=gemini_count_tokens_openapi_extra(),
)
@gemini_exceptions_handler
async def count_tokens(model: str, request: Request):
    """Gemini Developer API compatible countTokens endpoint."""
    data = await read_gemini_request_json(request)
    normalized_model = _ensure_route_model_matches_body(model, data.get("model"))
    count_payload = data.get("generateContentRequest") or data
    if not isinstance(count_payload, dict):
        raise GeminiAPIError(
            status_code=400,
            status="INVALID_ARGUMENT",
            message="`generateContentRequest` must be an object when provided.",
        )

    texts = extract_text_for_token_count(count_payload)
    if not texts:
        return {"totalTokens": 0}

    giga_client = get_gigachat_client(request)
    token_counts = await giga_client.atokens_count(texts, model=normalized_model)
    total_tokens = sum(token_count.tokens for token_count in token_counts)
    return {"totalTokens": total_tokens}


@router.post(
    "/models/{model}:batchEmbedContents",
    openapi_extra=gemini_batch_embed_contents_openapi_extra(),
)
@gemini_exceptions_handler
async def batch_embed_contents(model: str, request: Request):
    """Gemini Developer API compatible batch embeddings endpoint."""
    data = await read_gemini_request_json(request)
    requests_payload = data.get("requests")
    if not isinstance(requests_payload, list) or not requests_payload:
        raise GeminiAPIError(
            status_code=400,
            status="INVALID_ARGUMENT",
            message="`requests` must be a non-empty array.",
        )

    embeddings_service = get_embeddings_service_from_state(request.app.state)
    giga_client = get_gigachat_client(request)
    texts = extract_embed_texts(requests_payload, model)
    result = await embeddings_service.embed_texts(texts, giga_client=giga_client)
    return build_batch_embed_contents_response(result)


@router.post("/models/{model}:embedContent")
@gemini_exceptions_handler
async def embed_content(model: str, request: Request):
    """Gemini REST alias for single-item embeddings."""
    data = await read_gemini_request_json(request)
    content = data.get("content")
    if content is None and data.get("contents") is not None:
        contents = data.get("contents")
        if isinstance(contents, list) and len(contents) == 1:
            content = contents[0]
        else:
            content = (
                {"role": "user", "parts": contents}
                if isinstance(contents, list)
                else contents
            )
    if not isinstance(content, dict):
        raise GeminiAPIError(
            status_code=400,
            status="INVALID_ARGUMENT",
            message="`content` must be provided for `embedContent`.",
        )

    batch_like = {
        "requests": [{"model": model_resource_name(model), "content": content}]
    }
    embeddings_service = get_embeddings_service_from_state(request.app.state)
    giga_client = get_gigachat_client(request)
    texts = extract_embed_texts(batch_like["requests"], model)
    result = await embeddings_service.embed_texts(texts, giga_client=giga_client)
    return build_single_embed_content_response(result)
