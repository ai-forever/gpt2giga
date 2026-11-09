"""Anthropic message endpoints."""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from typing import Any, List

from fastapi import APIRouter, Request

from gpt2giga.common.streaming_response import ModelLimitedStreamingResponse

from gpt2giga.common.streaming_response import closing_stream

from gpt2giga.app.providers import bind_model_request
from gpt2giga.common.files import validate_model_attachments
from gpt2giga.app_state import get_request_transformer
from gpt2giga.app_state import get_gigachat_client, get_model_concurrency_limiter
from gpt2giga.common.api_mode import resolve_gigachat_api_mode
from gpt2giga.common.client_params import ClientCompatibilityError
from gpt2giga.common.conversation import (
    commit_anthropic_response,
    stitch_anthropic_stream,
    stitch_normalized_chat,
)
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.gigachat_options import (
    extract_gigachat_request_options,
    gigachat_request_options,
)
from gpt2giga.common.signed_model_override import (
    resolve_signed_model_override,
)
from gpt2giga.common.request_json import read_request_json
from gpt2giga.core.context import get_request_context, update_request_context
from gpt2giga.logger import rquid_context
from gpt2giga.openapi_specs.anthropic import (
    anthropic_count_tokens_openapi_extra,
    anthropic_messages_openapi_extra,
)
from gpt2giga.openapi_tags import OPENAPI_TAG_ANTHROPIC_MESSAGES
from gpt2giga.protocol.anthropic.params import (
    sanitize_anthropic_messages_parameters,
    validate_anthropic_version,
)
from gpt2giga.protocol.anthropic.files import resolve_anthropic_file_references
from gpt2giga.protocol.anthropic.request import (
    _convert_anthropic_messages_to_openai,
    _extract_text_from_openai_messages,
    _extract_structured_output_text,
    _extract_tool_definitions_text,
)
from gpt2giga.protocols.anthropic import (
    AnthropicProtocolAdapter,
    AnthropicStreamProjector,
    normalized_chat_response_to_anthropic,
)
from gpt2giga.protocols.normalized import BridgeMatrixAdmissionError, PublicProtocol
from gpt2giga.providers.gigachat import GigaChatProviderAdapter
from gpt2giga.providers.gigachat.adapter import (
    normalized_chat_to_openai_payload,
    _normalized_token_count_texts,
)
from gpt2giga.providers.gigachat.model_resolution import resolve_upstream_model
from gpt2giga.providers.profiles import (
    ProviderAliasError,
    ProviderKind,
    ProviderModelInventory,
)
from gpt2giga.sinks.observability.anthropic import (
    emit_anthropic_message_observability,
    observe_anthropic_message_stream,
)

router = APIRouter(tags=[OPENAPI_TAG_ANTHROPIC_MESSAGES])


def _claude_cli_model_override(request: Request) -> str | None:
    """Return an authenticated Claude CLI model override."""
    return resolve_signed_model_override(
        request,
        protocol="anthropic",
        user_agent_prefix="claude-cli/",
    )


