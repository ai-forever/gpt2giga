import asyncio
import json
import traceback
from typing import AsyncGenerator, Optional

import gigachat
from aioitertools import enumerate as aio_enumerate
from gigachat import GigaChat
from gigachat.models import Chat
from starlette.requests import Request

from gpt2giga.common.tools import map_tool_name_from_gigachat
from gpt2giga.logger import rquid_context


async def stream_chat_completion_generator(
    request: Request,
    model: str,
    chat_messages: Chat,
    response_id: str,
    giga_client: Optional[GigaChat] = None,
) -> AsyncGenerator[str, None]:
    if not giga_client:
        giga_client = request.app.state.gigachat_client
    logger = getattr(request.app.state, "logger", None)
    rquid = rquid_context.get()

    try:
        async for chunk in giga_client.astream(chat_messages):
            if await request.is_disconnected():
                if logger:
                    logger.info(f"[{rquid}] Client disconnected during streaming")
                break
            processed = request.app.state.response_processor.process_stream_chunk(
                chunk, model, response_id
            )
            yield f"data: {json.dumps(processed)}\n\n"

        yield "data: [DONE]\n\n"

    except gigachat.exceptions.GigaChatException as e:
        error_type = type(e).__name__
        error_message = str(e)
        if logger:
            logger.error(
                f"[{rquid}] GigaChat streaming error: {error_type}: {error_message}"
            )
        error_response = {
            "error": {
                "message": error_message,
                "type": error_type,
                "code": "stream_error",
            }
        }
        yield f"data: {json.dumps(error_response)}\n\n"
        yield "data: [DONE]\n\n"

    except asyncio.CancelledError:
        # Preserve cooperative cancellation for graceful server shutdown.
        raise

    except Exception as e:
        error_type = type(e).__name__
        error_message = str(e)
        tb = traceback.format_exc()
        if logger:
            logger.error(
                f"[{rquid}] Unexpected streaming error: {error_type}: {error_message}\n{tb}"
            )
        error_response = {
            "error": {
                "message": f"Stream interrupted: {error_message}",
                "type": error_type,
                "code": "internal_error",
            }
        }
        yield f"data: {json.dumps(error_response)}\n\n"
        yield "data: [DONE]\n\n"


