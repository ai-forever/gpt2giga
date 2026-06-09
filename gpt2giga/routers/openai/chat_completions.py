"""OpenAI chat completions endpoint."""

import json
from collections.abc import AsyncIterator
from collections.abc import Mapping
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from gpt2giga.app_state import get_gigachat_client, get_model_concurrency_limiter
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.gigachat_options import (
    extract_gigachat_request_options,
    gigachat_request_options,
)
from gpt2giga.common.model_concurrency import resolve_gigachat_model
from gpt2giga.common.request_json import read_request_json
from gpt2giga.common.streaming import (
    stream_chat_completion_generator,
    stream_chat_completion_v2_generator,
)
from gpt2giga.core.context import get_request_context, update_request_context
from gpt2giga.logger import rquid_context
from gpt2giga.openapi_specs.openai import chat_completions_openapi_extra
from gpt2giga.protocol.response import adapt_v2_completion_to_v1_shape
from gpt2giga.protocols.openai import (
    normalized_chat_response_to_openai,
    normalized_stream_done_sse,
    normalized_stream_event_to_openai_sse,
)
from gpt2giga.protocols.normalized import run_openai_chat_shadow_normalization
from gpt2giga.protocols.normalized.models import (
    NormalizedChoice,
    NormalizedError,
    NormalizedMessage,
    NormalizedResponse,
    NormalizedToolCall,
    NormalizedUsage,
)
from gpt2giga.providers.gigachat import GigaChatProviderAdapter
from gpt2giga.routers.openai.helpers import populate_giga_functions
from gpt2giga.sinks.observability.factory import emit_observability_event
from gpt2giga.sinks.observability.llm import (
    CHAT_COMPLETION_SPAN_NAME,
    build_llm_chat_completion_attributes,
    build_stream_span_events,
    build_tool_call_span_events,
)

router = APIRouter(tags=["OpenAI"])


@router.post("/chat/completions", openapi_extra=chat_completions_openapi_extra())
@exceptions_handler
async def chat_completions(request: Request):
    """Create a chat completion."""
    data = await read_request_json(request)
    request_data = deepcopy(data)
    request_options = extract_gigachat_request_options(request, data)
    stream = data.get("stream", False)
    current_rquid = rquid_context.get()
    state = request.app.state
    giga_client = get_gigachat_client(request)
    model_limiter = get_model_concurrency_limiter(request)
    mode = getattr(state.config.proxy_settings, "gigachat_api_mode", "v1")

    normalized_response = await _try_normalized_non_stream_chat(
        request,
        request_data,
        request_options,
        giga_client,
        model_limiter,
    )
    if normalized_response is not None:
        return normalized_response

    normalized_stream_response = await _try_normalized_stream_chat(
        request,
        request_data,
        request_options,
        giga_client,
        model_limiter,
    )
    if normalized_stream_response is not None:
        return normalized_stream_response

    await run_openai_chat_shadow_normalization(request, request_data)
    populate_giga_functions(data, getattr(state, "logger", None))
    if mode == "v2":
        async with gigachat_request_options(giga_client, request_options):
            chat_request = await state.request_transformer.prepare_chat_completion_v2(
                data, giga_client
            )
        effective_model = resolve_gigachat_model(chat_request, state.config)
        update_request_context(model_effective=effective_model)
        if stream:
            acquired_model_limit = model_limiter.limit(
                effective_model,
                provider="openai",
            )
            await acquired_model_limit.__aenter__()
            return StreamingResponse(
                _observe_chat_completion_stream(
                    state,
                    stream_chat_completion_v2_generator(
                        request,
                        data["model"],
                        chat_request,
                        current_rquid,
                        giga_client,
                        request_options,
                        request_data=request_data,
                        model_limiter=model_limiter,
                        effective_model=effective_model,
                        acquired_model_limit=acquired_model_limit,
                    ),
                    request_payload=request_data,
                    context=get_request_context(),
                ),
                media_type="text/event-stream",
            )
        async with model_limiter.limit(effective_model, provider="openai"):
            async with gigachat_request_options(giga_client, request_options):
                response = await giga_client.achat.create(chat_request)
        adapted = adapt_v2_completion_to_v1_shape(
            response,
            default_model=data["model"],
        )
        result = state.response_processor.process_response(
            SimpleNamespace(model_dump=lambda: adapted),
            data["model"],
            current_rquid,
            request_data=request_data,
        )
        await _emit_legacy_chat_completion_observability(
            state,
            request_data,
            result,
            context=get_request_context(),
        )
        return result

    async with gigachat_request_options(giga_client, request_options):
        chat_messages = await state.request_transformer.prepare_chat_completion(
            data, giga_client
        )
    effective_model = resolve_gigachat_model(chat_messages, state.config)
    update_request_context(model_effective=effective_model)
    if not stream:
        async with model_limiter.limit(effective_model, provider="openai"):
            async with gigachat_request_options(giga_client, request_options):
                response = await giga_client.achat(chat_messages)
        result = state.response_processor.process_response(
            response, data["model"], current_rquid, request_data=request_data
        )
        await _emit_legacy_chat_completion_observability(
            state,
            request_data,
            result,
            context=get_request_context(),
        )
        return result

    acquired_model_limit = model_limiter.limit(effective_model, provider="openai")
    await acquired_model_limit.__aenter__()
    return StreamingResponse(
        _observe_chat_completion_stream(
            state,
            stream_chat_completion_generator(
                request,
                data["model"],
                chat_messages,
                current_rquid,
                giga_client,
                request_options,
                request_data=request_data,
                model_limiter=model_limiter,
                effective_model=effective_model,
                acquired_model_limit=acquired_model_limit,
            ),
            request_payload=request_data,
            context=get_request_context(),
        ),
        media_type="text/event-stream",
    )


