"""Streaming helpers for the responses feature."""

from __future__ import annotations

import asyncio
import time
import traceback
from typing import Any, AsyncGenerator, Optional

from gigachat import GigaChat
from gigachat.models import Chat, ChatV2
from starlette.requests import Request

from gpt2giga.app.dependencies import (
    get_logger_from_state,
    get_response_processor_from_state,
)
from gpt2giga.core.logging.setup import rquid_context
from gpt2giga.features.responses.store import get_response_store
from gpt2giga.providers.gigachat.client import get_gigachat_client
from gpt2giga.providers.gigachat.streaming import (
    GigaChatStreamError,
    ResponsesFunctionCallUpdate,
    ResponsesTextUpdate,
    ResponsesToolUpdate,
    iter_chat_stream_chunks,
    iter_responses_stream_chunks,
)


async def _stream_responses_generator_v1(
    request: Request,
    chat_messages: Chat | Any,
    *,
    response_id: str,
    giga_client: Optional[GigaChat],
    request_data: Optional[dict],
    response_processor: Any,
) -> AsyncGenerator[str, None]:
    """Stream legacy Responses API events over the v1 backend path."""
    from gpt2giga.api.openai.streaming import format_responses_stream_event

    logger = None
    rquid = rquid_context.get()
    processor = response_processor
    model = request_data.get("model", "unknown") if request_data else "unknown"
    usage: Optional[dict] = None
    finish_reason: Optional[str] = None
    sequence_number = 0
    text_item: dict[str, Any] | None = None
    text_value = ""
    function_item: dict[str, Any] | None = None
    function_arguments = ""
    function_name: str | None = None
    response_text = processor._build_response_text_config(request_data)

    def emit(event_type: str, payload: dict) -> str:
        nonlocal sequence_number
        body = dict(payload)
        body["type"] = event_type
        body["sequence_number"] = sequence_number
        sequence_number += 1
        return format_responses_stream_event(event_type, body)

    def current_response(status: str) -> dict:
        _, details = processor._build_response_status(finish_reason)
        result = processor._build_responses_api_result(
            request_data=request_data,
            gpt_model=model,
            response_id=response_id,
            output=output_items(),
            usage=usage,
            response_text=response_text,
        )
        result["status"] = status
        result["incomplete_details"] = details if status == "incomplete" else None
        return result

    def output_items() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if text_item is not None:
            items.append(text_item)
        if function_item is not None:
            items.append(function_item)
        return items

    try:
        if giga_client is None:
            giga_client = get_gigachat_client(request)
        logger = get_logger_from_state(request.app.state)

        yield emit("response.created", {"response": current_response("in_progress")})
        yield emit(
            "response.in_progress",
            {"response": current_response("in_progress")},
        )

        async for chunk in iter_chat_stream_chunks(giga_client, chat_messages):
            if await request.is_disconnected():
                if logger:
                    logger.info(f"[{rquid}] Client disconnected during streaming")
                break

            chunk_dict = processor._safe_model_dump(chunk)
            choice = (chunk_dict.get("choices") or [{}])[0]
            finish_reason = choice.get("finish_reason") or finish_reason
            chunk_model = chunk_dict.get("model")
            if isinstance(chunk_model, str) and chunk_model:
                model = chunk_model
            if chunk_dict.get("usage") is not None:
                usage = processor._build_response_usage(chunk_dict.get("usage"))

            processed = processor.process_stream_chunk_response(
                chunk,
                response_id=response_id,
            )
            event_type = processed.get("type") if isinstance(processed, dict) else None
            if event_type == "response.output_text.delta":
                if text_item is None:
                    text_item = {
                        "id": processed["item_id"],
                        "type": "message",
                        "status": "in_progress",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "",
                                "annotations": [],
                                "logprobs": [],
                            }
                        ],
                    }
                    yield emit(
                        "response.output_item.added",
                        {"output_index": 0, "item": text_item},
                    )
                    yield emit(
                        "response.content_part.added",
                        {
                            "item_id": text_item["id"],
                            "output_index": 0,
                            "content_index": 0,
                            "part": text_item["content"][0],
                        },
                    )
                delta = processed.get("delta", "")
                text_value += delta
                text_item["content"][0]["text"] = text_value
                yield emit(
                    "response.output_text.delta",
                    {
                        "item_id": text_item["id"],
                        "output_index": 0,
                        "content_index": 0,
                        "delta": delta,
                        "logprobs": [],
                    },
                )
                continue

            for output_index, item in enumerate(
                processed if isinstance(processed, list) else [processed],
                start=1 if text_item is not None else 0,
            ):
                if not isinstance(item, dict) or item.get("type") != "function_call":
                    continue
                if function_item is None:
                    function_item = dict(item)
                    function_item["status"] = "in_progress"
                    function_arguments = ""
                    function_name = function_item.get("name")
                    yield emit(
                        "response.output_item.added",
                        {"output_index": output_index, "item": function_item},
                    )

                new_arguments = item.get("arguments", "")
                if isinstance(new_arguments, str):
                    if new_arguments.startswith(function_arguments):
                        delta = new_arguments[len(function_arguments) :]
                    else:
                        delta = new_arguments
                    if delta:
                        function_arguments = (
                            f"{function_arguments}{delta}"
                            if new_arguments.startswith(function_arguments)
                            else new_arguments
                        )
                        function_item["arguments"] = function_arguments
                        yield emit(
                            "response.function_call_arguments.delta",
                            {
                                "item_id": function_item["id"],
                                "output_index": output_index,
                                "delta": delta,
                            },
                        )

        response_status, incomplete_details = processor._build_response_status(
            finish_reason
        )
        final_item_status = processor._build_output_item_status(response_status)

        if text_item is not None:
            text_item["status"] = final_item_status
            yield emit(
                "response.output_text.done",
                {
                    "item_id": text_item["id"],
                    "output_index": 0,
                    "content_index": 0,
                    "text": text_value,
                    "logprobs": [],
                },
            )
            yield emit(
                "response.content_part.done",
                {
                    "item_id": text_item["id"],
                    "output_index": 0,
                    "content_index": 0,
                    "part": text_item["content"][0],
                },
            )
            yield emit(
                "response.output_item.done",
                {"output_index": 0, "item": text_item},
            )

        if function_item is not None:
            function_item["status"] = final_item_status
            yield emit(
                "response.function_call_arguments.done",
                {
                    "item_id": function_item["id"],
                    "output_index": 1 if text_item is not None else 0,
                    "name": function_name,
                    "arguments": function_arguments,
                },
            )
            yield emit(
                "response.output_item.done",
                {
                    "output_index": 1 if text_item is not None else 0,
                    "item": function_item,
                },
            )

        final_response = current_response(response_status)
        final_response["incomplete_details"] = (
            incomplete_details if response_status == "incomplete" else None
        )
        if response_status == "incomplete":
            yield emit("response.incomplete", {"response": final_response})
        else:
            yield emit("response.completed", {"response": final_response})

    except GigaChatStreamError as exc:
        if logger:
            logger.error(
                f"[{rquid}] GigaChat streaming error: {exc.error_type}: {exc.message}"
            )
        yield emit(
            "error",
            {
                "code": "stream_error",
                "message": exc.message,
                "param": None,
            },
        )

    except asyncio.CancelledError:
        raise

    except Exception as exc:
        error_type = type(exc).__name__
        tb = traceback.format_exc()
        if logger:
            logger.error(
                f"[{rquid}] Unexpected streaming error: {error_type}: {exc}\n{tb}"
            )
        yield emit(
            "error",
            {
                "code": "internal_error",
                "message": "Stream interrupted",
                "param": None,
            },
        )


