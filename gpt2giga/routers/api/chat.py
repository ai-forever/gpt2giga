"""Chat, embeddings, and responses endpoints."""

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.request_json import read_request_json
from gpt2giga.common.streaming import (
    stream_chat_completion_generator,
    stream_responses_generator,
)
from gpt2giga.common.tools import convert_tool_to_giga_functions
from gpt2giga.logger import rquid_context
from gpt2giga.openapi_specs import (
    chat_completions_openapi_extra,
    embeddings_openapi_extra,
    responses_openapi_extra,
)
from gpt2giga.protocol.batches import transform_embedding_body
from gpt2giga.routers.state import get_gigachat_client

router = APIRouter(tags=["API"])


@router.post("/chat/completions", openapi_extra=chat_completions_openapi_extra())
@exceptions_handler
async def chat_completions(request: Request):
    """Create a chat completion."""
    data = await read_request_json(request)
    stream = data.get("stream", False)
    uses_tools = "tools" in data or "functions" in data
    current_rquid = rquid_context.get()
    state = request.app.state
    giga_client = get_gigachat_client(request)
    if uses_tools:
        data["functions"] = convert_tool_to_giga_functions(data)
        state.logger.debug(f"Functions count: {len(data['functions'])}")
    chat_messages = await state.request_transformer.prepare_chat_completion(
        data, giga_client
    )
    if not stream:
        response = await giga_client.achat(chat_messages)
        return state.response_processor.process_response(
            response, data["model"], current_rquid, request_data=data
        )

    return StreamingResponse(
        stream_chat_completion_generator(
            request, data["model"], chat_messages, current_rquid, giga_client
        ),
        media_type="text/event-stream",
    )


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


@router.post("/responses", openapi_extra=responses_openapi_extra())
@exceptions_handler
async def responses(request: Request):
    """Create a Responses API response."""
    data = await read_request_json(request)
    stream = data.get("stream", False)
    uses_tools = "tools" in data or "functions" in data
    current_rquid = rquid_context.get()
    state = request.app.state
    giga_client = get_gigachat_client(request)
    if uses_tools:
        data["functions"] = convert_tool_to_giga_functions(data)
        state.logger.debug(f"Functions count: {len(data['functions'])}")
    chat_messages = await state.request_transformer.prepare_response(data, giga_client)
    if not stream:
        response = await giga_client.achat(chat_messages)
        return state.response_processor.process_response_api(
            data, response, data["model"], current_rquid
        )

    return StreamingResponse(
        stream_responses_generator(
            request, chat_messages, current_rquid, giga_client, request_data=data
        ),
        media_type="text/event-stream",
    )
