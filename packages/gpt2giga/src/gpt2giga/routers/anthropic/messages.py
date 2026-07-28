"""Anthropic message endpoints."""

from collections.abc import AsyncIterator
from typing import Any, Dict, List

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from gpt2giga.app_state import get_gigachat_client, get_model_concurrency_limiter
from gpt2giga.common.api_mode import resolve_gigachat_api_mode
from gpt2giga.common.conversation import (
    commit_anthropic_response,
    stitch_anthropic_stream,
    stitch_chat_payload,
)
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.gigachat_options import (
    extract_gigachat_request_options,
    gigachat_request_options,
)
from gpt2giga.common.harness_model import trusted_harness_model
from gpt2giga.common.model_concurrency import resolve_gigachat_model
from gpt2giga.common.request_json import read_request_json
from gpt2giga.core.context import get_request_context, update_request_context
from gpt2giga.logger import rquid_context
from gpt2giga.openapi_specs.anthropic import (
    anthropic_count_tokens_openapi_extra,
    anthropic_messages_openapi_extra,
)
from gpt2giga.openapi_tags import OPENAPI_TAG_ANTHROPIC_MESSAGES
from gpt2giga.protocol.anthropic.params import sanitize_anthropic_messages_parameters
from gpt2giga.protocol.anthropic.request import (
    _build_openai_data_from_anthropic_request,
    _convert_anthropic_messages_to_openai,
    _extract_text_from_openai_messages,
    _extract_structured_output_text,
    _extract_tool_definitions_text,
    _is_anthropic_structured_output_request,
)
from gpt2giga.protocol.anthropic.response import _build_anthropic_response
from gpt2giga.protocol.anthropic.streaming import (
    _stream_anthropic_generator,
    _stream_anthropic_chat_completion_generator,
)
from gpt2giga.protocol.response import adapt_chat_completion_to_chat_shape
from gpt2giga.protocols.anthropic import (
    AnthropicProtocolAdapter,
    AnthropicStreamProjector,
    normalized_chat_response_to_anthropic,
)
from gpt2giga.providers.gigachat import GigaChatProviderAdapter
from gpt2giga.sinks.observability.anthropic import (
    emit_anthropic_message_observability,
    observe_anthropic_message_stream,
)

router = APIRouter(tags=[OPENAPI_TAG_ANTHROPIC_MESSAGES])


def _claude_cli_harness_model(request: Request) -> str | None:
    """Return an authenticated Harness-pinned Claude model."""
    return trusted_harness_model(
        request,
        protocol="anthropic",
        user_agent_prefix="claude-cli/",
    )


def _force_harness_model(payload: Any, model: str | None) -> Any:
    """Apply a trusted request-scoped model after global pass-model handling."""
    if model is None:
        return payload
    if isinstance(payload, dict):
        return {**payload, "model": model}
    model_copy = getattr(payload, "model_copy", None)
    if callable(model_copy):
        return model_copy(update={"model": model})
    setattr(payload, "model", model)
    return payload


@router.post(
    "/messages/count_tokens", openapi_extra=anthropic_count_tokens_openapi_extra()
)
@exceptions_handler
async def count_tokens(request: Request):
    """Anthropic Messages count_tokens API compatible endpoint."""
    data = sanitize_anthropic_messages_parameters(await read_request_json(request))
    request_options = extract_gigachat_request_options(request, dict(data))
    normalized = await _try_normalized_count_tokens(
        request,
        data,
        request_options=request_options,
    )
    if normalized is not None:
        return normalized

    giga_client = get_gigachat_client(request)
    model_limiter = get_model_concurrency_limiter(request)
    model = _claude_cli_harness_model(request) or data.get("model", "unknown")

    openai_messages = _convert_anthropic_messages_to_openai(
        data.get("system"), data.get("messages", [])
    )
    texts: List[str] = _extract_text_from_openai_messages(openai_messages)

    if "tools" in data and data["tools"]:
        texts.extend(_extract_tool_definitions_text(data["tools"]))
    texts.extend(_extract_structured_output_text(data))

    if not texts:
        return {"input_tokens": 0}

    async with model_limiter.limit(model, provider="anthropic"):
        async with gigachat_request_options(giga_client, request_options):
            token_counts = await giga_client.atokens_count(texts, model=model)
    total_tokens = sum(token_count.tokens for token_count in token_counts)
    return {"input_tokens": total_tokens}