async def stream_responses_generator(
    request: Request,
    chat_messages: ChatV2 | Chat | Any,
    response_id: str,
    giga_client: Optional[GigaChat] = None,
    request_data: Optional[dict] = None,
    response_store: Optional[dict] = None,
    response_processor: Any = None,
    api_mode: str = "v2",
) -> AsyncGenerator[str, None]:
    """Stream Responses API events as SSE lines."""
    from gpt2giga.api.openai.streaming import format_responses_stream_event

    logger = None
    rquid = rquid_context.get()
    processor = response_processor or get_response_processor_from_state(
        request.app.state
    )
    response_store = (
        response_store if response_store is not None else get_response_store(request)
    )

    if api_mode == "v1":
        async for line in _stream_responses_generator_v1(
            request,
            chat_messages,
            response_id=response_id,
            giga_client=giga_client,
            request_data=request_data,
            response_processor=processor,
        ):
            yield line
        return

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
    tool_states: dict[str, dict[str, Any]] = {}

    def emit(event_type: str, payload: dict) -> str:
        nonlocal sequence_number
        body = dict(payload)
        body["type"] = event_type
        body["sequence_number"] = sequence_number
        sequence_number += 1
        return format_responses_stream_event(event_type, body)

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
        call_key: str,
        *,
        item_id: str,
        call_id: str,
        name: str | None,
    ) -> Optional[dict[str, Any]]:
        state = function_states.get(call_key)
        if state is not None:
            if name:
                state["name"] = name
                state["item"]["name"] = name
            return state
        if not name:
            return None

        item = {
            "id": item_id,
            "type": "function_call",
            "status": "in_progress",
            "call_id": call_id,
            "name": name,
            "arguments": "",
        }
        output_index, item = add_output_item("function_call", call_key, item)
        state = {
            "item": item,
            "item_id": item_id,
            "output_index": output_index,
            "call_id": call_id,
            "name": name,
            "arguments": "",
            "added": False,
        }
        function_states[call_key] = state
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
        output_item: dict[str, Any],
        raw_status: Optional[str],
    ) -> dict[str, Any]:
        state = tool_states.get(tool_key)
        if state is not None:
            state["item"].update(output_item)
            if raw_status is not None:
                state["raw_status"] = raw_status
            return state

        item = dict(output_item)
        output_index, item = add_output_item("tool", tool_key, item)
        state = {
            "item": item,
            "item_id": item_id,
            "output_index": output_index,
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
        logger = get_logger_from_state(request.app.state)

        yield emit("response.created", {"response": current_response("in_progress")})
        yield emit(
            "response.in_progress",
            {"response": current_response("in_progress")},
        )

        async for chunk in iter_responses_stream_chunks(
            giga_client,
            chat_messages,
            response_processor=processor,
            response_id=response_id,
        ):
            if await request.is_disconnected():
                if logger:
                    logger.info(f"[{rquid}] Client disconnected during streaming")
                break

            model = chunk.model or model
            created_at = chunk.created_at or created_at
            thread_id = chunk.thread_id or thread_id
            finish_reason = chunk.finish_reason or finish_reason
            if chunk.usage is not None:
                usage = chunk.usage

            for update in chunk.updates:
                if isinstance(update, ResponsesTextUpdate):
                    state = ensure_text_state(update.message_key, update.item_id)
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

                    state["text"] += update.text
                    state["item"]["content"][0]["text"] = state["text"]
                    yield emit(
                        "response.output_text.delta",
                        {
                            "item_id": state["item_id"],
                            "output_index": state["output_index"],
                            "content_index": 0,
                            "delta": update.text,
                            "logprobs": [],
                        },
                    )
                    continue

                if isinstance(update, ResponsesFunctionCallUpdate):
                    state = ensure_function_state(
                        update.call_key,
                        item_id=update.item_id,
                        call_id=update.call_id,
                        name=update.name,
                    )
                    if state is None:
                        continue
                    if not state["added"]:
                        yield emit(
                            "response.output_item.added",
                            {
                                "output_index": state["output_index"],
                                "item": state["item"],
                            },
                        )
                        state["added"] = True
                    if update.arguments:
                        state["arguments"] += update.arguments
                        state["item"]["arguments"] = state["arguments"]
                        yield emit(
                            "response.function_call_arguments.delta",
                            {
                                "item_id": state["item_id"],
                                "output_index": state["output_index"],
                                "delta": update.arguments,
                            },
                        )
                    continue

                if isinstance(update, ResponsesToolUpdate):
                    state = ensure_tool_state(
                        update.tool_key,
                        item_id=update.item_id,
                        output_item=update.output_item,
                        raw_status=update.raw_status,
                    )
                    if not state["added"]:
                        yield emit(
                            "response.output_item.added",
                            {
                                "output_index": state["output_index"],
                                "item": state["item"],
                            },
                        )
                        state["added"] = True
                    for event in emit_tool_progress(state):
                        yield event

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

    except GigaChatStreamError as exc:
        if logger:
            logger.error(
                f"[{rquid}] GigaChat streaming error: {exc.error_type}: {exc.message}"
            )
        yield emit(
            "error",
            {
                "code": "stream_error",
                "message": exc.message,
                "param": None,
            },
        )

    except asyncio.CancelledError:
        raise

    except Exception as exc:
        error_type = type(exc).__name__
        tb = traceback.format_exc()
        if logger:
            logger.error(
                f"[{rquid}] Unexpected streaming error: {error_type}: {exc}\n{tb}"
            )
        yield emit(
            "error",
            {
                "code": "internal_error",
                "message": "Stream interrupted",
                "param": None,
            },
        )
