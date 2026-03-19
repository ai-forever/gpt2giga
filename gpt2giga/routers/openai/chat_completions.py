"""OpenAI chat completions endpoint."""

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from gpt2giga.app_state import get_gigachat_client, get_tool_call_store
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.request_json import read_request_json
from gpt2giga.common.streaming import stream_chat_completion_generator
from gpt2giga.common.tool_call_history import (
    mark_tool_call_results,
    normalize_tool_call,
    store_tool_call_session,
)
from gpt2giga.logger import rquid_context
from gpt2giga.openapi_specs.openai import chat_completions_openapi_extra
from gpt2giga.routers.openai.helpers import populate_giga_functions

router = APIRouter(tags=["OpenAI"])


@router.post("/chat/completions", openapi_extra=chat_completions_openapi_extra())
@exceptions_handler
async def chat_completions(request: Request):
    """Create a chat completion."""
    data = await read_request_json(request)
    stream = data.get("stream", False)
    current_rquid = rquid_context.get()
    state = request.app.state
    giga_client = get_gigachat_client(request)
    tool_call_store = get_tool_call_store(request)

    completed_tool_call_ids = [
        message.get("tool_call_id")
        for message in data.get("messages", [])
        if message.get("role") == "tool" and message.get("tool_call_id")
    ]
    if completed_tool_call_ids:
        mark_tool_call_results(tool_call_store, data.get("previous_response_id"), completed_tool_call_ids)

    populate_giga_functions(data, getattr(state, "logger", None))
    chat_messages = await state.request_transformer.prepare_chat_completion(
        data, giga_client
    )
    if not stream:
        response = await giga_client.achat(chat_messages)
        result = state.response_processor.process_response(
            response, data["model"], current_rquid, request_data=data
        )
        tool_calls = [
            normalize_tool_call(tool_call)
            for tool_call in result.get("choices", [{}])[0]
            .get("message", {})
            .get("tool_calls", [])
        ]
        store_tool_call_session(
            tool_call_store,
            result.get("id"),
            api_type="chat.completions",
            request_data=data,
            tool_calls=tool_calls,
        )
        return result

    return StreamingResponse(
        stream_chat_completion_generator(
            request, data["model"], chat_messages, current_rquid, giga_client
        ),
        media_type="text/event-stream",
    )