@router.post("/messages", openapi_extra=anthropic_messages_openapi_extra())
@exceptions_handler
async def messages(request: Request):
    """Anthropic Messages API compatible endpoint."""
    data = await read_request_json(request)
    pinned_model = _claude_cli_harness_model(request)
    request_options = extract_gigachat_request_options(request, data)
    stream = data.get("stream", False)
    current_rquid = rquid_context.get()
    state = request.app.state
    giga_client = get_gigachat_client(request)
    model_limiter = get_model_concurrency_limiter(request)

    model = data.get("model", "unknown")
    openai_data: Dict = _build_openai_data_from_anthropic_request(
        data,
        state.logger,
        builtin_tool_mapping_enabled=not state.config.proxy_settings.disable_builtin_tool_mapping,
    )
    if "conversation" in data:
        openai_data["conversation"] = data["conversation"]
    if "metadata" in data:
        openai_data["metadata"] = data["metadata"]
    conversation_turn = await stitch_chat_payload(
        request,
        openai_data,
        protocol="anthropic",
    )
    structured_output_fallback = (
        _is_anthropic_structured_output_request(data)
        and state.config.proxy_settings.structured_output_mode == "function_call"
    )
    mode = resolve_gigachat_api_mode(request)

    normalized_response = await _try_normalized_non_stream_message(
        request,
        data,
        openai_data=openai_data,
        request_options=request_options,
        conversation_turn=conversation_turn,
        pinned_model=pinned_model,
        structured_output=structured_output_fallback,
    )
    if normalized_response is not None:
        return normalized_response

    normalized_stream = await _try_normalized_stream_message(
        request,
        data,
        openai_data=openai_data,
        request_options=request_options,
        conversation_turn=conversation_turn,
        pinned_model=pinned_model,
        structured_output=structured_output_fallback,
    )
    if normalized_stream is not None:
        return normalized_stream

    if mode == "v2":
        async with gigachat_request_options(giga_client, request_options):
            chat_request = await state.request_transformer.prepare_chat_completion(
                openai_data, giga_client
            )
        chat_request = _force_harness_model(chat_request, pinned_model)
        effective_model = resolve_gigachat_model(chat_request, state.config)
        update_request_context(model_effective=effective_model)
        if not stream:
            async with model_limiter.limit(effective_model, provider="anthropic"):
                async with gigachat_request_options(giga_client, request_options):
                    response = await giga_client.achat.create(chat_request)
            giga_dict = adapt_chat_completion_to_chat_shape(
                response,
                default_model=model,
            )
            result = _build_anthropic_response(
                giga_dict,
                model,
                current_rquid,
                is_structured_output=structured_output_fallback,
                logger=state.logger,
                mode=state.config.proxy_settings.mode,
                log_level=state.config.proxy_settings.log_level,
            )
            await commit_anthropic_response(request, conversation_turn, result)
            await emit_anthropic_message_observability(
                state,
                openai_data,
                result,
                context=get_request_context(),
            )
            return result

        return StreamingResponse(
            observe_anthropic_message_stream(
                state,
                stitch_anthropic_stream(
                    request,
                    conversation_turn,
                    _stream_anthropic_chat_completion_generator(
                        request,
                        model,
                        chat_request,
                        current_rquid,
                        giga_client,
                        is_structured_output=structured_output_fallback,
                        request_options=request_options,
                        model_limiter=model_limiter,
                        effective_model=effective_model,
                    ),
                ),
                request_payload=openai_data,
                context=get_request_context(),
            ),
            media_type="text/event-stream",
        )

    async with gigachat_request_options(giga_client, request_options):
        chat_messages = await state.request_transformer.prepare_chat(
            openai_data, giga_client
        )
    chat_messages = _force_harness_model(chat_messages, pinned_model)
    effective_model = resolve_gigachat_model(chat_messages, state.config)
    update_request_context(model_effective=effective_model)

    if not stream:
        async with model_limiter.limit(effective_model, provider="anthropic"):
            async with gigachat_request_options(giga_client, request_options):
                response = await giga_client.achat(chat_messages)
        giga_dict = response.model_dump()
        result = _build_anthropic_response(
            giga_dict,
            model,
            current_rquid,
            is_structured_output=structured_output_fallback,
            logger=state.logger,
            mode=state.config.proxy_settings.mode,
            log_level=state.config.proxy_settings.log_level,
        )
        await commit_anthropic_response(request, conversation_turn, result)
        await emit_anthropic_message_observability(
            state,
            openai_data,
            result,
            context=get_request_context(),
        )
        return result

    return StreamingResponse(
        observe_anthropic_message_stream(
            state,
            stitch_anthropic_stream(
                request,
                conversation_turn,
                _stream_anthropic_generator(
                    request,
                    model,
                    chat_messages,
                    current_rquid,
                    giga_client,
                    is_structured_output=structured_output_fallback,
                    request_options=request_options,
                    model_limiter=model_limiter,
                    effective_model=effective_model,
                ),
            ),
            request_payload=openai_data,
            context=get_request_context(),
        ),
        media_type="text/event-stream",
    )