async def _try_normalized_non_stream_chat(
    request: Request,
    payload: dict,
    request_options,
    giga_client,
    model_limiter,
) -> dict | None:
    state = request.app.state
    settings = getattr(getattr(state, "config", None), "proxy_settings", None)
    if (
        settings is None
        or settings.normalization_mode != "on"
        or payload.get("stream", False)
    ):
        return None

    try:
        protocol_adapter = state.openai_protocol_adapter
        context = get_request_context()
        normalized_request = await protocol_adapter.to_normalized(
            payload,
            context=context,
        )
        provider_adapter = GigaChatProviderAdapter(
            config=state.config,
            request_transformer=state.request_transformer,
            giga_client=giga_client,
            model_limiter=model_limiter,
            request_options=request_options,
        )
        normalized_response = await provider_adapter.chat(
            normalized_request,
            context=context,
        )
        await _emit_chat_completion_observability(
            state,
            normalized_request,
            normalized_response,
            context=context,
        )
        return normalized_chat_response_to_openai(
            normalized_response,
            requested_model=payload["model"],
            context=context,
        )
    except Exception as exc:
        if not settings.legacy_chat_fallback:
            raise
        logger = getattr(state, "logger", None)
        if logger is not None:
            logger.bind(
                event="normalized_chat_fallback",
                route=request.url.path,
                error_type=type(exc).__name__,
                request_id=getattr(get_request_context(), "request_id", None),
            ).warning("Normalized chat path failed; using legacy fallback")
        return None


