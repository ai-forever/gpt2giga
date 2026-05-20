"""Anthropic streaming helpers."""

import json
import traceback
import uuid
from typing import Any, AsyncGenerator, Dict, Optional

import gigachat
from fastapi import Request
from gigachat import GigaChat

from gpt2giga.common.reasoning import ReasoningContentParser
from gpt2giga.common.tools import map_tool_name_from_gigachat
from gpt2giga.logger import rquid_context


async def _stream_anthropic_generator(
    request: Request,
    model: str,
    chat_messages: Dict[str, Any],
    response_id: str,
    giga_client: GigaChat,
    *,
    is_structured_output: bool = False,
) -> AsyncGenerator[str, None]:
    """SSE generator producing Anthropic Messages streaming events."""
    logger = None
    rquid = rquid_context.get()

    def sse(event_type: str, data: dict) -> str:
        return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

    try:
        logger = getattr(request.app.state, "logger", None)

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
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            },
        )
        yield sse("ping", {"type": "ping"})

        function_call_data: Optional[Dict[str, str]] = None
        content_block_started = False
        thinking_block_started = False
        thinking_block_stopped = False
        reasoning_parser = ReasoningContentParser()
        content_index = 0
        output_tokens = 0

        async for chunk in giga_client.astream(chat_messages):
            if await request.is_disconnected():
                if logger:
                    logger.info(f"[{rquid}] Client disconnected during streaming")
                break

            giga_dict = chunk.model_dump()
            choice = giga_dict["choices"][0]
            delta = choice.get("delta", {})
            delta_content = delta.get("content", "")
            delta_function_call = delta.get("function_call")
            delta_reasoning = delta.get("reasoning_content", "")
            parsed_content = reasoning_parser.feed(delta_content)
            delta_content = parsed_content.content
            delta_reasoning = f"{delta_reasoning}{parsed_content.reasoning_content}"

            if delta_reasoning:
                if not thinking_block_started or thinking_block_stopped:
                    yield sse(
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": content_index,
                            "content_block": {"type": "thinking", "thinking": ""},
                        },
                    )
                    thinking_block_started = True
                    thinking_block_stopped = False
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

            if delta_function_call:
                if thinking_block_started and not thinking_block_stopped:
                    yield sse(
                        "content_block_stop",
                        {"type": "content_block_stop", "index": content_index},
                    )
                    content_index += 1
                    thinking_block_stopped = True

                arguments = delta_function_call.get("arguments")
                if is_structured_output:
                    if arguments is None:
                        continue

                    arguments_str = (
                        json.dumps(arguments, ensure_ascii=False)
                        if isinstance(arguments, dict)
                        else str(arguments)
                    )
                    if not arguments_str:
                        continue

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
                                "text": arguments_str,
                            },
                        },
                    )
                    continue

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
                if thinking_block_started and not thinking_block_stopped:
                    yield sse(
                        "content_block_stop",
                        {"type": "content_block_stop", "index": content_index},
                    )
                    content_index += 1
                    thinking_block_stopped = True

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
            if chunk_usage and chunk_usage.get("completion_tokens"):
                output_tokens = chunk_usage["completion_tokens"]

        flushed_reasoning = reasoning_parser.flush()
        if flushed_reasoning.reasoning_content:
            if not thinking_block_started or thinking_block_stopped:
                yield sse(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": content_index,
                        "content_block": {"type": "thinking", "thinking": ""},
                    },
                )
                thinking_block_started = True
                thinking_block_stopped = False
            yield sse(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": content_index,
                    "delta": {
                        "type": "thinking_delta",
                        "thinking": flushed_reasoning.reasoning_content,
                    },
                },
            )
        if flushed_reasoning.content:
            if thinking_block_started and not thinking_block_stopped:
                yield sse(
                    "content_block_stop",
                    {"type": "content_block_stop", "index": content_index},
                )
                content_index += 1
                thinking_block_stopped = True
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
                        "text": flushed_reasoning.content,
                    },
                },
            )

        stop_reason = "tool_use" if function_call_data else "end_turn"
        if thinking_block_started and not thinking_block_stopped:
            yield sse(
                "content_block_stop",
                {"type": "content_block_stop", "index": content_index},
            )
            content_index += 1
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
                "usage": {"output_tokens": output_tokens},
            },
        )
        yield sse("message_stop", {"type": "message_stop"})
    except gigachat.exceptions.GigaChatException as exc:
        if logger:
            logger.error(
                f"[{rquid}] GigaChat streaming error: {type(exc).__name__}: {exc}"
            )
        yield sse(
            "error",
            {
                "type": "error",
                "error": {"type": "api_error", "message": str(exc)},
            },
        )
    except Exception as exc:
        traceback_text = traceback.format_exc()
        if logger:
            logger.error(
                f"[{rquid}] Unexpected streaming error: {type(exc).__name__}: {exc}\n{traceback_text}"
            )
        yield sse(
            "error",
            {
                "type": "error",
                "error": {
                    "type": "api_error",
                    "message": "Stream interrupted",
                },
            },
        )