@router.post(
    "/messages/count_tokens", openapi_extra=anthropic_count_tokens_openapi_extra()
)
@exceptions_handler
async def count_tokens(request: Request):
    """Anthropic Messages count_tokens API compatible endpoint."""
    data = sanitize_anthropic_messages_parameters(
        await read_request_json(request),
        version=request.headers.get("anthropic-version"),
    )
    await bind_model_request(
        request, data.get("model"), PublicProtocol.ANTHROPIC_MESSAGES
    )
    request_options = extract_gigachat_request_options(request, dict(data))
    if _external_provider_route(request, data.get("model")) is not None:
        context = get_request_context()
        normalized = _anthropic_adapter(request).count_tokens_to_normalized(
            data, context=context
        )
        provider = _provider_adapter(
            request,
            normalized_request=normalized.input,
            request_options=request_options,
            pinned_model=_claude_cli_model_override(request),
        )
        result = await provider.count_tokens(normalized, context=context)
        return {"input_tokens": result.input_tokens}

    giga_client = get_gigachat_client(request)
    model_limiter = get_model_concurrency_limiter(request)
    resolution = resolve_upstream_model(
        data,
        request.app.state.config,
        forced_model=getattr(request.state, "upstream_model", None)
        or _claude_cli_model_override(request),
        provider="anthropic",
    )
    update_request_context(
        model_effective=resolution.model,
        metadata={"model_source": resolution.source},
    )

    if request.app.state.config.proxy_settings.normalization_mode == "on":
        texts = _normalized_token_count_texts(
            _anthropic_adapter(request).count_tokens_to_normalized(
                data, context=get_request_context()
            )
        )
    else:
        openai_messages = _convert_anthropic_messages_to_openai(
            data.get("system"),
            data.get("messages", []),
        )
        texts: List[str] = _extract_text_from_openai_messages(openai_messages)

        if "tools" in data and data["tools"]:
            texts.extend(_extract_tool_definitions_text(data["tools"]))
        texts.extend(_extract_structured_output_text(data))

    if not texts:
        return {"input_tokens": 0}

    async with model_limiter.limit(resolution.limiter_key, provider="anthropic"):
        async with gigachat_request_options(
            giga_client, request_options
        ) as request_client:
            token_counts = await request_client.atokens_count(
                texts,
                model=resolution.model,
            )
    total_tokens = sum(token_count.tokens for token_count in token_counts)
    return {"input_tokens": total_tokens}


@router.post("/messages", openapi_extra=anthropic_messages_openapi_extra())
@exceptions_handler
async def messages(request: Request):
    """Anthropic Messages API compatible endpoint."""
    data = await read_request_json(request)
    validate_anthropic_version(data, request.headers.get("anthropic-version"))
    await bind_model_request(
        request, data.get("model"), PublicProtocol.ANTHROPIC_MESSAGES
    )
    await validate_model_attachments(request, data)
    await resolve_anthropic_file_references(request, data)
    pinned_model = getattr(
        request.state, "upstream_model", None
    ) or _claude_cli_model_override(request)
    request_options = extract_gigachat_request_options(request, data)
    context = get_request_context()
    normalized_request = _anthropic_adapter(request).messages_to_normalized(
        data, context=context
    )
    conversation_turn = await stitch_normalized_chat(
        request, normalized_request, payload=data, protocol="anthropic"
    )
    openai_data = normalized_chat_to_openai_payload(normalized_request)
    await validate_model_attachments(request, openai_data)
    provider = _provider_adapter(
        request,
        normalized_request=normalized_request,
        request_options=request_options,
        pinned_model=pinned_model,
        require_streaming=normalized_request.stream,
    )
    try:
        if normalized_request.stream:
            return await _stream_message(
                request, normalized_request, provider, openai_data, conversation_turn
            )
        result = normalized_chat_response_to_anthropic(
            await provider.chat(normalized_request, context=context),
            requested_model=str(data.get("model") or "unknown"),
            context=context,
        )
    except ClientCompatibilityError as exc:
        exc.provider = "anthropic"
        raise
    await commit_anthropic_response(request, conversation_turn, result)
    await emit_anthropic_message_observability(
        request.app.state, openai_data, result, context=context
    )
    return result