async def _try_normalized_stream_chat(
    request: Request,
    payload: dict,
    request_options,
    giga_client,
    model_limiter,
) -> StreamingResponse | None:
    state = request.app.state
    settings = getattr(getattr(state, "config", None), "proxy_settings", None)
    if (
        settings is None
        or settings.normalization_mode != "on"
        or not payload.get("stream", False)
    ):
        return None

    try:
        protocol_adapter = state.openai_protocol_adapter
        context = get_request_context()
        normalized_request = await protocol_adapter.to_normalized(
            payload,
            context=context,
        )
        provider_adapter = GigaChatProviderAdapter(
            config=state.config,
            request_transformer=state.request_transformer,
            giga_client=giga_client,
            model_limiter=model_limiter,
            request_options=request_options,
            response_processor=state.response_processor,
        )
        response_id = context.request_id if context is not None else rquid_context.get()
        stream_span_events: list[dict[str, Any]] = []

        async def emit_stream():
            seen_content_delta = False
            async for event in provider_adapter.stream_chat(
                normalized_request,
                context=context,
                is_disconnected=request.is_disconnected,
                logger=getattr(state, "logger", None),
            ):
                first_content_delta = (
                    event.type == "content_delta"
                    and bool(event.content_delta)
                    and not seen_content_delta
                )
                span_events = build_stream_span_events(
                    event,
                    settings=settings,
                    first_content_delta=first_content_delta,
                )
                if span_events:
                    stream_span_events.extend(span_events)
                if event.type == "content_delta" and event.content_delta:
                    seen_content_delta = True
                sse = normalized_stream_event_to_openai_sse(
                    event,
                    requested_model=payload["model"],
                    response_id=response_id,
                )
                if sse is not None:
                    yield sse
            yield normalized_stream_done_sse()

        return StreamingResponse(
            _observe_chat_completion_stream(
                state,
                emit_stream(),
                request_payload=payload,
                context=context,
                normalized_request=normalized_request,
                stream_span_events=stream_span_events,
            ),
            media_type="text/event-stream",
        )
    except Exception as exc:
        if not settings.legacy_chat_fallback:
            raise
        logger = getattr(state, "logger", None)
        if logger is not None:
            logger.bind(
                event="normalized_chat_stream_fallback",
                route=request.url.path,
                error_type=type(exc).__name__,
                request_id=getattr(get_request_context(), "request_id", None),
            ).warning("Normalized chat stream path failed; using legacy fallback")
        return None


async def _observe_chat_completion_stream(
    state,
    body_iterator: AsyncIterator[str],
    *,
    request_payload: Mapping[str, Any],
    context,
    normalized_request=None,
    stream_span_events: list[dict[str, Any]] | None = None,
) -> AsyncIterator[str]:
    sink = getattr(state, "observability_sink", None)
    if sink is None or sink.__class__.__name__ == "NoopObservabilitySink":
        async for chunk in body_iterator:
            yield chunk
        return

    if normalized_request is None:
        try:
            protocol_adapter = getattr(state, "openai_protocol_adapter", None)
            if protocol_adapter is not None:
                normalized_request = await protocol_adapter.to_normalized(
                    request_payload,
                    context=context,
                )
        except Exception as exc:
            logger = getattr(state, "logger", None)
            if logger is not None:
                logger.warning(
                    "Chat completion stream observability normalization failed: {}",
                    exc,
                )

    observer = _ChatCompletionStreamObserver()
    async for chunk in body_iterator:
        observer.observe_chunk(chunk)
        yield chunk

    if normalized_request is None or not observer.has_observed_payload:
        return

    await _emit_chat_completion_observability(
        state,
        normalized_request,
        observer.to_normalized_response(),
        context=context,
        events=stream_span_events,
    )


async def _emit_legacy_chat_completion_observability(
    state,
    request_payload: Mapping[str, Any],
    response_payload: Mapping[str, Any],
    *,
    context,
) -> None:
    settings = getattr(getattr(state, "config", None), "proxy_settings", None)
    sink = getattr(state, "observability_sink", None)
    if sink is None or sink.__class__.__name__ == "NoopObservabilitySink":
        return
    try:
        protocol_adapter = getattr(state, "openai_protocol_adapter", None)
        if protocol_adapter is None:
            return
        normalized_request = await protocol_adapter.to_normalized(
            request_payload,
            context=context,
        )
        if normalized_request is None:
            return
        normalized_response = _openai_chat_completion_to_normalized_response(
            response_payload
        )
    except Exception as exc:
        logger = getattr(state, "logger", None)
        if logger is not None:
            logger.warning(
                "Chat completion observability normalization failed: {}", exc
            )
        return

    await _emit_chat_completion_observability(
        state,
        normalized_request,
        normalized_response,
        context=context,
        settings=settings,
    )


