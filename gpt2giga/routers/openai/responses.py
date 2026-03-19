"""OpenAI responses endpoint."""

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from gpt2giga.app_state import get_gigachat_client, get_tool_call_store
from gpt2giga.common.tool_call_history import (
    mark_tool_call_results,
    normalize_tool_call,
    store_tool_call_session,
)
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.request_json import read_request_json
from gpt2giga.common.streaming import stream_responses_generator
from gpt2giga.logger import rquid_context
from gpt2giga.openapi_specs.openai import responses_openapi_extra
from gpt2giga.routers.openai.helpers import populate_giga_functions

router = APIRouter(tags=["OpenAI"])


@router.post("/responses", openapi_extra=responses_openapi_extra())
@exceptions_handler
async def responses(request: Request):
    """Create a Responses API response."""
    data = await read_request_json(request)
    stream = data.get("stream", False)
    current_rquid = rquid_context.get()
    state = request.app.state
    giga_client = get_gigachat_client(request)
    tool_call_store = get_tool_call_store(request)

    input_items = data.get("input", [])
    if not isinstance(input_items, list):
        input_items = []
    completed_call_ids = [
        item.get("call_id")
        for item in input_items
        if isinstance(item, dict)
        and item.get("type") == "function_call_output"
        and item.get("call_id")
    ]
    if completed_call_ids:
        mark_tool_call_results(
            tool_call_store,
            data.get("previous_response_id"),
            completed_call_ids,
        )

    populate_giga_functions(data, getattr(state, "logger", None))
    chat_messages = await state.request_transformer.prepare_response(data, giga_client)
    if not stream:
        response = await giga_client.achat(chat_messages)
        result = state.response_processor.process_response_api(
            data, response, data["model"], current_rquid
        )
        tool_calls = [
            normalize_tool_call(item)
            for item in result.get("output", [])
            if item.get("type") == "function_call"
        ]
        for tool_call, item in zip(
            tool_calls,
            [item for item in result.get("output", []) if item.get("type") == "function_call"],
        ):
            tool_call["id"] = item.get("call_id")
        store_tool_call_session(
            tool_call_store,
            result.get("id"),
            api_type="responses",
            request_data=data,
            tool_calls=tool_calls,
        )
        return result

    return StreamingResponse(
        stream_responses_generator(
            request, chat_messages, current_rquid, giga_client, request_data=data
        ),
        media_type="text/event-stream",
    )
