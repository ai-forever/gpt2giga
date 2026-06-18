"""Anthropic message endpoints."""

from collections.abc import Mapping
from typing import Dict, List

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

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
from gpt2giga.protocol.anthropic.response import _anthropic_http_exception
from gpt2giga.protocol.anthropic.streaming import (
    _stream_anthropic_generator,
    _stream_anthropic_chat_completion_generator,
)
from gpt2giga.protocol.response import adapt_chat_completion_to_chat_shape
from gpt2giga.protocols.anthropic import (
    buffered_anthropic_sse_from_normalized_response,
    normalized_response_to_anthropic_message,
)
from gpt2giga.protocols.normalized import NormalizedChatRequest
from gpt2giga.protocols.openai import OpenAIProtocolAdapter
from gpt2giga.providers.fusion.adapter import FusionProviderAdapter
from gpt2giga.providers.fusion.detection import extract_fusion_request
from gpt2giga.providers.fusion.errors import FusionConfigurationError
from gpt2giga.providers.gigachat import GigaChatProviderAdapter
from gpt2giga.sinks.observability.anthropic import (
    emit_anthropic_message_observability,
    observe_anthropic_message_stream,
)

router = APIRouter(tags=[OPENAPI_TAG_ANTHROPIC_MESSAGES])


@router.post(
    "/messages/count_tokens", openapi_extra=anthropic_count_tokens_openapi_extra()
)
@exceptions_handler
async def count_tokens(request: Request):
    """Anthropic Messages count_tokens API compatible endpoint."""
    data = sanitize_anthropic_messages_parameters(await read_request_json(request))
    request_options = extract_gigachat_request_options(request, dict(data))
    giga_client = get_gigachat_client(request)
    model_limiter = get_model_concurrency_limiter(request)
    model = data.get("model", "unknown")

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
    request_options = extract_gigachat_request_options(request, data)
    stream = data.get("stream", False)
    current_rquid = rquid_context.get()
    state = request.app.state
    giga_client = get_gigachat_client(request)
    model_limiter = get_model_concurrency_limiter(request)

    model = data.get("model", "unknown")
    openai_data: Dict = _build_openai_data_from_anthropic_request(data, state.logger)
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

    fusion_response = await _try_fusion_anthropic_messages(
        request,
        data,
        openai_data,
        request_options,
        giga_client,
        model_limiter,
        conversation_turn,
        structured_output_fallback=structured_output_fallback,
    )
    if fusion_response is not None:
        return fusion_response

    mode = resolve_gigachat_api_mode(request)

    if mode == "v2":
        async with gigachat_request_options(giga_client, request_options):
            chat_request = await state.request_transformer.prepare_chat_completion(
                openai_data, giga_client
            )
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


async def _try_fusion_anthropic_messages(
    request: Request,
    payload: dict,
    openai_data: dict,
    request_options,
    giga_client,
    model_limiter,
    conversation_turn,
    *,
    structured_output_fallback: bool,
) -> dict | JSONResponse | StreamingResponse | None:
    state = request.app.state
    settings = getattr(getattr(state, "config", None), "proxy_settings", None)
    if settings is None:
        return None

    fusion_settings = settings.fusion
    try:
        fusion_config = extract_fusion_request(payload, fusion_settings)
    except FusionConfigurationError as exc:
        return _anthropic_http_exception(400, "invalid_request_error", str(exc))
    if fusion_config is None:
        return None

    stream = bool(payload.get("stream", False))
    if stream and fusion_settings.streaming_mode != "buffered":
        return _anthropic_http_exception(
            400,
            "invalid_request_error",
            "Fusion streaming is disabled.",
        )

    protocol_adapter = getattr(state, "openai_protocol_adapter", None)
    if protocol_adapter is None:
        protocol_adapter = OpenAIProtocolAdapter()
    context = get_request_context()
    normalized_request = await protocol_adapter.to_normalized(
        openai_data,
        context=context,
    )
    normalized_request.protocol = "anthropic"
    normalized_request.operation = "messages"
    _strip_fusion_request_artifacts(normalized_request)

    upstream_provider = GigaChatProviderAdapter(
        config=state.config,
        request_transformer=state.request_transformer,
        giga_client=giga_client,
        model_limiter=model_limiter,
        request_options=request_options,
        response_processor=getattr(state, "response_processor", None),
        api_mode=resolve_gigachat_api_mode(request),
        provider_label="anthropic",
        force_request_model=True,
    )
    fusion_adapter = FusionProviderAdapter(
        settings=fusion_settings,
        upstream_provider=upstream_provider,
    )
    normalized_response = await fusion_adapter.chat(
        normalized_request,
        context=context,
        fusion_config=fusion_config,
        is_disconnected=request.is_disconnected,
    )
    requested_model = str(
        payload.get("model") or normalized_response.model or "GigaChat"
    )
    response_id = normalized_response.id
    if response_id is None:
        response_id = context.request_id if context is not None else rquid_context.get()
    response_id = response_id or "fusion"

    if normalized_response.error is not None and not stream:
        return _anthropic_http_exception(
            502,
            normalized_response.error.type,
            normalized_response.error.message,
        )

    if not stream:
        result = normalized_response_to_anthropic_message(
            normalized_response,
            requested_model=requested_model,
            response_id=response_id,
            is_structured_output=structured_output_fallback,
        )
        await commit_anthropic_response(request, conversation_turn, result)
        await emit_anthropic_message_observability(
            state,
            openai_data,
            result,
            context=context,
        )
        return result

    body_iterator = stitch_anthropic_stream(
        request,
        conversation_turn,
        buffered_anthropic_sse_from_normalized_response(
            normalized_response,
            requested_model=requested_model,
            response_id=response_id,
            is_structured_output=structured_output_fallback,
        ),
    )
    return StreamingResponse(
        observe_anthropic_message_stream(
            state,
            body_iterator,
            request_payload=openai_data,
            context=context,
        ),
        media_type="text/event-stream",
    )


def _strip_fusion_request_artifacts(normalized_request: NormalizedChatRequest) -> None:
    normalized_request.tools = [
        tool for tool in normalized_request.tools if tool.type != "openrouter:fusion"
    ]
    normalized_request.metadata.pop("gpt2giga_fusion", None)
    gigachat_metadata = normalized_request.provider_metadata.get("gigachat")
    if isinstance(gigachat_metadata, Mapping):
        additional_fields = gigachat_metadata.get("additional_fields")
        if isinstance(additional_fields, dict):
            for key in ("plugins", "gpt2giga_fusion"):
                additional_fields.pop(key, None)
    for key in ("plugins", "gpt2giga_fusion"):
        normalized_request.raw_extensions.pop(key, None)