async def stream_responses_generator(
    request: Request,
    chat_messages: Chat,
    response_id: str,
    giga_client: Optional[GigaChat] = None,
    request_data: Optional[dict] = None,
) -> AsyncGenerator[str, None]:
    if not giga_client:
        giga_client = request.app.state.gigachat_client
    logger = getattr(request.app.state, "logger", None)
    rquid = rquid_context.get()
    import time

    created_at = int(time.time())
    model = request_data.get("model", "unknown") if request_data else "unknown"
    msg_id = f"msg_{response_id}"
    fc_id = f"fc_{response_id}"  # ID for function call item

    def sse_event(event_type: str, data: dict) -> str:
        return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

    def build_response_obj(status: str, output: list = None, usage: dict = None):
        return {
            "id": f"resp_{response_id}",
            "object": "response",
            "created_at": created_at,
            "status": status,
            "error": None,
            "incomplete_details": None,
            "instructions": request_data.get("instructions") if request_data else None,
            "max_output_tokens": (
                request_data.get("max_output_tokens") if request_data else None
            ),
            "model": model,
            "output": output or [],
            "parallel_tool_calls": True,
            "previous_response_id": None,
            "reasoning": {"effort": None, "summary": None},
            "store": True,
            "temperature": request_data.get("temperature", 1) if request_data else 1,
            "text": {"format": {"type": "text"}},
            "tool_choice": "auto",
            "tools": [],
            "top_p": request_data.get("top_p", 1) if request_data else 1,
            "truncation": "disabled",
            "usage": usage,
            "user": None,
            "metadata": {},
        }

    sequence_number = 0

    try:
        yield sse_event(
            "response.created",
            {
                "type": "response.created",
                "response": build_response_obj("in_progress"),
                "sequence_number": sequence_number,
            },
        )
        sequence_number += 1

        yield sse_event(
            "response.in_progress",
            {
                "type": "response.in_progress",
                "response": build_response_obj("in_progress"),
                "sequence_number": sequence_number,
            },
        )
        sequence_number += 1

        full_text = ""
        function_call_data = None  # {"name": ..., "arguments": ...}
        functions_state_id = None
        output_item_added = False
        is_function_call = False

        async for _i, chunk in aio_enumerate(giga_client.astream(chat_messages)):
            if await request.is_disconnected():
                if logger:
                    logger.info(f"[{rquid}] Client disconnected during streaming")
                break

            giga_dict = chunk.model_dump()
            choice = giga_dict["choices"][0]
            delta = choice.get("delta", {})
            delta_content = delta.get("content", "")
            delta_function_call = delta.get("function_call")

            if delta_function_call:
                is_function_call = True
                if functions_state_id is None:
                    functions_state_id = delta.get("functions_state_id")

                if function_call_data is None:
                    tool_name = map_tool_name_from_gigachat(
                        delta_function_call.get("name", "")
                    )
                    function_call_data = {
                        "name": tool_name,
                        "arguments": "",
                    }
                    yield sse_event(
                        "response.output_item.added",
                        {
                            "type": "response.output_item.added",
                            "output_index": 0,
                            "item": {
                                "id": fc_id,
                                "type": "function_call",
                                "status": "in_progress",
                                "call_id": f"call_{response_id}",
                                "name": function_call_data["name"],
                                "arguments": "",
                            },
                            "sequence_number": sequence_number,
                        },
                    )
                    sequence_number += 1
                    output_item_added = True

                if delta_function_call.get("name"):
                    function_call_data["name"] = map_tool_name_from_gigachat(
                        delta_function_call["name"]
                    )

                args = delta_function_call.get("arguments")
                if args is not None:
                    if isinstance(args, dict):
                        args_str = json.dumps(args, ensure_ascii=False)
                    else:
                        args_str = str(args)

                    if args_str:
                        yield sse_event(
                            "response.function_call_arguments.delta",
                            {
                                "type": "response.function_call_arguments.delta",
                                "item_id": fc_id,
                                "output_index": 0,
                                "delta": args_str,
                                "sequence_number": sequence_number,
                            },
                        )
                        sequence_number += 1
                        function_call_data["arguments"] += args_str

            elif delta_content:
                if not output_item_added:
                    yield sse_event(
                        "response.output_item.added",
                        {
                            "type": "response.output_item.added",
                            "output_index": 0,
                            "item": {
                                "id": msg_id,
                                "status": "in_progress",
                                "type": "message",
                                "role": "assistant",
                                "content": [],
                            },
                            "sequence_number": sequence_number,
                        },
                    )
                    sequence_number += 1

                    yield sse_event(
                        "response.content_part.added",
                        {
                            "type": "response.content_part.added",
                            "item_id": msg_id,
                            "output_index": 0,
                            "content_index": 0,
                            "part": {
                                "type": "output_text",
                                "text": "",
                                "annotations": [],
                            },
                            "sequence_number": sequence_number,
                        },
                    )
                    sequence_number += 1
                    output_item_added = True

                full_text += delta_content
                yield sse_event(
                    "response.output_text.delta",
                    {
                        "type": "response.output_text.delta",
                        "item_id": msg_id,
                        "output_index": 0,
                        "content_index": 0,
                        "delta": delta_content,
                        "sequence_number": sequence_number,
                    },
                )
                sequence_number += 1

        if is_function_call and function_call_data:
            yield sse_event(
                "response.function_call_arguments.done",
                {
                    "type": "response.function_call_arguments.done",
                    "item_id": fc_id,
                    "output_index": 0,
                    "name": function_call_data["name"],
                    "arguments": function_call_data["arguments"],
                    "sequence_number": sequence_number,
                },
            )
            sequence_number += 1

            yield sse_event(
                "response.output_item.done",
                {
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": {
                        "id": fc_id,
                        "type": "function_call",
                        "status": "completed",
                        "call_id": f"call_{response_id}",
                        "name": function_call_data["name"],
                        "arguments": function_call_data["arguments"],
                    },
                    "sequence_number": sequence_number,
                },
            )
            sequence_number += 1

            final_output = [
                {
                    "id": fc_id,
                    "type": "function_call",
                    "status": "completed",
                    "call_id": f"call_{response_id}",
                    "name": function_call_data["name"],
                    "arguments": function_call_data["arguments"],
                }
            ]
            yield sse_event(
                "response.completed",
                {
                    "type": "response.completed",
                    "response": build_response_obj("completed", output=final_output),
                    "sequence_number": sequence_number,
                },
            )
        else:
            if not output_item_added:
                yield sse_event(
                    "response.output_item.added",
                    {
                        "type": "response.output_item.added",
                        "output_index": 0,
                        "item": {
                            "id": msg_id,
                            "status": "in_progress",
                            "type": "message",
                            "role": "assistant",
                            "content": [],
                        },
                        "sequence_number": sequence_number,
                    },
                )
                sequence_number += 1

                yield sse_event(
                    "response.content_part.added",
                    {
                        "type": "response.content_part.added",
                        "item_id": msg_id,
                        "output_index": 0,
                        "content_index": 0,
                        "part": {
                            "type": "output_text",
                            "text": "",
                            "annotations": [],
                        },
                        "sequence_number": sequence_number,
                    },
                )
                sequence_number += 1

            yield sse_event(
                "response.output_text.done",
                {
                    "type": "response.output_text.done",
                    "item_id": msg_id,
                    "output_index": 0,
                    "content_index": 0,
                    "text": full_text,
                    "sequence_number": sequence_number,
                },
            )
            sequence_number += 1

            yield sse_event(
                "response.content_part.done",
                {
                    "type": "response.content_part.done",
                    "item_id": msg_id,
                    "output_index": 0,
                    "content_index": 0,
                    "part": {
                        "type": "output_text",
                        "text": full_text,
                        "annotations": [],
                    },
                    "sequence_number": sequence_number,
                },
            )
            sequence_number += 1

            yield sse_event(
                "response.output_item.done",
                {
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": {
                        "id": msg_id,
                        "status": "completed",
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": full_text,
                                "annotations": [],
                            }
                        ],
                    },
                    "sequence_number": sequence_number,
                },
            )
            sequence_number += 1

            final_output = [
                {
                    "id": msg_id,
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": full_text,
                            "annotations": [],
                        }
                    ],
                }
            ]
            yield sse_event(
                "response.completed",
                {
                    "type": "response.completed",
                    "response": build_response_obj("completed", output=final_output),
                    "sequence_number": sequence_number,
                },
            )

    except gigachat.exceptions.GigaChatException as e:
        error_type = type(e).__name__
        error_message = str(e)
        if logger:
            logger.error(
                f"[{rquid}] GigaChat streaming error: {error_type}: {error_message}"
            )
        error_response = {
            "type": "error",
            "code": "stream_error",
            "message": error_message,
            "param": None,
            "sequence_number": sequence_number,
        }
        yield sse_event("error", error_response)

    except asyncio.CancelledError:
        raise

    except Exception as e:
        error_type = type(e).__name__
        error_message = str(e)
        tb = traceback.format_exc()
        if logger:
            logger.error(
                f"[{rquid}] Unexpected streaming error: {error_type}: {error_message}\n{tb}"
            )
        error_response = {
            "type": "error",
            "code": "internal_error",
            "message": f"Stream interrupted: {error_message}",
            "param": None,
            "sequence_number": sequence_number,
        }
        yield sse_event("error", error_response)
