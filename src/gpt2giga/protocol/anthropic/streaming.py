"""Anthropic streaming helpers."""

import json
import uuid
from types import SimpleNamespace
from typing import Any, AsyncGenerator, Dict, Optional

import gigachat
from fastapi import Request
from gigachat import GigaChat

from gpt2giga.app_state import get_model_concurrency_limiter
from gpt2giga.common.gigachat_options import (
    GigaRequestOptions,
    gigachat_request_options,
)
from gpt2giga.common.model_concurrency import (
    ModelConcurrencyLimiter,
    ModelConcurrencyTimeoutError,
)
from gpt2giga.common.reasoning import ReasoningContentParser
from gpt2giga.common.sources import (
    SourceMarkerStreamRenderer,
    extract_sources,
    has_source_marker_start,
)
from gpt2giga.common.tools import map_tool_name_from_gigachat
from gpt2giga.logger import rquid_context
from gpt2giga.protocol.response import adapt_chat_completion_chunk_to_chat_chunk_shape
from gpt2giga.protocol.anthropic.response import _backend_tool_state_id
from gpt2giga.providers.gigachat.model_resolution import resolve_upstream_model


async def _stream_anthropic_generator(
    request: Request,
    model: str,
    chat_messages: Dict[str, Any],
    response_id: str,
    giga_client: Any,
    *,
    request_options: Optional[GigaRequestOptions] = None,
    model_limiter: Optional[ModelConcurrencyLimiter] = None,
    effective_model: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """SSE generator producing Anthropic Messages streaming events."""
    logger = None
    rquid = rquid_context.get()

    def sse(event_type: str, data: dict) -> str:
        return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

    try:
        logger = getattr(request.app.state, "logger", None)
        if model_limiter is None:
            model_limiter = get_model_concurrency_limiter(request)
        if effective_model is None:
            effective_model = resolve_upstream_model(
                chat_messages,
                getattr(request.app.state, "config", None),
                api_mode=getattr(
                    getattr(request.app.state.config, "proxy_settings", None),
                    "gigachat_api_mode",
                    "v1",
                ),
                provider="anthropic",
            ).limiter_key

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
        source_renderer = SourceMarkerStreamRenderer()
        source_rendering_enabled = False
        content_index = 0
        output_tokens = 0
        input_tokens = 0
        cached_tokens = 0

        async with model_limiter.limit(effective_model, provider="anthropic"):
            async with gigachat_request_options(giga_client, request_options):
                async for chunk in giga_client.astream(chat_messages):
                    if await request.is_disconnected():
                        if logger:
                            logger.info(
                                f"[{rquid}] Client disconnected during streaming"
                            )
                        break

                    giga_dict = chunk.model_dump()
                    choice = giga_dict["choices"][0]
                    delta = choice.get("delta", {})
                    delta_content = _delta_text(delta.get("content"))
                    delta_function_calls = [
                        {
                            **call["function"],
                            "id": call.get("id"),
                            "tools_state_id": _backend_tool_state_id(call),
                        }
                        for call in delta.get("tool_calls") or []
                        if isinstance(call, dict)
                        and isinstance(call.get("function"), dict)
                    ]
                    if delta.get("function_call"):
                        delta_function_calls.append(delta["function_call"])
                    delta_reasoning = _delta_text(delta.get("reasoning_content"))
                    parsed_content = reasoning_parser.feed(delta_content)
                    delta_content = parsed_content.content
                    inline_data = delta.get("inline_data")
                    source_rendering_enabled = (
                        source_rendering_enabled
                        or bool(extract_sources(inline_data or {}))
                        or has_source_marker_start(delta_content)
                    )
                    if source_rendering_enabled:
                        source_renderer.merge_inline_data(inline_data)
                        delta_content = source_renderer.feed(delta_content)
                    delta_reasoning = (
                        f"{delta_reasoning}{parsed_content.reasoning_content}"
                    )

                    if delta_reasoning:
                        if not thinking_block_started or thinking_block_stopped:
                            yield sse(
                                "content_block_start",
                                {
                                    "type": "content_block_start",
                                    "index": content_index,
                                    "content_block": {
                                        "type": "thinking",
                                        "thinking": "",
                                    },
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

                    if delta_function_calls:
                        if thinking_block_started and not thinking_block_stopped:
                            yield sse(
                                "content_block_stop",
                                {"type": "content_block_stop", "index": content_index},
                            )
                            content_index += 1
                            thinking_block_stopped = True

                        for delta_function_call in delta_function_calls:
                            arguments = delta_function_call.get("arguments")
                            incoming_id = (
                                delta_function_call.get("id")
                                or delta_function_call.get("id_")
                                or _backend_tool_state_id(delta)
                            )
                            if (
                                function_call_data
                                and incoming_id
                                and incoming_id != function_call_data["tool_id"]
                            ):
                                yield sse(
                                    "content_block_stop",
                                    {
                                        "type": "content_block_stop",
                                        "index": content_index,
                                    },
                                )
                                content_index += 1
                                function_call_data = None
                            if function_call_data is None:
                                tool_id = (
                                    delta_function_call.get("id")
                                    or delta_function_call.get("id_")
                                    or _backend_tool_state_id(delta)
                                    or f"toolu_{uuid.uuid4().hex[:24]}"
                                )
                                function_call_data = {
                                    "name": map_tool_name_from_gigachat(
                                        delta_function_call.get("name", "")
                                    ),
                                    "tool_id": tool_id,
                                }
                                tools_state_id = _backend_tool_state_id(
                                    delta_function_call
                                ) or _backend_tool_state_id(delta)
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
                                            **(
                                                {"tools_state_id": tools_state_id}
                                                if tools_state_id
                                                else {}
                                            ),
                                        },
                                    },
                                )
                                content_block_started = True

                            if delta_function_call.get("name"):
                                function_call_data["name"] = (
                                    map_tool_name_from_gigachat(
                                        delta_function_call["name"]
                                    )
                                )

                            if arguments is not None:
                                arguments_str = (
                                    json.dumps(arguments, ensure_ascii=False)
                                    if isinstance(arguments, dict)
                                    else str(arguments)
                                )
                                if arguments_str:
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
                    if chunk_usage:
                        output_tokens = chunk_usage.get(
                            "completion_tokens", output_tokens
                        )
                        input_tokens = chunk_usage.get("prompt_tokens", input_tokens)
                        cached_tokens = (
                            chunk_usage.get("precached_prompt_tokens", cached_tokens)
                            or 0
                        )

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
        if source_rendering_enabled:
            source_text = source_renderer.feed(flushed_reasoning.content)
            source_text += source_renderer.finish()
        else:
            source_text = flushed_reasoning.content
        if source_text:
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
                        "text": source_text,
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
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_read_input_tokens": cached_tokens,
                },
            },
        )
        yield sse("message_stop", {"type": "message_stop"})
    except ModelConcurrencyTimeoutError as exc:
        yield sse(
            "error",
            {
                "type": "error",
                "error": {
                    "type": "rate_limit_error",
                    "message": str(exc),
                    "code": "model_concurrency_limit",
                },
            },
        )
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
        if logger:
            logger.error(
                f"[{rquid}] Unexpected streaming error: {type(exc).__name__}: {exc}"
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


class _ChatCompletionAnthropicStreamClient:
    def __init__(
        self,
        giga_client: GigaChat,
        model: str,
        request_options: Optional[GigaRequestOptions],
    ):
        self._giga_client = giga_client
        self._model = model
        self._request_options = request_options

    def astream(self, chat_request: Any):
        async def gen():
            pending: list[dict[str, Any]] = []
            known_state_id: Optional[str] = None
            async with gigachat_request_options(
                self._giga_client,
                self._request_options,
            ):
                async for chunk in self._giga_client.achat.stream(chat_request):
                    adapted = adapt_chat_completion_chunk_to_chat_chunk_shape(
                        chunk,
                        default_model=self._model,
                    )
                    delta = adapted["choices"][0]["delta"]
                    state_id = _backend_tool_state_id(delta) or known_state_id
                    if state_id:
                        known_state_id = state_id
                        delta.setdefault("tools_state_id", state_id)
                    has_calls = bool(
                        delta.get("tool_calls") or delta.get("function_call")
                    )
                    # Anthropic SDKs retain extras from block_start only. Wait for
                    # a late provider state before starting the corresponding block.
                    if pending or (has_calls and not state_id):
                        pending.append(adapted)
                        if not state_id:
                            continue
                        for buffered in pending:
                            buffered_delta = buffered["choices"][0]["delta"]
                            buffered_delta.setdefault("tools_state_id", state_id)
                            yield SimpleNamespace(model_dump=lambda item=buffered: item)
                        pending.clear()
                    else:
                        yield SimpleNamespace(model_dump=lambda item=adapted: item)
            for buffered in pending:
                yield SimpleNamespace(model_dump=lambda item=buffered: item)

        return gen()


async def _stream_anthropic_chat_completion_generator(
    request: Request,
    model: str,
    chat_request: Any,
    response_id: str,
    giga_client: GigaChat,
    *,
    request_options: Optional[GigaRequestOptions] = None,
    model_limiter: Optional[ModelConcurrencyLimiter] = None,
    effective_model: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """SSE generator for Anthropic Messages backed by chat completion streaming."""
    adapter_client = _ChatCompletionAnthropicStreamClient(
        giga_client,
        model,
        request_options,
    )
    async for event in _stream_anthropic_generator(
        request,
        model,
        chat_request,
        response_id,
        adapter_client,
        request_options=None,
        model_limiter=model_limiter,
        effective_model=effective_model,
    ):
        yield event


def _delta_text(value: Any) -> str:
    return value if isinstance(value, str) else ""
