"""Legacy v1 Responses streaming flow."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any, Optional

from gigachat import GigaChat
from gigachat.models import Chat
from starlette.requests import Request

from gpt2giga.app.dependencies import get_logger_from_state
from gpt2giga.app.observability import (
    set_request_audit_model,
    set_request_audit_usage,
)
from gpt2giga.core.http.sse import format_responses_stream_event
from gpt2giga.core.logging.setup import rquid_context
from gpt2giga.features.responses._streaming.events import (
    ResponsesStreamEventSequencer,
)
from gpt2giga.features.responses._streaming.failures import (
    emit_stream_failure_event,
)
from gpt2giga.providers.gigachat.client import get_gigachat_client
from gpt2giga.providers.gigachat.streaming import (
    iter_chat_stream_chunks,
    iter_stream_with_disconnect,
)


async def stream_responses_generator_v1(
    request: Request,
    chat_messages: Chat | Any,
    *,
    response_id: str,
    giga_client: Optional[GigaChat],
    request_data: Optional[dict[str, Any]],
    response_processor: Any,
) -> AsyncGenerator[str, None]:
    """Stream legacy Responses API events over the v1 backend path."""
    logger = None
    rquid = rquid_context.get()
    processor = response_processor
    model = request_data.get("model", "unknown") if request_data else "unknown"
    set_request_audit_model(request, model)
    usage: Optional[dict[str, Any]] = None
    finish_reason: Optional[str] = None
    text_item: dict[str, Any] | None = None
    text_value = ""
    function_item: dict[str, Any] | None = None
    function_arguments = ""
    function_name: str | None = None
    response_text = processor._build_response_text_config(request_data)
    emitter = ResponsesStreamEventSequencer(format_responses_stream_event)

    def output_items() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if text_item is not None:
            items.append(text_item)
        if function_item is not None:
            items.append(function_item)
        return items

    def current_response(status: str) -> dict[str, Any]:
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

    try:
        if giga_client is None:
            giga_client = get_gigachat_client(request)
        logger = get_logger_from_state(request.app.state)

        yield emitter.emit(
            "response.created",
            {"response": current_response("in_progress")},
        )
        yield emitter.emit(
            "response.in_progress",
            {"response": current_response("in_progress")},
        )

        async for chunk in iter_stream_with_disconnect(
            request,
            iter_chat_stream_chunks(giga_client, chat_messages),
            logger=logger,
            rquid=rquid,
        ):
            chunk_dict = processor._safe_model_dump(chunk)
            choice = (chunk_dict.get("choices") or [{}])[0]
            finish_reason = choice.get("finish_reason") or finish_reason
            chunk_model = chunk_dict.get("model")
            if isinstance(chunk_model, str) and chunk_model:
                model = chunk_model
                set_request_audit_model(request, chunk_model)
            if chunk_dict.get("usage") is not None:
                usage = processor._build_response_usage(chunk_dict.get("usage"))
                set_request_audit_usage(request, usage)

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
                    yield emitter.emit(
                        "response.output_item.added",
                        {"output_index": 0, "item": text_item},
                    )
                    yield emitter.emit(
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
                yield emitter.emit(
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
                    yield emitter.emit(
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
                        yield emitter.emit(
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
            yield emitter.emit(
                "response.output_text.done",
                {
                    "item_id": text_item["id"],
                    "output_index": 0,
                    "content_index": 0,
                    "text": text_value,
                    "logprobs": [],
                },
            )
            yield emitter.emit(
                "response.content_part.done",
                {
                    "item_id": text_item["id"],
                    "output_index": 0,
                    "content_index": 0,
                    "part": text_item["content"][0],
                },
            )
            yield emitter.emit(
                "response.output_item.done",
                {"output_index": 0, "item": text_item},
            )

        if function_item is not None:
            function_item["status"] = final_item_status
            yield emitter.emit(
                "response.function_call_arguments.done",
                {
                    "item_id": function_item["id"],
                    "output_index": 1 if text_item is not None else 0,
                    "name": function_name,
                    "arguments": function_arguments,
                },
            )
            yield emitter.emit(
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
            yield emitter.emit("response.incomplete", {"response": final_response})
        else:
            yield emitter.emit("response.completed", {"response": final_response})

    except asyncio.CancelledError:
        raise

    except Exception as exc:
        yield emit_stream_failure_event(
            request=request,
            exc=exc,
            emitter=emitter,
            logger=logger,
            rquid=rquid,
        )
