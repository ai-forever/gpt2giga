"""Gemini-compatible content generation endpoints."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from gpt2giga.app_state import get_gigachat_client, get_model_concurrency_limiter
from gpt2giga.common.api_mode import resolve_gigachat_api_mode
from gpt2giga.common.conversation import (
    commit_conversation_turn,
    stitch_message_list,
)
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.gigachat_options import extract_gigachat_request_options
from gpt2giga.common.request_json import read_request_json
from gpt2giga.core.context import get_request_context, update_request_context
from gpt2giga.openapi_specs.gemini import (
    gemini_count_tokens_openapi_extra,
    gemini_generate_content_openapi_extra,
)
from gpt2giga.openapi_tags import OPENAPI_TAG_GEMINI_GENERATE_CONTENT
from gpt2giga.protocols.gemini import (
    GeminiProtocolAdapter,
    normalized_chat_response_to_gemini,
    normalized_stream_event_to_gemini_sse,
)
from gpt2giga.protocols.normalized import (
    NormalizedChoice,
    NormalizedError,
    NormalizedMessage,
    NormalizedResponse,
    NormalizedStreamEvent,
    NormalizedUsage,
)
from gpt2giga.providers.gigachat import GigaChatProviderAdapter
from gpt2giga.sinks.observability.factory import emit_observability_event
from gpt2giga.sinks.observability.llm import (
    build_llm_chat_completion_attributes,
    build_stream_span_events,
    build_tool_call_span_events,
)

router = APIRouter(tags=[OPENAPI_TAG_GEMINI_GENERATE_CONTENT])

GEMINI_SPAN_NAME = "Gemini-Content"


@router.post(
    "/models/{model}:generateContent",
    openapi_extra=gemini_generate_content_openapi_extra(streaming=False),
)
@exceptions_handler
async def generate_content(model: str, request: Request):
    """Create a Gemini-compatible content response."""
    data = await read_request_json(request)
    requested_model = _normalize_model_name(model)
    update_request_context(
        model_requested=requested_model,
        metadata={"protocol": "gemini", "api_format": "generate_content"},
    )
    context = get_request_context()
    protocol_adapter = _gemini_adapter(request)
    normalized_request = protocol_adapter.generate_content_to_normalized(
        data,
        model=requested_model,
        context=context,
        stream=False,
        builtin_tool_mapping_enabled=_builtin_tool_mapping_enabled(request),
    )
    conversation_turn = await _stitch_gemini_request(
        request,
        data,
        normalized_request,
    )
    request_options = extract_gigachat_request_options(request, data)
    provider_adapter = _provider_adapter(request, request_options=request_options)
    normalized_response = await provider_adapter.chat(
        normalized_request,
        context=context,
    )
    result = normalized_chat_response_to_gemini(
        normalized_response,
        requested_model=requested_model,
        context=context,
    )
    await commit_conversation_turn(
        request,
        conversation_turn,
        _normalized_response_messages(normalized_response),
    )
    await _emit_gemini_observability(
        request.app.state,
        normalized_request,
        normalized_response,
        context=context,
    )
    return result


@router.post(
    "/models/{model}:streamGenerateContent",
    openapi_extra=gemini_generate_content_openapi_extra(streaming=True),
)
@exceptions_handler
async def stream_generate_content(model: str, request: Request):
    """Create a Gemini-compatible content stream."""
    data = await read_request_json(request)
    requested_model = _normalize_model_name(model)
    update_request_context(
        model_requested=requested_model,
        metadata={"protocol": "gemini", "api_format": "stream_generate_content"},
    )
    context = get_request_context()
    protocol_adapter = _gemini_adapter(request)
    normalized_request = protocol_adapter.generate_content_to_normalized(
        data,
        model=requested_model,
        context=context,
        stream=True,
        builtin_tool_mapping_enabled=_builtin_tool_mapping_enabled(request),
    )
    conversation_turn = await _stitch_gemini_request(
        request,
        data,
        normalized_request,
    )
    request_options = extract_gigachat_request_options(request, data)
    provider_adapter = _provider_adapter(
        request,
        request_options=request_options,
        require_streaming=True,
    )
    response_id = context.request_id if context is not None else "gemini-stream"
    observer = _GeminiStreamObserver(response_id=response_id, model=requested_model)
    span_events: list[dict[str, Any]] = []

    async def emit_stream() -> AsyncIterator[str]:
        emitted_chunk = False
        seen_content_delta = False
        try:
            async for event in provider_adapter.stream_chat(
                normalized_request,
                context=context,
                is_disconnected=request.is_disconnected,
                logger=getattr(request.app.state, "logger", None),
            ):
                first_content_delta = (
                    event.type == "content_delta"
                    and bool(event.content_delta)
                    and not seen_content_delta
                )
                try:
                    span_events.extend(
                        build_stream_span_events(
                            event,
                            settings=request.app.state.config.proxy_settings,
                            first_content_delta=first_content_delta,
                        )
                    )
                except Exception as exc:
                    logger = getattr(request.app.state, "logger", None)
                    if logger is not None:
                        logger.warning(
                            "Gemini stream span event build failed: {}",
                            exc,
                        )
                try:
                    observer.observe(event)
                except Exception as exc:
                    logger = getattr(request.app.state, "logger", None)
                    if logger is not None:
                        logger.warning(
                            "Gemini stream observability observe failed: {}",
                            exc,
                        )
                if event.type == "content_delta" and event.content_delta:
                    seen_content_delta = True
                chunk = normalized_stream_event_to_gemini_sse(
                    event,
                    requested_model=requested_model,
                    response_id=response_id,
                )
                if chunk is not None:
                    emitted_chunk = True
                    yield chunk
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger = getattr(request.app.state, "logger", None)
            if logger is not None:
                logger.warning("Gemini stream failed before response chunk: {}", exc)
            event = _stream_error_event(
                response_id=response_id,
                model=requested_model,
                error_type=type(exc).__name__,
                code="internal_error",
            )
            span_events.extend(
                build_stream_span_events(
                    event,
                    settings=request.app.state.config.proxy_settings,
                )
            )
            yield normalized_stream_event_to_gemini_sse(
                event,
                requested_model=requested_model,
                response_id=response_id,
            )
            return

        if not emitted_chunk:
            event = _stream_empty_end_event(
                response_id=response_id,
                model=requested_model,
            )
            try:
                observer.observe(event)
            except Exception as exc:
                logger = getattr(request.app.state, "logger", None)
                if logger is not None:
                    logger.warning(
                        "Gemini empty stream observability observe failed: {}",
                        exc,
                    )
            span_events.extend(
                build_stream_span_events(
                    event,
                    settings=request.app.state.config.proxy_settings,
                )
            )
            yield normalized_stream_event_to_gemini_sse(
                event,
                requested_model=requested_model,
                response_id=response_id,
            )

        try:
            normalized_response = observer.to_normalized_response()
        except Exception as exc:
            logger = getattr(request.app.state, "logger", None)
            if logger is not None:
                logger.warning(
                    "Gemini stream observability response build failed: {}",
                    exc,
                )
            return
        await commit_conversation_turn(
            request,
            conversation_turn,
            _normalized_response_messages(normalized_response),
        )
        await _emit_gemini_observability(
            request.app.state,
            normalized_request,
            normalized_response,
            context=context,
            events=span_events,
        )

    return StreamingResponse(emit_stream(), media_type="text/event-stream")


def _stream_error_event(
    *,
    response_id: str,
    model: str,
    error_type: str,
    code: str,
) -> NormalizedStreamEvent:
    return NormalizedStreamEvent(
        type="error",
        id=response_id,
        model=model,
        error=NormalizedError(
            type=error_type,
            message="Stream interrupted",
            code=code,
        ),
    )


def _stream_empty_end_event(
    *,
    response_id: str,
    model: str,
) -> NormalizedStreamEvent:
    return NormalizedStreamEvent(
        type="message_end",
        id=response_id,
        model=model,
        finish_reason="stop",
    )


@router.post(
    "/models/{model}:countTokens",
    openapi_extra=gemini_count_tokens_openapi_extra(),
)
@exceptions_handler
async def count_tokens(model: str, request: Request):
    """Count prompt tokens for a Gemini-compatible request."""
    data = await read_request_json(request)
    requested_model = _normalize_model_name(model)
    update_request_context(
        model_requested=requested_model,
        metadata={"protocol": "gemini", "api_format": "count_tokens"},
    )
    texts = _extract_texts_for_token_count(data)
    if not texts:
        return {"totalTokens": 0}

    request_options = extract_gigachat_request_options(request, data)
    giga_client = get_gigachat_client(request)
    model_limiter = get_model_concurrency_limiter(request)
    from gpt2giga.common.gigachat_options import gigachat_request_options

    async with model_limiter.limit(requested_model, provider="gemini"):
        async with gigachat_request_options(giga_client, request_options):
            token_counts = await giga_client.atokens_count(
                texts,
                model=requested_model,
            )
    total_tokens = sum(int(getattr(item, "tokens", 0)) for item in token_counts)
    return {"totalTokens": total_tokens}


def _provider_adapter(
    request: Request,
    *,
    request_options: Any,
    require_streaming: bool = False,
) -> GigaChatProviderAdapter:
    state = request.app.state
    return GigaChatProviderAdapter(
        config=state.config,
        request_transformer=state.request_transformer,
        giga_client=get_gigachat_client(request),
        model_limiter=get_model_concurrency_limiter(request),
        request_options=request_options,
        response_processor=state.response_processor if require_streaming else None,
        api_mode=resolve_gigachat_api_mode(request),
        provider_label="gemini",
    )


def _gemini_adapter(request: Request) -> GeminiProtocolAdapter:
    adapter = getattr(request.app.state, "gemini_protocol_adapter", None)
    if adapter is None:
        adapter = GeminiProtocolAdapter()
        request.app.state.gemini_protocol_adapter = adapter
    return adapter


def _builtin_tool_mapping_enabled(request: Request) -> bool:
    return not request.app.state.config.proxy_settings.disable_builtin_tool_mapping


async def _stitch_gemini_request(
    request: Request,
    payload: dict[str, Any],
    normalized_request,
):
    turn = await stitch_message_list(
        request,
        [message.to_json_dict() for message in normalized_request.messages],
        payload=payload,
        protocol="gemini",
    )
    if turn is not None:
        normalized_request.messages = [
            NormalizedMessage.model_validate(message)
            for message in turn.request_messages
        ]
    return turn


def _normalized_response_messages(normalized_response) -> list[dict[str, Any]]:
    return [
        choice.message.to_json_dict()
        for choice in normalized_response.choices
        if choice.message is not None
    ]


async def _emit_gemini_observability(
    state,
    normalized_request,
    normalized_response,
    *,
    context,
    events: list[dict[str, Any]] | None = None,
) -> None:
    logger = getattr(state, "logger", None)
    try:
        settings = getattr(getattr(state, "config", None), "proxy_settings", None)
        span_events = list(events or [])
        span_events.extend(
            build_tool_call_span_events(normalized_response, settings=settings)
        )
        attributes = build_llm_chat_completion_attributes(
            normalized_request,
            normalized_response,
            settings=settings,
        )
        attributes["gpt2giga.api_format"] = "generate_content"
        emitted = await emit_observability_event(
            getattr(state, "observability_sink", None),
            GEMINI_SPAN_NAME,
            attributes,
            context=context,
            events=span_events or None,
            logger=logger,
        )
        if emitted and context is not None:
            context.llm_observability_emitted = True
    except Exception as exc:
        if logger is not None:
            logger.warning("Gemini observability emission failed: {}", exc)


def _extract_texts_for_token_count(payload: dict[str, Any]) -> list[str]:
    source = payload.get("generateContentRequest")
    if isinstance(source, dict):
        payload = source
    texts: list[str] = []
    system_instruction = payload.get("systemInstruction") or payload.get(
        "system_instruction"
    )
    texts.extend(_texts_from_content(system_instruction))
    contents = payload.get("contents")
    if isinstance(contents, list):
        for content in contents:
            texts.extend(_texts_from_content(content))
    else:
        texts.extend(_texts_from_content(contents))
    tools = payload.get("tools")
    if isinstance(tools, list):
        texts.extend(_texts_from_tools(tools))
    return [text for text in texts if text]


def _texts_from_content(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, dict):
        return [str(value)]
    parts = value.get("parts")
    if isinstance(parts, dict):
        parts = [parts]
    if not isinstance(parts, list):
        return []
    return [
        part["text"]
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    ]


def _texts_from_tools(tools: list[Any]) -> list[str]:
    texts: list[str] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        declarations = tool.get("functionDeclarations") or tool.get(
            "function_declarations"
        )
        if isinstance(declarations, dict):
            declarations = [declarations]
        if not isinstance(declarations, list):
            continue
        for declaration in declarations:
            if isinstance(declaration, dict):
                texts.extend(
                    str(declaration.get(key) or "") for key in ("name", "description")
                )
    return texts


def _normalize_model_name(model: str) -> str:
    return model.removeprefix("models/")


class _GeminiStreamObserver:
    def __init__(self, *, response_id: str, model: str) -> None:
        self.response_id = response_id
        self.model = model
        self.content_parts: list[str] = []
        self.usage: NormalizedUsage | None = None
        self.finish_reason: str | None = None

    def observe(self, event) -> None:
        if event.type in {"content_delta", "message_end"} and event.content_delta:
            self.content_parts.append(event.content_delta)
        if event.usage is not None:
            self.usage = event.usage
        if event.type == "message_end":
            self.finish_reason = event.finish_reason

    def to_normalized_response(self) -> NormalizedResponse:
        return NormalizedResponse(
            id=self.response_id,
            model=self.model,
            provider="gigachat",
            choices=[
                NormalizedChoice(
                    index=0,
                    message=NormalizedMessage(
                        role="assistant",
                        content="".join(self.content_parts),
                    ),
                    finish_reason=self.finish_reason,
                )
            ],
            usage=self.usage,
        )
