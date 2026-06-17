"""Normalized GigaChat provider adapter."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Mapping
from types import SimpleNamespace
from typing import Any, Literal

import gigachat

from gpt2giga.common.gigachat_options import gigachat_request_options
from gpt2giga.common.json_schema import normalize_tool_parameters_schema
from gpt2giga.common.model_concurrency import (
    ModelConcurrencyLimiter,
    ModelConcurrencyTimeoutError,
    resolve_gigachat_model,
)
from gpt2giga.common.tools import (
    map_tool_name_from_gigachat,
    normalize_gigachat_builtin_tool_type,
)
from gpt2giga.core.context import RequestContext, update_request_context
from gpt2giga.models.config import ProxyConfig
from gpt2giga.protocol.response import (
    adapt_chat_completion_chunk_to_chat_chunk_shape,
    adapt_chat_completion_to_chat_shape,
)
from gpt2giga.protocols.normalized import (
    NormalizedChatRequest,
    NormalizedChoice,
    NormalizedContentPart,
    NormalizedMessage,
    NormalizedResponse,
    NormalizedStreamEvent,
    NormalizedTool,
    NormalizedToolCall,
    NormalizedUsage,
)
from gpt2giga.providers.gigachat.streaming import GigaChatNormalizedStreamMapper


class GigaChatProviderAdapter:
    """Execute normalized requests through the current GigaChat SDK path."""

    name = "gigachat"

    def __init__(
        self,
        *,
        config: ProxyConfig,
        request_transformer: Any,
        giga_client: Any,
        model_limiter: ModelConcurrencyLimiter,
        request_options: Any = None,
        response_processor: Any = None,
        api_mode: Literal["v1", "v2"] | None = None,
        provider_label: str = "openai",
    ) -> None:
        self.config = config
        self.request_transformer = request_transformer
        self.giga_client = giga_client
        self.model_limiter = model_limiter
        self.request_options = request_options
        self.response_processor = response_processor
        self.api_mode = api_mode
        self.provider_label = provider_label

    async def complete(
        self,
        request: NormalizedChatRequest,
        *,
        context: RequestContext | None = None,
    ) -> NormalizedResponse:
        """Execute a non-streaming normalized chat request."""
        return await self.chat(request, context=context)

    async def chat(
        self,
        request: NormalizedChatRequest,
        *,
        context: RequestContext | None = None,
    ) -> NormalizedResponse:
        """Execute a non-streaming normalized chat request."""
        payload = normalized_chat_to_openai_payload(request)
        mode = self._resolve_api_mode()
        if mode == "v2":
            return await self._chat_completion(payload, request, context=context)
        return await self._chat(payload, request, context=context)

    async def stream_chat(
        self,
        request: NormalizedChatRequest,
        *,
        context: RequestContext | None = None,
        is_disconnected: Any = None,
        logger: Any = None,
    ) -> AsyncGenerator[NormalizedStreamEvent, None]:
        """Execute a streaming normalized chat request."""
        if self.response_processor is None:
            raise RuntimeError("response_processor is required for streaming")

        payload = normalized_chat_to_openai_payload(request)
        mode = self._resolve_api_mode()
        if mode == "v2":
            async for event in self._stream_chat_completion(
                payload,
                request,
                context=context,
                is_disconnected=is_disconnected,
                logger=logger,
            ):
                yield event
            return

        async for event in self._stream_chat(
            payload,
            request,
            context=context,
            is_disconnected=is_disconnected,
            logger=logger,
        ):
            yield event

    def _resolve_api_mode(self) -> Literal["v1", "v2"]:
        return self.api_mode or getattr(
            self.config.proxy_settings, "gigachat_api_mode", "v1"
        )

    async def _chat(
        self,
        payload: dict[str, Any],
        request: NormalizedChatRequest,
        *,
        context: RequestContext | None,
    ) -> NormalizedResponse:
        async with gigachat_request_options(self.giga_client, self.request_options):
            chat_payload = await self.request_transformer.prepare_chat(
                payload,
                self.giga_client,
            )
        effective_model = resolve_gigachat_model(chat_payload, self.config)
        update_request_context(model_effective=effective_model)
        async with self.model_limiter.limit(
            effective_model,
            provider=self.provider_label,
        ):
            async with gigachat_request_options(self.giga_client, self.request_options):
                response = await self.giga_client.achat(chat_payload)
        return gigachat_response_to_normalized(
            response,
            request=request,
            context=context,
        )

    async def _chat_completion(
        self,
        payload: dict[str, Any],
        request: NormalizedChatRequest,
        *,
        context: RequestContext | None,
    ) -> NormalizedResponse:
        async with gigachat_request_options(self.giga_client, self.request_options):
            chat_payload = await self.request_transformer.prepare_chat_completion(
                payload,
                self.giga_client,
            )
        effective_model = resolve_gigachat_model(chat_payload, self.config)
        update_request_context(model_effective=effective_model)
        async with self.model_limiter.limit(
            effective_model,
            provider=self.provider_label,
        ):
            async with gigachat_request_options(self.giga_client, self.request_options):
                response = await self.giga_client.achat.create(chat_payload)
        adapted = adapt_chat_completion_to_chat_shape(
            response,
            default_model=request.model or effective_model,
        )
        return gigachat_response_to_normalized(
            _ModelDumpWrapper(adapted),
            request=request,
            context=context,
        )

    async def _stream_chat(
        self,
        payload: dict[str, Any],
        request: NormalizedChatRequest,
        *,
        context: RequestContext | None,
        is_disconnected: Any,
        logger: Any,
    ):
        async with gigachat_request_options(self.giga_client, self.request_options):
            chat_payload = await self.request_transformer.prepare_chat(
                payload,
                self.giga_client,
            )
        effective_model = resolve_gigachat_model(chat_payload, self.config)
        update_request_context(model_effective=effective_model)
        mapper = self._stream_mapper(request, context)
        yield mapper.message_start()

        try:
            async with self.model_limiter.limit(
                effective_model,
                provider=self.provider_label,
            ):
                async with gigachat_request_options(
                    self.giga_client,
                    self.request_options,
                ):
                    async for chunk in self.giga_client.astream(chat_payload):
                        if await _is_disconnected(is_disconnected):
                            _log_disconnect(logger, context)
                            break
                        yield mapper.chunk_to_event(chunk)

            for event in mapper.flush_reasoning_events():
                yield event
        except ModelConcurrencyTimeoutError as exc:
            yield mapper.error_event(
                message=str(exc),
                error_type="rate_limit_error",
                code="model_concurrency_limit",
            )
        except gigachat.exceptions.GigaChatException as exc:
            _log_stream_error(logger, context, exc)
            yield mapper.error_event(
                message=str(exc),
                error_type=type(exc).__name__,
                code="stream_error",
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log_stream_error(logger, context, exc)
            yield mapper.error_event(
                message="Stream interrupted",
                raw_message="Stream interrupted",
                error_type=type(exc).__name__,
                code="internal_error",
            )

    async def _stream_chat_completion(
        self,
        payload: dict[str, Any],
        request: NormalizedChatRequest,
        *,
        context: RequestContext | None,
        is_disconnected: Any,
        logger: Any,
    ):
        async with gigachat_request_options(self.giga_client, self.request_options):
            chat_payload = await self.request_transformer.prepare_chat_completion(
                payload,
                self.giga_client,
            )
        effective_model = resolve_gigachat_model(chat_payload, self.config)
        update_request_context(model_effective=effective_model)
        mapper = self._stream_mapper(request, context)
        yield mapper.message_start()

        try:
            async with self.model_limiter.limit(
                effective_model,
                provider=self.provider_label,
            ):
                async with gigachat_request_options(
                    self.giga_client,
                    self.request_options,
                ):
                    async for chunk in self.giga_client.achat.stream(chat_payload):
                        if await _is_disconnected(is_disconnected):
                            _log_disconnect(logger, context)
                            break
                        adapted = adapt_chat_completion_chunk_to_chat_chunk_shape(
                            chunk,
                            default_model=request.model or effective_model,
                        )
                        yield mapper.chunk_to_event(
                            SimpleNamespace(model_dump=lambda: adapted)
                        )

            for event in mapper.flush_reasoning_events():
                yield event
        except ModelConcurrencyTimeoutError as exc:
            yield mapper.error_event(
                message=str(exc),
                error_type="rate_limit_error",
                code="model_concurrency_limit",
            )
        except gigachat.exceptions.GigaChatException as exc:
            _log_stream_error(logger, context, exc)
            yield mapper.error_event(
                message=str(exc),
                error_type=type(exc).__name__,
                code="stream_error",
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log_stream_error(logger, context, exc)
            yield mapper.error_event(
                message="Stream interrupted",
                raw_message="Stream interrupted",
                error_type=type(exc).__name__,
                code="internal_error",
            )

    def _stream_mapper(
        self,
        request: NormalizedChatRequest,
        context: RequestContext | None,
    ) -> GigaChatNormalizedStreamMapper:
        return GigaChatNormalizedStreamMapper(
            response_processor=self.response_processor,
            requested_model=request.model or "unknown",
            response_id=context.request_id if context is not None else "stream",
            request_data=normalized_chat_to_openai_payload(request),
        )


def normalized_chat_to_openai_payload(
    request: NormalizedChatRequest,
) -> dict[str, Any]:
    """Reconstruct an OpenAI Chat payload from normalized chat fields."""
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": [_message_to_openai(message) for message in request.messages],
        "stream": request.stream,
    }
    if request.user is not None:
        payload["user"] = request.user
    if request.metadata:
        payload["metadata"] = dict(request.metadata)
    if request.tools:
        payload["tools"] = [_tool_to_openai(tool) for tool in request.tools]
    if request.tool_choice is not None:
        payload["tool_choice"] = request.tool_choice
    if request.response_format is not None:
        payload["response_format"] = request.response_format.to_json_dict()

    generation = request.generation_config
    for source, target in (
        ("temperature", "temperature"),
        ("top_p", "top_p"),
        ("max_tokens", "max_tokens"),
        ("presence_penalty", "presence_penalty"),
        ("frequency_penalty", "frequency_penalty"),
        ("stop", "stop"),
        ("seed", "seed"),
    ):
        value = getattr(generation, source)
        if value is not None:
            payload[target] = value

    if request.protocol == "openai":
        payload.update(request.raw_extensions)
    additional_fields = _gigachat_additional_fields(request.provider_metadata)
    if additional_fields:
        existing = payload.get("additional_fields")
        if isinstance(existing, Mapping):
            payload["additional_fields"] = {**dict(existing), **additional_fields}
        else:
            payload["additional_fields"] = additional_fields
    return {key: value for key, value in payload.items() if value is not None}


def gigachat_response_to_normalized(
    response: Any,
    *,
    request: NormalizedChatRequest,
    context: RequestContext | None = None,
) -> NormalizedResponse:
    """Convert a GigaChat-compatible response object to normalized response."""
    data = response.model_dump() if hasattr(response, "model_dump") else dict(response)
    return NormalizedResponse(
        id=context.request_id if context is not None else None,
        model=request.model,
        provider="gigachat",
        choices=[
            _choice_to_normalized(index, choice)
            for index, choice in enumerate(data.get("choices") or [])
            if isinstance(choice, Mapping)
        ],
        usage=_usage_to_normalized(data.get("usage")),
        metadata=_response_metadata(data),
        provider_metadata={
            "gigachat": {
                key: value
                for key, value in data.items()
                if key not in {"choices", "usage", "x_headers"}
            }
        },
    )


def _message_to_openai(message: NormalizedMessage) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "role": message.role,
        "content": _content_to_openai(message.content),
    }
    if message.name is not None:
        payload["name"] = message.name
    if message.tool_call_id is not None:
        payload["tool_call_id"] = message.tool_call_id
    if message.tool_calls:
        payload["tool_calls"] = [
            _tool_call_to_openai(tool_call) for tool_call in message.tool_calls
        ]
    payload.update(message.raw_extensions)
    return {key: value for key, value in payload.items() if value is not None}


def _content_to_openai(
    content: str | list[NormalizedContentPart] | None,
) -> str | list[dict[str, Any]] | None:
    if content is None or isinstance(content, str):
        return content
    return [_content_part_to_openai(part) for part in content]


def _content_part_to_openai(part: NormalizedContentPart) -> dict[str, Any]:
    payload = {"type": part.type}
    if part.type == "text":
        payload["text"] = part.text or ""
    elif part.type == "image_url":
        payload["image_url"] = part.data
    elif part.type == "file":
        payload["file"] = part.data
    else:
        payload["data"] = part.data
    payload.update(part.raw_extensions)
    return payload


def _tool_to_openai(tool: NormalizedTool) -> dict[str, Any]:
    raw_extensions = dict(tool.raw_extensions)
    builtin_field_name = normalize_gigachat_builtin_tool_type(tool.type)
    if builtin_field_name is not None:
        payload: dict[str, Any] = {"type": builtin_field_name}
        config = raw_extensions.pop(builtin_field_name, None)
        if isinstance(config, Mapping):
            payload[builtin_field_name] = dict(config)
        payload.update(raw_extensions)
        return payload

    parameters = normalize_tool_parameters_schema(tool.parameters)
    payload = {
        "type": tool.type,
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": parameters,
        },
    }
    function_payload = {
        key: value for key, value in payload["function"].items() if value is not None
    }
    payload["function"] = function_payload
    function_extensions = raw_extensions.pop("function", None)
    if isinstance(function_extensions, Mapping):
        payload["function"].update(dict(function_extensions))
    payload.update(raw_extensions)
    return payload


def _tool_call_to_openai(tool_call: NormalizedToolCall) -> dict[str, Any]:
    raw_extensions = dict(tool_call.raw_extensions)
    payload: dict[str, Any] = {
        "id": tool_call.id,
        "type": tool_call.type,
        "function": {
            "name": tool_call.name,
            "arguments": tool_call.arguments,
        },
    }
    function_extensions = raw_extensions.pop("function", None)
    if isinstance(function_extensions, Mapping):
        payload["function"].update(dict(function_extensions))
    payload.update(raw_extensions)
    return {key: value for key, value in payload.items() if value is not None}


def _gigachat_additional_fields(provider_metadata: Mapping[str, Any]) -> dict[str, Any]:
    gigachat_metadata = provider_metadata.get("gigachat")
    if not isinstance(gigachat_metadata, Mapping):
        return {}
    additional_fields = gigachat_metadata.get("additional_fields")
    if not isinstance(additional_fields, Mapping):
        return {}
    return dict(additional_fields)


def _choice_to_normalized(index: int, choice: Mapping[str, Any]) -> NormalizedChoice:
    message_data = choice.get("message") if isinstance(choice, Mapping) else None
    message = _response_message_to_normalized(message_data)
    finish_reason = choice.get("finish_reason")
    if finish_reason == "function_call":
        finish_reason = "tool_calls"
    return NormalizedChoice(
        index=int(choice.get("index", index)),
        message=message,
        finish_reason=finish_reason,
        raw_extensions={
            key: value
            for key, value in choice.items()
            if key not in {"index", "message", "finish_reason"}
        },
    )


def _response_message_to_normalized(value: Any) -> NormalizedMessage | None:
    if not isinstance(value, Mapping):
        return None
    tool_calls = []
    function_call = value.get("function_call")
    if isinstance(function_call, Mapping):
        tool_calls.append(_function_call_to_normalized(function_call, value))
    return NormalizedMessage(
        role=str(value.get("role", "assistant")),
        content=value.get("content"),
        tool_calls=tool_calls,
        raw_extensions={
            key: item
            for key, item in value.items()
            if key
            not in {
                "role",
                "content",
                "function_call",
            }
        },
    )


def _function_call_to_normalized(
    function_call: Mapping[str, Any],
    message: Mapping[str, Any],
) -> NormalizedToolCall:
    arguments = function_call.get("arguments", {})
    return NormalizedToolCall(
        id=_backend_state_id_from_message(message),
        type="function",
        name=map_tool_name_from_gigachat(str(function_call.get("name", ""))),
        arguments=arguments,
    )


def _usage_to_normalized(value: Any) -> NormalizedUsage | None:
    if not isinstance(value, Mapping):
        return None
    input_tokens = value.get("prompt_tokens", value.get("input_tokens"))
    output_tokens = value.get("completion_tokens", value.get("output_tokens"))
    return NormalizedUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=value.get("total_tokens"),
        raw_extensions={
            key: item
            for key, item in value.items()
            if key
            not in {
                "prompt_tokens",
                "completion_tokens",
                "input_tokens",
                "output_tokens",
                "total_tokens",
            }
        },
    )


def _response_metadata(data: Mapping[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    headers = data.get("x_headers")
    if isinstance(headers, Mapping):
        for key, value in headers.items():
            normalized_key = str(key).lower()
            if normalized_key in {"authorization", "x-api-key", "cookie"}:
                continue
            if normalized_key.startswith("x-"):
                metadata[f"gigachat_{normalized_key.replace('-', '_')}"] = str(value)
    return metadata


def _backend_state_id_from_message(message: Mapping[str, Any]) -> str | None:
    for field_name in (
        "tools_state_id",
        "tool_state_id",
        "functions_state_id",
        "function_state_id",
        "tool_call_id",
    ):
        value = message.get(field_name)
        if not isinstance(value, str):
            continue
        state_id = value.strip()
        if not state_id:
            continue
        for prefix in ("fc_", "call_"):
            if state_id.startswith(prefix) and len(state_id) > len(prefix):
                return state_id.removeprefix(prefix)
        return state_id
    return None


class _ModelDumpWrapper:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def model_dump(self) -> dict[str, Any]:
        return self._data


async def _is_disconnected(is_disconnected: Any) -> bool:
    if is_disconnected is None:
        return False
    result = is_disconnected()
    if hasattr(result, "__await__"):
        result = await result
    return bool(result)


def _log_disconnect(logger: Any, context: RequestContext | None) -> None:
    if logger is None:
        return
    request_id = context.request_id if context is not None else None
    logger.bind(request_id=request_id).info(
        "Client disconnected during normalized streaming"
    )


def _log_stream_error(
    logger: Any,
    context: RequestContext | None,
    exc: BaseException,
) -> None:
    if logger is None:
        return
    request_id = context.request_id if context is not None else None
    logger.bind(
        request_id=request_id,
        error_type=type(exc).__name__,
    ).error("Normalized streaming error")
