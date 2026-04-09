"""Anthropic message endpoints."""

from typing import Dict, List

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from gpt2giga.api.anthropic.openapi import (
    anthropic_count_tokens_openapi_extra,
    anthropic_messages_openapi_extra,
)
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.request_json import read_request_json
from gpt2giga.core.logging.setup import rquid_context
from gpt2giga.protocol.anthropic.request import (
    _build_openai_data_from_anthropic_request,
    _convert_anthropic_messages_to_openai,
    _extract_text_from_openai_messages,
    _extract_tool_definitions_text,
)
from gpt2giga.protocol.anthropic.response import _build_anthropic_response
from gpt2giga.protocol.anthropic.streaming import _stream_anthropic_generator
from gpt2giga.providers.gigachat.client import get_gigachat_client

router = APIRouter(tags=["Anthropic"])


@router.post(
    "/messages/count_tokens", openapi_extra=anthropic_count_tokens_openapi_extra()
)
@exceptions_handler
async def count_tokens(request: Request):
    """Anthropic Messages count_tokens API compatible endpoint."""
    data = await read_request_json(request)
    giga_client = get_gigachat_client(request)
    model = data.get("model", "unknown")

    openai_messages = _convert_anthropic_messages_to_openai(
        data.get("system"), data.get("messages", [])
    )
    texts: List[str] = _extract_text_from_openai_messages(openai_messages)

    if "tools" in data and data["tools"]:
        texts.extend(_extract_tool_definitions_text(data["tools"]))

    if not texts:
        return {"input_tokens": 0}

    token_counts = await giga_client.atokens_count(texts, model=model)
    total_tokens = sum(token_count.tokens for token_count in token_counts)
    return {"input_tokens": total_tokens}


@router.post("/messages", openapi_extra=anthropic_messages_openapi_extra())
@exceptions_handler
async def messages(request: Request):
    """Anthropic Messages API compatible endpoint."""
    data = await read_request_json(request)
    stream = data.get("stream", False)
    current_rquid = rquid_context.get()
    state = request.app.state
    giga_client = get_gigachat_client(request)

    model = data.get("model", "unknown")
    openai_data: Dict = _build_openai_data_from_anthropic_request(data, state.logger)
    chat_messages = await state.request_transformer.prepare_chat_completion(
        openai_data, giga_client
    )

    if not stream:
        response = await giga_client.achat(chat_messages)
        giga_dict = response.model_dump()
        return _build_anthropic_response(giga_dict, model, current_rquid)

    return StreamingResponse(
        _stream_anthropic_generator(
            request, model, chat_messages, current_rquid, giga_client
        ),
        media_type="text/event-stream",
    )