async def _try_normalized_count_tokens(
    request: Request,
    payload: dict[str, Any],
    *,
    request_options: Any,
) -> dict[str, int] | None:
    settings = _normalization_settings(request)
    if settings is None or settings.normalization_mode != "on":
        return None
    try:
        context = get_request_context()
        normalized_request = _anthropic_adapter(request).count_tokens_to_normalized(
            payload,
            context=context,
            builtin_tool_mapping_enabled=_builtin_tool_mapping_enabled(request),
        )
        response = await _provider_adapter(
            request,
            request_options=request_options,
            pinned_model=_claude_cli_harness_model(request),
        ).count_tokens(normalized_request, context=context)
        return {"input_tokens": response.input_tokens}
    except Exception as exc:
        if not settings.legacy_chat_fallback:
            raise
        _log_normalized_fallback(request, exc, event="anthropic_count_tokens_fallback")
        return None


async def _try_normalized_non_stream_message(
    request: Request,
    payload: dict[str, Any],
    *,
    openai_data: dict[str, Any],
    request_options: Any,
    conversation_turn: Any,
    pinned_model: str | None,
    structured_output: bool,
) -> dict[str, Any] | None:
    settings = _normalization_settings(request)
    if (
        settings is None
        or settings.normalization_mode != "on"
        or payload.get("stream", False)
    ):
        return None
    try:
        context = get_request_context()
        normalized_request = _anthropic_adapter(request).messages_to_normalized(
            payload,
            context=context,
            builtin_tool_mapping_enabled=_builtin_tool_mapping_enabled(request),
        )
        normalized_response = await _provider_adapter(
            request,
            request_options=request_options,
            pinned_model=pinned_model,
        ).chat(normalized_request, context=context)
        result = normalized_chat_response_to_anthropic(
            normalized_response,
            requested_model=str(payload.get("model") or "unknown"),
            context=context,
            structured_output=structured_output,
        )
        await commit_anthropic_response(request, conversation_turn, result)
        await emit_anthropic_message_observability(
            request.app.state,
            openai_data,
            result,
            context=context,
        )
        return result
    except Exception as exc:
        if not settings.legacy_chat_fallback:
            raise
        _log_normalized_fallback(request, exc, event="anthropic_message_fallback")
        return None


async def _try_normalized_stream_message(
    request: Request,
    payload: dict[str, Any],
    *,
    openai_data: dict[str, Any],
    request_options: Any,
    conversation_turn: Any,
    pinned_model: str | None,
    structured_output: bool,
) -> StreamingResponse | None:
    settings = _normalization_settings(request)
    if (
        settings is None
        or settings.normalization_mode != "on"
        or not payload.get("stream", False)
    ):
        return None
    try:
        context = get_request_context()
        normalized_request = _anthropic_adapter(request).messages_to_normalized(
            payload,
            context=context,
            builtin_tool_mapping_enabled=_builtin_tool_mapping_enabled(request),
        )
        provider = _provider_adapter(
            request,
            request_options=request_options,
            pinned_model=pinned_model,
            require_streaming=True,
        )
        response_id = context.request_id if context is not None else rquid_context.get()
        projector = AnthropicStreamProjector(
            requested_model=str(payload.get("model") or "unknown"),
            response_id=response_id or "-",
            structured_output=structured_output,
        )

        async def emit_stream() -> AsyncIterator[str]:
            async for event in provider.stream_chat(
                normalized_request,
                context=context,
                is_disconnected=request.is_disconnected,
                logger=getattr(request.app.state, "logger", None),
            ):
                for frame in projector.project(event):
                    yield frame

        body_iterator = observe_anthropic_message_stream(
            request.app.state,
            stitch_anthropic_stream(
                request,
                conversation_turn,
                emit_stream(),
            ),
            request_payload=openai_data,
            context=context,
        )
        return StreamingResponse(body_iterator, media_type="text/event-stream")
    except Exception as exc:
        if not settings.legacy_chat_fallback:
            raise
        _log_normalized_fallback(request, exc, event="anthropic_stream_fallback")
        return None


def _provider_adapter(
    request: Request,
    *,
    request_options: Any,
    pinned_model: str | None,
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
        provider_label="anthropic",
        forced_model=pinned_model,
    )


def _anthropic_adapter(request: Request) -> AnthropicProtocolAdapter:
    adapter = getattr(request.app.state, "anthropic_protocol_adapter", None)
    if adapter is None:
        adapter = AnthropicProtocolAdapter()
        request.app.state.anthropic_protocol_adapter = adapter
    return adapter


def _normalization_settings(request: Request) -> Any:
    return getattr(
        getattr(request.app.state, "config", None),
        "proxy_settings",
        None,
    )


def _builtin_tool_mapping_enabled(request: Request) -> bool:
    settings = _normalization_settings(request)
    return settings is None or not settings.disable_builtin_tool_mapping


def _log_normalized_fallback(
    request: Request,
    exc: Exception,
    *,
    event: str,
) -> None:
    logger = getattr(request.app.state, "logger", None)
    if logger is None:
        return
    context = get_request_context()
    logger.bind(
        event=event,
        route=request.url.path,
        error_type=type(exc).__name__,
        request_id=getattr(context, "request_id", None),
    ).warning("Normalized Anthropic path failed; using legacy fallback")
