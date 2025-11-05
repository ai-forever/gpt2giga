import json
from functools import wraps
from typing import AsyncGenerator

import gigachat
from fastapi import HTTPException
from gigachat.models import Chat
from starlette.requests import Request
from aioitertools import enumerate as aio_enumerate

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


async def stream_chat_completion_generator(request: Request, chat_messages: Chat) -> AsyncGenerator[str, None]:
    try:
        async for chunk in request.app.state.gigachat_client.astream(
                chat_messages
        ):
            if await request.is_disconnected():
                break
            processed = (
                request.app.state.response_processor.process_stream_chunk(
                    chunk, chat_messages.model
                )
            )
            yield f"data: {json.dumps(processed)}\n\n"

    except GeneratorExit:
        pass
    except Exception as e:
        yield f"data: {json.dumps({'error': 'Stream interrupted'})}\n\n"
        yield "data: [DONE]\n\n"

async def stream_responses_generator(request: Request, chat_messages: Chat) -> AsyncGenerator[str, None]:
    try:
        async for i, chunk in aio_enumerate(
                request.app.state.gigachat_client.astream(chat_messages)
        ):
            if await request.is_disconnected():
                break
            processed = request.app.state.response_processor.process_stream_chunk_response(
                chunk, sequence_number=i, response_id=request.app.state.rquid
            )
            yield f"data: {json.dumps(processed)}\n\n"

    except GeneratorExit:
        pass
    except Exception as e:
        yield f"data: {json.dumps({'error': 'Stream interrupted'})}\n\n"
        yield "data: [DONE]\n\n"
