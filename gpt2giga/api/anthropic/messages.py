"""Anthropic message endpoints."""

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from gpt2giga.api.anthropic.openapi import (
    anthropic_count_tokens_openapi_extra,
    anthropic_messages_openapi_extra,
)
from gpt2giga.api.anthropic.response import _build_anthropic_response
from gpt2giga.api.anthropic.streaming import _stream_anthropic_generator
from gpt2giga.api.tags import (
    PROVIDER_ANTHROPIC,
    TAG_CHAT,
    TAG_COUNT_TOKENS,
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
from gpt2giga.core.errors import exceptions_handler
from gpt2giga.core.http.json_body import read_request_json
from gpt2giga.core.logging.setup import rquid_context
from gpt2giga.features.chat.service import get_chat_service_from_state
from gpt2giga.providers.anthropic import anthropic_provider_adapters
from gpt2giga.providers.gigachat.client import get_gigachat_client

router = APIRouter()


@router.post(
    "/messages/count_tokens",
    openapi_extra=anthropic_count_tokens_openapi_extra(),
    tags=[provider_tag(TAG_COUNT_TOKENS, PROVIDER_ANTHROPIC)],
)
@exceptions_handler
async def count_tokens(request: Request):
    """Anthropic Messages count_tokens API compatible endpoint."""
    data = await read_request_json(request)
    giga_client = get_gigachat_client(request)
    model = data.get("model", "unknown")
    set_request_audit_model(request, model)
    texts = anthropic_provider_adapters.chat.build_token_count_texts(data)

    if not texts:
        return {"input_tokens": 0}

    token_counts = await giga_client.atokens_count(texts, model=model)
    total_tokens = sum(token_count.tokens for token_count in token_counts)
    return {"input_tokens": total_tokens}


@router.post(
    "/messages",
    openapi_extra=anthropic_messages_openapi_extra(),
    tags=[provider_tag(TAG_CHAT, PROVIDER_ANTHROPIC)],
)
@exceptions_handler
async def messages(request: Request):
    """Anthropic Messages API compatible endpoint."""
    data = await read_request_json(request)
    annotate_request_audit_request_payload(request, data)
    stream = data.get("stream", False)
    current_rquid = rquid_context.get()
    giga_client = get_gigachat_client(request)

    model = data.get("model", "unknown")
    set_request_audit_model(request, model)
    app_state = request.app.state
    chat_service = get_chat_service_from_state(app_state)
    api_mode = chat_service.backend_mode
    normalized_request = anthropic_provider_adapters.chat.build_normalized_request(
        data,
        logger=get_logger_from_state(app_state),
    )
    chat_messages = await chat_service.prepare_request(
        normalized_request,
        giga_client=giga_client,
    )

    if not stream:
        response = await chat_service.execute_prepared_request(
            chat_messages,
            giga_client=giga_client,
        )
        giga_dict = chat_service.normalize_provider_response(response)
        anthropic_response = _build_anthropic_response(giga_dict, model, current_rquid)
        annotate_request_audit_from_payload(
            request,
            anthropic_response,
            fallback_model=model,
        )
        return anthropic_response

    return StreamingResponse(
        _stream_anthropic_generator(
            request,
            model,
            chat_messages,
            current_rquid,
            giga_client,
            api_mode=api_mode,
            response_processor=chat_service.response_processor,
        ),
        media_type="text/event-stream",
    )
