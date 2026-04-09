import asyncio
import json
import traceback
from typing import Any, AsyncGenerator, Optional

import gigachat
from gigachat import GigaChat
from gigachat.models import Chat, ChatV2
from starlette.requests import Request

from gpt2giga.app_state import get_response_store
from gpt2giga.common.tools import map_tool_name_from_gigachat
from gpt2giga.core.logging.setup import rquid_context
from gpt2giga.providers.gigachat.client import get_gigachat_client


async def stream_chat_completion_generator(
    request: Request,
    model: str,
    chat_messages: Chat,
    response_id: str,
    giga_client: Optional[GigaChat] = None,
) -> AsyncGenerator[str, None]:
    logger = None
    rquid = rquid_context.get()

    try:
        if giga_client is None:
            giga_client = get_gigachat_client(request)
        logger = getattr(request.app.state, "logger", None)

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
        raise

    except Exception as e:
        error_type = type(e).__name__
        tb = traceback.format_exc()
        if logger:
            logger.error(
                f"[{rquid}] Unexpected streaming error: {error_type}: {e}\n{tb}"
            )
        error_response = {
            "error": {
                "message": "Stream interrupted",
                "type": error_type,
                "code": "internal_error",
            }
        }
        yield f"data: {json.dumps(error_response)}\n\n"
        yield "data: [DONE]\n\n"