async def _emit_chat_completion_observability(
    state,
    normalized_request,
    normalized_response,
    *,
    context,
    settings=None,
    events: list[dict[str, Any]] | None = None,
) -> None:
    if settings is None:
        settings = getattr(getattr(state, "config", None), "proxy_settings", None)
    span_events = list(events or [])
    span_events.extend(
        build_tool_call_span_events(normalized_response, settings=settings)
    )
    await emit_observability_event(
        getattr(state, "observability_sink", None),
        CHAT_COMPLETION_SPAN_NAME,
        build_llm_chat_completion_attributes(
            normalized_request,
            normalized_response,
            settings=settings,
        ),
        context=context,
        events=span_events or None,
        logger=getattr(state, "logger", None),
    )
    if context is not None:
        context.llm_observability_emitted = True


class _ChatCompletionStreamObserver:
    def __init__(self) -> None:
        self.has_observed_payload = False
        self.response_id: str | None = None
        self.model: str | None = None
        self.finish_reason: str | None = None
        self.content_parts: list[str] = []
        self.reasoning_parts: list[str] = []
        self.metadata: dict[str, Any] = {}
        self.usage: NormalizedUsage | None = None
        self.error: NormalizedError | None = None
        self.tool_calls: dict[int, dict[str, Any]] = {}

    def observe_chunk(self, chunk: Any) -> None:
        for payload in _iter_sse_json_payloads(chunk):
            self.observe_payload(payload)

    def observe_payload(self, payload: Mapping[str, Any]) -> None:
        self.has_observed_payload = True
        self.response_id = _string_or_none(payload.get("id")) or self.response_id
        self.model = _string_or_none(payload.get("model")) or self.model

        metadata = payload.get("metadata")
        if isinstance(metadata, Mapping):
            self.metadata.update(dict(metadata))

        usage = _openai_usage_to_normalized_usage(payload.get("usage"))
        if usage is not None:
            self.usage = usage

        error = payload.get("error")
        if isinstance(error, Mapping):
            self.error = NormalizedError(
                type=_string_or_none(error.get("type")) or "stream_error",
                message=_string_or_none(error.get("message")) or "",
                code=error.get("code"),
                param=_string_or_none(error.get("param")),
            )

        for choice in payload.get("choices") or []:
            if isinstance(choice, Mapping):
                self._observe_choice(choice)

    def to_normalized_response(self) -> NormalizedResponse:
        message = NormalizedMessage(
            role="assistant",
            content="".join(self.content_parts),
            tool_calls=[
                _stream_tool_call_to_normalized_tool_call(tool_call)
                for _, tool_call in sorted(self.tool_calls.items())
            ],
        )
        if self.reasoning_parts:
            message.raw_extensions["reasoning_content"] = "".join(self.reasoning_parts)
        return NormalizedResponse(
            id=self.response_id,
            model=self.model,
            provider="gigachat",
            choices=[
                NormalizedChoice(
                    index=0,
                    message=message,
                    finish_reason=self.finish_reason,
                )
            ],
            usage=self.usage,
            error=self.error,
            metadata=self.metadata,
        )

    def _observe_choice(self, choice: Mapping[str, Any]) -> None:
        finish_reason = _string_or_none(choice.get("finish_reason"))
        if finish_reason is not None:
            self.finish_reason = finish_reason

        delta = choice.get("delta")
        if not isinstance(delta, Mapping):
            return

        content = delta.get("content")
        if isinstance(content, str):
            self.content_parts.append(content)

        reasoning_content = delta.get("reasoning_content")
        if isinstance(reasoning_content, str):
            self.reasoning_parts.append(reasoning_content)

        for raw_tool_call in delta.get("tool_calls") or []:
            if isinstance(raw_tool_call, Mapping):
                self._observe_tool_call(raw_tool_call)

    def _observe_tool_call(self, raw_tool_call: Mapping[str, Any]) -> None:
        index = raw_tool_call.get("index", len(self.tool_calls))
        if not isinstance(index, int):
            index = len(self.tool_calls)
        tool_call = self.tool_calls.setdefault(
            index,
            {"function": {"arguments": ""}},
        )
        if raw_tool_call.get("id") is not None:
            tool_call["id"] = raw_tool_call.get("id")
        if raw_tool_call.get("type") is not None:
            tool_call["type"] = raw_tool_call.get("type")
        function = raw_tool_call.get("function")
        if isinstance(function, Mapping):
            target_function = tool_call.setdefault("function", {"arguments": ""})
            if function.get("name") is not None:
                target_function["name"] = function.get("name")
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                target_function["arguments"] = (
                    target_function.get("arguments", "") + arguments
                )


