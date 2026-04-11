"""Anthropic streaming helpers."""

import asyncio
import json
import uuid
from typing import Any, AsyncGenerator, Optional

from fastapi import Request
from gigachat import GigaChat

from gpt2giga.app.dependencies import get_logger_from_state
from gpt2giga.app.observability import (
    set_request_audit_model,
    set_request_audit_usage,
)
from gpt2giga.core.logging.setup import rquid_context
from gpt2giga.providers.gigachat.streaming import (
    iter_chat_stream_chunks,
    iter_chat_v2_stream_chunks,
    iter_stream_with_disconnect,
    report_stream_failure,
)
from gpt2giga.providers.gigachat.tool_mapping import map_tool_name_from_gigachat


async def _stream_anthropic_generator(
    request: Request,
    model: str,
    chat_messages: Any,
    response_id: str,
    giga_client: GigaChat,
    *,
    api_mode: str = "v1",
    response_processor: Any = None,
) -> AsyncGenerator[str, None]:
    """SSE generator producing Anthropic Messages streaming events."""
    logger = None
    rquid = rquid_context.get()
    set_request_audit_model(request, model)

    def sse(event_type: str, data: dict) -> str:
        return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

    try:
        logger = get_logger_from_state(request.app.state)

        function_call_data: Optional[dict[str, str]] = None
        content_block_started = False
        thinking_block_emitted = False
        content_index = 0
        input_tokens = 0
        output_tokens = 0

        stream_iter = (
            iter_chat_v2_stream_chunks(giga_client, chat_messages)
            if api_mode == "v2"
            else iter_chat_stream_chunks(giga_client, chat_messages)
        )
        buffered_chunks = []

        try:
            first_chunk = await anext(stream_iter)
        except StopAsyncIteration:
            first_chunk = None
        else:
            buffered_chunks.append(first_chunk)
            initial_usage = first_chunk.model_dump().get("usage") or {}
            input_tokens = initial_usage.get("prompt_tokens", 0)
            output_tokens = initial_usage.get("completion_tokens", 0)
            set_request_audit_usage(
                request,
                {
                    "prompt_tokens": input_tokens,
                    "completion_tokens": output_tokens,
                    "total_tokens": initial_usage.get(
                        "total_tokens",
                        input_tokens + output_tokens,
                    ),
                },
            )

        yield sse(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": f"msg_{response_id}",
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": model,
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                    },
                },
            },
        )
        yield sse("ping", {"type": "ping"})

        async def iter_chunks():
            for chunk in buffered_chunks:
                yield chunk
            async for chunk in stream_iter:
                yield chunk

        async for chunk in iter_stream_with_disconnect(
            request,
            iter_chunks(),
            logger=logger,
            rquid=rquid,
        ):
            giga_dict = (
                response_processor.normalize_chat_v2_stream_chunk(chunk)
                if api_mode == "v2" and response_processor is not None
                else chunk.model_dump()
            )
            choice = giga_dict["choices"][0]
            delta = choice.get("delta", {})
            delta_content = delta.get("content", "")
            delta_function_call = delta.get("function_call")
            delta_reasoning = delta.get("reasoning_content", "")

            if delta_reasoning and not thinking_block_emitted:
                yield sse(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": content_index,
                        "content_block": {"type": "thinking", "thinking": ""},
                    },
                )
                yield sse(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": content_index,
                        "delta": {
                            "type": "thinking_delta",
                            "thinking": delta_reasoning,
                        },
                    },
                )
                yield sse(
                    "content_block_stop",
                    {"type": "content_block_stop", "index": content_index},
                )
                content_index += 1
                thinking_block_emitted = True

            if delta_function_call:
                if function_call_data is None:
                    tool_id = f"toolu_{uuid.uuid4().hex[:24]}"
                    function_call_data = {
                        "name": map_tool_name_from_gigachat(
                            delta_function_call.get("name", "")
                        ),
                        "arguments": "",
                        "tool_id": tool_id,
                    }
                    yield sse(
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": content_index,
                            "content_block": {
                                "type": "tool_use",
                                "id": tool_id,
                                "name": function_call_data["name"],
                                "input": {},
                            },
                        },
                    )
                    content_block_started = True

                if delta_function_call.get("name"):
                    function_call_data["name"] = map_tool_name_from_gigachat(
                        delta_function_call["name"]
                    )

                arguments = delta_function_call.get("arguments")
                if arguments is not None:
                    arguments_str = (
                        json.dumps(arguments, ensure_ascii=False)
                        if isinstance(arguments, dict)
                        else str(arguments)
                    )
                    if arguments_str:
                        function_call_data["arguments"] += arguments_str
                        yield sse(
                            "content_block_delta",
                            {
                                "type": "content_block_delta",
                                "index": content_index,
                                "delta": {
                                    "type": "input_json_delta",
                                    "partial_json": arguments_str,
                                },
                            },
                        )
            elif delta_content:
                if not content_block_started:
                    yield sse(
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": content_index,
                            "content_block": {"type": "text", "text": ""},
                        },
                    )
                    content_block_started = True

                yield sse(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": content_index,
                        "delta": {
                            "type": "text_delta",
                            "text": delta_content,
                        },
                    },
                )

            chunk_usage = giga_dict.get("usage")
            if chunk_usage:
                input_tokens = chunk_usage.get("prompt_tokens", input_tokens)
                output_tokens = chunk_usage.get("completion_tokens", output_tokens)
                set_request_audit_usage(
                    request,
                    {
                        "prompt_tokens": input_tokens,
                        "completion_tokens": output_tokens,
                        "total_tokens": chunk_usage.get(
                            "total_tokens",
                            input_tokens + output_tokens,
                        ),
                    },
                )

        stop_reason = "tool_use" if function_call_data else "end_turn"
        if content_block_started:
            yield sse(
                "content_block_stop",
                {"type": "content_block_stop", "index": content_index},
            )

        yield sse(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {
                    "stop_reason": stop_reason,
                    "stop_sequence": None,
                },
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                },
            },
        )
        yield sse("message_stop", {"type": "message_stop"})
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        failure = report_stream_failure(
            request,
            exc,
            logger=logger,
            rquid=rquid,
        )
        yield sse(
            "error",
            {
                "type": "error",
                "error": {"type": "api_error", "message": failure.message},
            },
        )