async def stream_responses_generator(
    request: Request,
    chat_messages: ChatV2 | Chat | Any,
    response_id: str,
    giga_client: Optional[GigaChat] = None,
    request_data: Optional[dict] = None,
    response_store: Optional[dict] = None,
) -> AsyncGenerator[str, None]:
    import time

    logger = None
    rquid = rquid_context.get()
    processor = request.app.state.response_processor
    response_store = (
        response_store if response_store is not None else get_response_store(request)
    )

    created_at = int(time.time())
    completed_at: Optional[int] = None
    model = request_data.get("model", "unknown") if request_data else "unknown"
    thread_id: Optional[str] = None
    usage: Optional[dict] = None
    finish_reason: Optional[str] = None

    sequence_number = 0
    output_items: list[dict] = []
    output_meta: list[dict[str, str]] = []
    text_states: dict[str, dict[str, Any]] = {}
    function_states: dict[str, dict[str, Any]] = {}
    function_state_keys_by_call_id: dict[str, str] = {}
    tool_states: dict[str, dict[str, Any]] = {}

    def sse_event(event_type: str, data: dict) -> str:
        return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def emit(event_type: str, payload: dict) -> str:
        nonlocal sequence_number
        payload = dict(payload)
        payload["type"] = event_type
        payload["sequence_number"] = sequence_number
        sequence_number += 1
        return sse_event(event_type, payload)

    def current_response(status: str) -> dict:
        return processor.build_response_api_result_v2(
            request_data=request_data,
            gpt_model=model,
            response_id=response_id,
            output=output_items,
            usage=usage,
            created_at=created_at,
            completed_at=completed_at,
            status=status,
            incomplete_details=incomplete_details(status),
            thread_id=thread_id,
        )

    def incomplete_details(status: str) -> Optional[dict]:
        _, details = processor._build_response_status(finish_reason)
        if status == "incomplete":
            return details
        return None

    def add_output_item(kind: str, key: str, item: dict) -> tuple[int, dict]:
        output_index = len(output_items)
        output_items.append(item)
        output_meta.append({"kind": kind, "key": key})
        return output_index, item

    def ensure_text_state(message_key: str, item_id: str) -> dict[str, Any]:
        state = text_states.get(message_key)
        if state is not None:
            return state
        item = {
            "id": item_id,
            "type": "message",
            "status": "in_progress",
            "role": "assistant",
            "content": [],
        }
        output_index, item = add_output_item("message", message_key, item)
        state = {
            "item": item,
            "item_id": item_id,
            "output_index": output_index,
            "text": "",
            "part_added": False,
        }
        text_states[message_key] = state
        return state

    def ensure_function_state(
        call_key: str, item_id: str, call_id: str, name: str
    ) -> dict[str, Any]:
        state = function_states.get(call_key)
        if state is not None:
            return state
        mapped_name = map_tool_name_from_gigachat(name)
        item = {
            "id": item_id,
            "type": "function_call",
            "status": "in_progress",
            "call_id": call_id,
            "name": mapped_name,
            "arguments": "",
        }
        output_index, item = add_output_item("function_call", call_key, item)
        state = {
            "item": item,
            "item_id": item_id,
            "output_index": output_index,
            "call_id": call_id,
            "name": mapped_name,
            "arguments": "",
            "added": False,
        }
        function_states[call_key] = state
        function_state_keys_by_call_id[call_id] = call_key
        return state

    def tool_event_type(tool_item: dict, status: str) -> Optional[str]:
        item_type = tool_item.get("type")
        if item_type == "web_search_call":
            if status in {"in_progress", "searching", "completed"}:
                return f"response.web_search_call.{status}"
        if item_type == "code_interpreter_call":
            if status in {"in_progress", "interpreting", "completed"}:
                return f"response.code_interpreter_call.{status}"
        if item_type == "image_generation_call":
            if status in {"in_progress", "generating", "completed"}:
                return f"response.image_generation_call.{status}"
        return None

    def ensure_tool_state(
        tool_key: str,
        *,
        item_id: str,
        tool_name: str,
        raw_status: Optional[str],
        tools_state_id: Optional[str],
    ) -> Optional[dict[str, Any]]:
        state = tool_states.get(tool_key)
        if state is not None:
            if raw_status:
                state["raw_status"] = raw_status
            return state

        item = processor._build_builtin_tool_output_item(
            tool_name=tool_name,
            item_id=item_id,
            tools_state_id=tools_state_id,
            response_status="in_progress",
            raw_status=raw_status,
        )
        if item is None:
            return None

        output_index, item = add_output_item("tool", tool_key, item)
        state = {
            "item": item,
            "item_id": item_id,
            "output_index": output_index,
            "tool_name": tool_name,
            "tools_state_id": tools_state_id,
            "raw_status": raw_status,
            "last_emitted_status": None,
            "added": False,
        }
        tool_states[tool_key] = state
        return state

    def emit_tool_progress(state: dict[str, Any]) -> list[str]:
        status = state["item"].get("status")
        if not isinstance(status, str):
            return []
        if state.get("last_emitted_status") == status:
            return []
        event_type = tool_event_type(state["item"], status)
        if event_type is None:
            return []
        state["last_emitted_status"] = status
        return [
            emit(
                event_type,
                {
                    "item_id": state["item_id"],
                    "output_index": state["output_index"],
                },
            )
        ]

    try:
        if giga_client is None:
            giga_client = get_gigachat_client(request)
        logger = getattr(request.app.state, "logger", None)

        yield emit("response.created", {"response": current_response("in_progress")})
        yield emit(
            "response.in_progress",
            {"response": current_response("in_progress")},
        )

        async for chunk in giga_client.astream_v2(chat_messages):
            if await request.is_disconnected():
                if logger:
                    logger.info(f"[{rquid}] Client disconnected during streaming")
                break

            chunk_dict = processor._safe_model_dump(chunk)
            model = chunk_dict.get("model") or model
            created_at = chunk_dict.get("created_at", created_at)
            thread_id = chunk_dict.get("thread_id") or thread_id
            finish_reason = chunk_dict.get("finish_reason") or finish_reason

            usage_chunk = processor._build_response_usage_v2(chunk_dict.get("usage"))
            if usage_chunk is not None:
                usage = usage_chunk

            additional_data = chunk_dict.get("additional_data")
            for message_index, message in enumerate(chunk_dict.get("messages") or []):
                if not isinstance(message, dict):
                    continue
                message_id = (
                    message.get("message_id") or f"msg_{response_id}_{message_index}"
                )
                tools_state_id = message.get("tools_state_id")
                message_key = str(message_id)
                last_tool_state: Optional[dict[str, Any]] = None

                for part_index, part in enumerate(message.get("content") or []):
                    if not isinstance(part, dict):
                        continue

                    text = part.get("text")
                    if isinstance(text, str):
                        state = ensure_text_state(message_key, message_id)
                        if state["item"]["content"] == []:
                            yield emit(
                                "response.output_item.added",
                                {
                                    "output_index": state["output_index"],
                                    "item": state["item"],
                                },
                            )
                        if not state["part_added"]:
                            state["item"]["content"] = [
                                {
                                    "type": "output_text",
                                    "text": "",
                                    "annotations": [],
                                }
                            ]
                            yield emit(
                                "response.content_part.added",
                                {
                                    "item_id": state["item_id"],
                                    "output_index": state["output_index"],
                                    "content_index": 0,
                                    "part": state["item"]["content"][0],
                                },
                            )
                            state["part_added"] = True

                        state["text"] += text
                        state["item"]["content"][0]["text"] = state["text"]
                        yield emit(
                            "response.output_text.delta",
                            {
                                "item_id": state["item_id"],
                                "output_index": state["output_index"],
                                "content_index": 0,
                                "delta": text,
                                "logprobs": [],
                            },
                        )

                    function_call = part.get("function_call")
                    if isinstance(function_call, dict):
                        call_id = (
                            str(tools_state_id)
                            if tools_state_id is not None
                            else f"call_{message_id}_{part_index}"
                        )
                        name = function_call.get("name")
                        if isinstance(name, str) and name:
                            item_id = f"fc_{call_id}"
                            state = ensure_function_state(
                                f"{call_id}:{name}",
                                item_id,
                                call_id,
                                name,
                            )
                        else:
                            state_key = function_state_keys_by_call_id.get(call_id)
                            state = (
                                function_states.get(state_key)
                                if state_key is not None
                                else None
                            )

                        if state is not None:
                            if not state["added"]:
                                yield emit(
                                    "response.output_item.added",
                                    {
                                        "output_index": state["output_index"],
                                        "item": state["item"],
                                    },
                                )
                                state["added"] = True

                            arguments = processor._stringify_json(
                                function_call.get("arguments")
                            )
                            if arguments:
                                state["arguments"] += arguments
                                state["item"]["arguments"] = state["arguments"]
                                yield emit(
                                    "response.function_call_arguments.delta",
                                    {
                                        "item_id": state["item_id"],
                                        "output_index": state["output_index"],
                                        "delta": arguments,
                                    },
                                )

                    tool_execution = part.get("tool_execution")
                    if isinstance(tool_execution, dict):
                        tool_name = tool_execution.get("name")
                        if isinstance(tool_name, str) and tool_name:
                            item_id = (
                                f"tool_{tools_state_id or message_id}_{part_index}"
                            )
                            state = ensure_tool_state(
                                f"{tools_state_id or message_id}:{tool_name}",
                                item_id=item_id,
                                tool_name=tool_name,
                                raw_status=tool_execution.get("status"),
                                tools_state_id=tools_state_id,
                            )
                            if state is not None:
                                if not state["added"]:
                                    yield emit(
                                        "response.output_item.added",
                                        {
                                            "output_index": state["output_index"],
                                            "item": state["item"],
                                        },
                                    )
                                    state["added"] = True
                                updated_item = (
                                    processor._build_builtin_tool_output_item(
                                        tool_name=tool_name,
                                        item_id=state["item_id"],
                                        tools_state_id=tools_state_id,
                                        response_status="in_progress",
                                        raw_status=tool_execution.get("status"),
                                        additional_data=additional_data,
                                    )
                                )
                                if updated_item is not None:
                                    state["item"].update(updated_item)
                                last_tool_state = state
                                for event in emit_tool_progress(state):
                                    yield event

                    files = part.get("files")
                    if isinstance(files, list) and last_tool_state is not None:
                        updated_item = processor._build_builtin_tool_output_item(
                            tool_name=last_tool_state["tool_name"],
                            item_id=last_tool_state["item_id"],
                            tools_state_id=last_tool_state["tools_state_id"],
                            response_status="in_progress",
                            raw_status=last_tool_state["raw_status"],
                            related_files=files,
                            additional_data=additional_data,
                        )
                        if updated_item is not None:
                            last_tool_state["item"].update(updated_item)

        completed_at = int(time.time())
        response_status, _ = processor._build_response_status(finish_reason)
        final_item_status = processor._build_output_item_status(response_status)

        for meta in output_meta:
            kind = meta["kind"]
            key = meta["key"]

            if kind == "message":
                state = text_states[key]
                state["item"]["status"] = final_item_status
                if not state["part_added"]:
                    state["item"]["content"] = [
                        {
                            "type": "output_text",
                            "text": "",
                            "annotations": [],
                        }
                    ]
                    yield emit(
                        "response.output_item.added",
                        {
                            "output_index": state["output_index"],
                            "item": state["item"],
                        },
                    )
                    yield emit(
                        "response.content_part.added",
                        {
                            "item_id": state["item_id"],
                            "output_index": state["output_index"],
                            "content_index": 0,
                            "part": state["item"]["content"][0],
                        },
                    )
                    state["part_added"] = True

                part = {
                    "type": "output_text",
                    "text": state["text"],
                    "annotations": [],
                }
                state["item"]["content"] = [part]
                yield emit(
                    "response.output_text.done",
                    {
                        "item_id": state["item_id"],
                        "output_index": state["output_index"],
                        "content_index": 0,
                        "text": state["text"],
                        "logprobs": [],
                    },
                )
                yield emit(
                    "response.content_part.done",
                    {
                        "item_id": state["item_id"],
                        "output_index": state["output_index"],
                        "content_index": 0,
                        "part": part,
                    },
                )
                yield emit(
                    "response.output_item.done",
                    {
                        "output_index": state["output_index"],
                        "item": state["item"],
                    },
                )
                continue

            if kind == "function_call":
                state = function_states[key]
                state["item"]["status"] = final_item_status
                yield emit(
                    "response.function_call_arguments.done",
                    {
                        "item_id": state["item_id"],
                        "output_index": state["output_index"],
                        "name": state["name"],
                        "arguments": state["arguments"],
                    },
                )
                yield emit(
                    "response.output_item.done",
                    {
                        "output_index": state["output_index"],
                        "item": state["item"],
                    },
                )
                continue

            state = tool_states[key]
            item = state["item"]
            if item.get("status") not in {"completed", "failed"}:
                item["status"] = (
                    "completed" if response_status == "completed" else final_item_status
                )
            for event in emit_tool_progress(state):
                yield event
            yield emit(
                "response.output_item.done",
                {
                    "output_index": state["output_index"],
                    "item": item,
                },
            )

        final_response = current_response(response_status)
        processor.store_response_metadata(response_store, final_response)
        if response_status == "incomplete":
            yield emit("response.incomplete", {"response": final_response})
        else:
            yield emit("response.completed", {"response": final_response})

    except gigachat.exceptions.GigaChatException as e:
        error_type = type(e).__name__
        error_message = str(e)
        if logger:
            logger.error(
                f"[{rquid}] GigaChat streaming error: {error_type}: {error_message}"
            )
        yield emit(
            "error",
            {
                "code": "stream_error",
                "message": error_message,
                "param": None,
            },
        )

    except asyncio.CancelledError:
        raise

    except Exception as e:
        error_type = type(e).__name__
        tb = traceback.format_exc()
        if logger:
            logger.error(
                f"[{rquid}] Unexpected streaming error: {error_type}: {e}\n{tb}"
            )
        yield emit(
            "error",
            {
                "code": "internal_error",
                "message": "Stream interrupted",
                "param": None,
            },
        )