def _stream_tool_call_to_normalized_tool_call(
    value: Mapping[str, Any],
) -> NormalizedToolCall:
    function = value.get("function")
    function = function if isinstance(function, Mapping) else {}
    return NormalizedToolCall(
        id=_string_or_none(value.get("id")),
        type=_string_or_none(value.get("type")) or "function",
        name=_string_or_none(function.get("name")),
        arguments=function.get("arguments"),
    )


def _iter_sse_json_payloads(chunk: Any) -> list[Mapping[str, Any]]:
    if isinstance(chunk, bytes):
        text = chunk.decode("utf-8", errors="replace")
    else:
        text = str(chunk)
    payloads: list[Mapping[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        data = line.removeprefix("data:").strip()
        if not data or data == "[DONE]":
            continue
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            payloads.append(payload)
    return payloads


def _openai_chat_completion_to_normalized_response(
    payload: Mapping[str, Any],
) -> NormalizedResponse:
    usage = payload.get("usage")
    metadata = payload.get("metadata")
    return NormalizedResponse(
        id=_string_or_none(payload.get("id")),
        model=_string_or_none(payload.get("model")),
        provider="gigachat",
        choices=[
            _openai_choice_to_normalized_choice(index, choice)
            for index, choice in enumerate(payload.get("choices") or [])
            if isinstance(choice, Mapping)
        ],
        usage=_openai_usage_to_normalized_usage(usage),
        metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
    )


def _openai_choice_to_normalized_choice(
    index: int,
    choice: Mapping[str, Any],
) -> NormalizedChoice:
    choice_index = choice.get("index", index)
    if not isinstance(choice_index, int):
        choice_index = index
    message = choice.get("message")
    return NormalizedChoice(
        index=choice_index,
        message=_openai_message_to_normalized_message(message),
        finish_reason=_string_or_none(choice.get("finish_reason")),
    )


def _openai_message_to_normalized_message(value: Any) -> NormalizedMessage | None:
    if not isinstance(value, Mapping):
        return None
    return NormalizedMessage(
        role=str(value.get("role", "assistant")),
        content=value.get("content"),
        name=_string_or_none(value.get("name")),
        tool_call_id=_string_or_none(value.get("tool_call_id")),
        tool_calls=[
            _openai_tool_call_to_normalized_tool_call(tool_call)
            for tool_call in value.get("tool_calls") or []
            if isinstance(tool_call, Mapping)
        ],
    )


def _openai_tool_call_to_normalized_tool_call(
    value: Mapping[str, Any],
) -> NormalizedToolCall:
    function = value.get("function")
    function = function if isinstance(function, Mapping) else {}
    return NormalizedToolCall(
        id=_string_or_none(value.get("id")),
        type=str(value.get("type", "function")),
        name=_string_or_none(function.get("name")),
        arguments=function.get("arguments"),
    )


def _openai_usage_to_normalized_usage(value: Any) -> NormalizedUsage | None:
    if not isinstance(value, Mapping):
        return None
    return NormalizedUsage(
        input_tokens=value.get("prompt_tokens", value.get("input_tokens")),
        output_tokens=value.get("completion_tokens", value.get("output_tokens")),
        total_tokens=value.get("total_tokens"),
    )


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