async def _stream_message(
    request, normalized_request, provider, openai_data, conversation_turn
):
    """Project the shared provider stream while owning preparation and cleanup."""
    context = get_request_context()
    response_id = context.request_id if context is not None else rquid_context.get()
    projector = AnthropicStreamProjector(
        requested_model=normalized_request.model or "unknown",
        response_id=response_id or "-",
        include_cache_read_tokens=(
            isinstance(provider, GigaChatProviderAdapter)
            and request.app.state.config.proxy_settings.normalization_mode != "on"
        ),
    )
    acquired_model_limit = AsyncExitStack()
    stream_options = {}
    if isinstance(provider, GigaChatProviderAdapter):
        prepared = await provider._prepare_request(normalized_request, context)
        await acquired_model_limit.enter_async_context(
            provider.model_limiter.limit(
                prepared[1].limiter_key, provider=provider.provider_label
            )
        )
        stream_options = {
            "prepared_request": prepared,
            "acquired_model_limit": acquired_model_limit,
        }

    async def emit_stream() -> AsyncIterator[str]:
        try:
            pending_message_end = None
            async with closing_stream(
                provider.stream_chat(
                    normalized_request,
                    context=context,
                    is_disconnected=request.is_disconnected,
                    logger=getattr(request.app.state, "logger", None),
                    **stream_options,
                )
            ) as delegated_stream:
                async for event in delegated_stream:
                    if event.type == "error":
                        pending_message_end = None
                    if event.type == "message_end":
                        pending_message_end = event
                        continue
                    if event.type == "usage" and pending_message_end is not None:
                        pending_message_end = pending_message_end.model_copy(
                            update={"sequence": event.sequence, "usage": event.usage}
                        )
                        continue
                    for frame in projector.project(event):
                        yield frame
            if pending_message_end is not None:
                for frame in projector.project(pending_message_end):
                    yield frame
        finally:
            await acquired_model_limit.aclose()

    return ModelLimitedStreamingResponse(
        observe_anthropic_message_stream(
            request.app.state,
            stitch_anthropic_stream(request, conversation_turn, emit_stream()),
            request_payload=openai_data,
            context=context,
        ),
        media_type="text/event-stream",
        acquired_model_limit=acquired_model_limit,
    )


def _provider_adapter(
    request: Request,
    *,
    normalized_request: Any,
    request_options: Any,
    pinned_model: str | None,
    require_streaming: bool = False,
) -> Any:
    state = request.app.state
    route = _external_provider_route(request, normalized_request.model)
    if route is not None:
        try:
            return state.bridge_provider_runtime.adapter_for(
                normalized_request,
                api_mode=resolve_gigachat_api_mode(request),
                public_protocol=PublicProtocol.ANTHROPIC_MESSAGES,
            )
        except BridgeMatrixAdmissionError as exc:
            error = exc.as_public_error()
            raise ClientCompatibilityError(
                error["message"],
                provider="anthropic",
                param=error["param"],
                code=error["code"],
                error_type=error["type"],
            ) from exc
    return GigaChatProviderAdapter(
        config=state.config,
        request_transformer=get_request_transformer(request),
        giga_client=get_gigachat_client(request),
        model_limiter=get_model_concurrency_limiter(request),
        request_options=request_options,
        cache_session_request=request,
        response_processor=state.response_processor if require_streaming else None,
        api_mode=resolve_gigachat_api_mode(request),
        provider_label="anthropic",
        forced_model=pinned_model,
    )


def _external_provider_route(request: Request, model: Any) -> Any | None:
    """Resolve an external alias without changing dynamic GigaChat behavior."""
    runtime = getattr(request.app.state, "bridge_provider_runtime", None)
    if runtime is None:
        return None
    try:
        route = runtime.registry.resolve(model)
    except ProviderAliasError as exc:
        if any(
            profile.provider_kind is ProviderKind.GIGACHAT
            and profile.model_inventory is ProviderModelInventory.DYNAMIC
            for profile in runtime.registry.config.profiles
        ):
            return None
        raise ClientCompatibilityError(
            exc.message,
            provider="anthropic",
            param="model",
            code=exc.code,
        ) from exc
    return route if route.provider_kind is not ProviderKind.GIGACHAT else None


def _anthropic_adapter(request: Request) -> AnthropicProtocolAdapter:
    adapter = getattr(request.app.state, "anthropic_protocol_adapter", None)
    if adapter is None:
        adapter = AnthropicProtocolAdapter()
        request.app.state.anthropic_protocol_adapter = adapter
    return adapter
