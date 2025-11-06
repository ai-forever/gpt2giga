import json
from functools import wraps
from typing import AsyncGenerator

import gigachat
from aioitertools import enumerate as aio_enumerate
from fastapi import HTTPException
from gigachat.models import Chat, Function, FunctionParameters
from starlette.requests import Request


def exceptions_handler(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except gigachat.exceptions.ResponseError as e:
            if len(e.args) == 4:
                url, status_code, message, _ = e.args
                try:
                    error_detail = json.loads(message)
                except Exception:
                    error_detail = message
                raise HTTPException(
                    status_code=status_code,
                    detail={
                        "url": str(url),
                        "error": error_detail,
                    },
                )
            else:
                raise HTTPException(
                    status_code=500,
                    detail={
                        "error": "Unexpected ResponseError structure",
                        "args": e.args,
                    },
                )

    return wrapper


async def stream_chat_completion_generator(
    request: Request, chat_messages: Chat, current_rquid: str
) -> AsyncGenerator[str, None]:
    try:
        async for chunk in request.app.state.gigachat_client.astream(chat_messages):
            if await request.is_disconnected():
                break
            processed = request.app.state.response_processor.process_stream_chunk(
                chunk, chat_messages.model, current_rquid
            )
            yield f"data: {json.dumps(processed)}\n\n"

    except Exception:
        yield f"data: {json.dumps({'error': 'Stream interrupted'})}\n\n"
        yield "data: [DONE]\n\n"


async def stream_responses_generator(
    request: Request, chat_messages: Chat, current_rquid: str
) -> AsyncGenerator[str, None]:
    try:
        async for i, chunk in aio_enumerate(
            request.app.state.gigachat_client.astream(chat_messages)
        ):
            if await request.is_disconnected():
                break
            processed = (
                request.app.state.response_processor.process_stream_chunk_response(
                    chunk, sequence_number=i, response_id=current_rquid
                )
            )
            yield f"data: {json.dumps(processed)}\n\n"

    except Exception:
        yield f"data: {json.dumps({'error': 'Stream interrupted'})}\n\n"
        yield "data: [DONE]\n\n"


def convert_tool_to_giga_functions(data: dict):
    functions = []
    tools = data.get("tools", []) or data.get("functions", [])
    for tool in tools:
        if tool.get("function"):
            function = tool["function"]
            giga_function = Function(
                name=function["name"],
                description=function["description"],
                parameters=FunctionParameters(**function["parameters"]),
            )
        else:
            giga_function = Function(
                name=tool["name"],
                description=tool["description"],
                parameters=FunctionParameters(**tool["parameters"]),
            )
        functions.append(giga_function)
    return functions
