"""Normalized OpenAI-compatible upstream execution."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import ssl
from typing import Any, Literal, Protocol
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from pydantic import Field, field_validator, model_validator

from gpt2giga.protocols.normalized import (
    BridgeFeature,
    DownstreamProtocol,
    NormalizedBaseModel,
    NormalizedChatRequest,
    NormalizedChoice,
    NormalizedContentPart,
    NormalizedError,
    NormalizedMessage,
    NormalizedProtocolCapabilities,
    NormalizedResponse,
    NormalizedStopReason,
    NormalizedStreamEvent,
    NormalizedTokenLimits,
    NormalizedToolCall,
    NormalizedUsage,
    ProtocolBridgeAdmission,
    admit_protocol_bridge_request,
)


OPENAI_COMPATIBLE_UPSTREAM_SCHEMA_VERSION = "gigaloom.openai-compatible-upstream.v1"
OPENAI_CHAT_COMPLETIONS_DIALECT = "openai-chat-completions-v1"
OPENAI_CHAT_EXECUTION_OWNER = "provider-execution:openai-compatible"
DEFAULT_MAX_RESPONSE_BYTES = 1024 * 1024
MAX_MODEL_DISCOVERY_ITEMS = 500
MAX_MODEL_ID_CHARS = 256
_REQUEST_PURPOSE_CHAT = "provider.openai-compatible.chat"
_REQUEST_PURPOSE_MODELS = "provider.openai-compatible.models"


class OpenAICompatibleUpstreamProfile(NormalizedBaseModel):
    """Versioned execution profile without credential values or grant contents."""

    schema_version: Literal["gigaloom.openai-compatible-upstream.v1"] = (
        OPENAI_COMPATIBLE_UPSTREAM_SCHEMA_VERSION
    )
    id: str = Field(min_length=1, max_length=256)
    revision: str = Field(min_length=1, max_length=256)
    dialect: Literal["openai-chat-completions-v1"] = OPENAI_CHAT_COMPLETIONS_DIALECT
    base_url: str
    model: str = Field(min_length=1, max_length=256)
    capabilities: NormalizedProtocolCapabilities
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    max_response_bytes: int = Field(
        default=DEFAULT_MAX_RESPONSE_BYTES,
        gt=0,
        le=16 * 1024 * 1024,
    )
    credential_reference_id: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    network_policy_ref: str = Field(min_length=1, max_length=256)
    tls_policy_ref: str | None = Field(default=None, min_length=1, max_length=256)
    proxy_policy_ref: str | None = Field(default=None, min_length=1, max_length=256)

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        return _canonical_base_url(value)

    @model_validator(mode="after")
    def _validate_profile(self) -> OpenAICompatibleUpstreamProfile:
        if self.raw_extensions or self.provider_metadata:
            raise ValueError("upstream profile extensions are not admitted")
        if self.capabilities.profile != f"{self.id}@{self.revision}":
            raise ValueError("upstream capabilities do not bind the profile revision")
        if self.capabilities.raw_extensions or self.capabilities.provider_metadata:
            raise ValueError("upstream capability extensions are not admitted")
        return self

    @property
    def chat_completions_url(self) -> str:
        """Return the exact Chat Completions endpoint."""
        return _endpoint_url(self.base_url, "chat/completions")

    @property
    def models_url(self) -> str:
        """Return the exact model-discovery endpoint."""
        return _endpoint_url(self.base_url, "models")


@dataclass(frozen=True)
class OpenAICompatibleNetworkIntent:
    """Exact outbound request intent presented to a network-grant owner."""

    url: str
    method: Literal["GET", "POST"]
    purpose: str
    request_body_bytes: int
    request_body_sha256: str | None
    max_response_bytes: int


class OpenAICompatibleNetworkAuthorization(Protocol):
    """Validated network ticket used at the final transport boundary."""

    max_response_bytes: int
    peer_validation_required: bool

    def validate_request_body(
        self,
        *,
        body_bytes: int,
        body_sha256: str | None,
    ) -> None:
        """Reject a body that differs from the reviewed request."""

    def validate_connected_peer(self, address: str) -> None:
        """Reject a transport peer that differs from pre-connect resolution."""

    def validate_response_body(self, *, body_bytes: int) -> None:
        """Reject a response larger than the reviewed ceiling."""


OpenAICompatibleNetworkAuthorizer = Callable[
    [OpenAICompatibleNetworkIntent],
    OpenAICompatibleNetworkAuthorization,
]


class OpenAICompatibleUpstreamError(RuntimeError):
    """Stable normalized upstream failure."""

    def __init__(self, error: NormalizedError, *, status_code: int | None = None):
        super().__init__(error.message)
        self.error = error
        self.status_code = status_code


class OpenAICompatibleProtocolError(OpenAICompatibleUpstreamError):
    """Malformed or incomplete OpenAI-compatible response."""


class OpenAICompatibleProviderAdapter:
    """Execute normalized chat requests through an admitted OpenAI endpoint."""

    name = "openai_compatible"

    def __init__(
        self,
        profile: OpenAICompatibleUpstreamProfile,
        *,
        credential: str | None,
        authorize_network: OpenAICompatibleNetworkAuthorizer,
        http_client: httpx.AsyncClient | None = None,
        ssl_context: ssl.SSLContext | bool | None = None,
    ) -> None:
        if not isinstance(profile, OpenAICompatibleUpstreamProfile):
            raise TypeError("OpenAI-compatible profile is invalid")
        if profile.credential_reference_id is not None and not credential:
            raise ValueError("referenced OpenAI-compatible credential is unresolved")
        if profile.credential_reference_id is None and credential is not None:
            raise ValueError("unreferenced OpenAI-compatible credential is forbidden")
        if not callable(authorize_network):
            raise TypeError("OpenAI-compatible network authorizer is required")
        if (
            profile.tls_policy_ref is not None or profile.proxy_policy_ref is not None
        ) and http_client is None:
            raise ValueError(
                "reviewed TLS or proxy policy requires an injected HTTP client"
            )
        self.profile = profile
        self._credential = credential
        self._authorize_network = authorize_network
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(profile.timeout_seconds),
            verify=True if ssl_context is None else ssl_context,
            follow_redirects=False,
            trust_env=False,
        )

    def __repr__(self) -> str:
        return (
            "OpenAICompatibleProviderAdapter("
            f"profile={self.profile.id!r}, revision={self.profile.revision!r}, "
            "credential=<referenced>)"
        )

    def __gpt2giga_redacted__(self) -> dict[str, Any]:
        """Return a content-free runtime projection."""
        return {
            "profile_id": self.profile.id,
            "profile_revision": self.profile.revision,
            "credential_reference_id": self.profile.credential_reference_id,
            "network_policy_ref": self.profile.network_policy_ref,
        }

    async def __aenter__(self) -> OpenAICompatibleProviderAdapter:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close only the internally owned HTTP client."""
        if self._owns_client:
            await self._client.aclose()

    async def complete(
        self,
        request: NormalizedChatRequest,
        *,
        downstream: DownstreamProtocol,
        downstream_capabilities: Collection[BridgeFeature] = (),
        input_token_count: int | None = None,
    ) -> NormalizedResponse:
        """Execute one admitted non-streaming Chat Completions request."""
        if request.stream:
            raise ValueError("complete() requires a non-streaming request")
        admission = self._admit(
            request,
            downstream=downstream,
            downstream_capabilities=downstream_capabilities,
            input_token_count=input_token_count,
        )
        payload = normalized_chat_to_openai_compatible_payload(request)
        response = await self._request_json(
            url=self.profile.chat_completions_url,
            method="POST",
            purpose=_REQUEST_PURPOSE_CHAT,
            payload=payload,
        )
        return openai_compatible_response_to_normalized(
            response,
            profile=self.profile,
            admission=admission,
        )

    async def stream_chat(
        self,
        request: NormalizedChatRequest,
        *,
        downstream: DownstreamProtocol,
        downstream_capabilities: Collection[BridgeFeature] = (),
        input_token_count: int | None = None,
        is_disconnected: Callable[[], Any] | None = None,
    ) -> AsyncGenerator[NormalizedStreamEvent, None]:
        """Execute one admitted streaming Chat Completions request."""
        if not request.stream:
            raise ValueError("stream_chat() requires request.stream=true")
        admission = self._admit(
            request,
            downstream=downstream,
            downstream_capabilities=downstream_capabilities,
            input_token_count=input_token_count,
        )
        payload = normalized_chat_to_openai_compatible_payload(request)
        sequence = 0
        terminal_choices: set[int] = set()
        started_tool_calls: set[tuple[int, int]] = set()
        saw_done = False

        yield NormalizedStreamEvent(
            type="message_start",
            sequence=sequence,
            model=None,
            provider_metadata=_response_provider_metadata(
                self.profile,
                admission=admission,
            ),
        )
        sequence += 1
        try:
            async for chunk in self._stream_json(
                url=self.profile.chat_completions_url,
                purpose=_REQUEST_PURPOSE_CHAT,
                payload=payload,
            ):
                if chunk is None:
                    saw_done = True
                    break
                if await _is_disconnected(is_disconnected):
                    yield NormalizedStreamEvent(
                        type="cancelled",
                        sequence=sequence,
                        cancellation=request.cancellation,
                        stop_reason="cancelled",
                    )
                    return
                for event in _chunk_to_events(
                    chunk,
                    sequence=sequence,
                    started_tool_calls=started_tool_calls,
                    terminal_choices=terminal_choices,
                ):
                    sequence = (event.sequence or sequence) + 1
                    yield event
        except asyncio.CancelledError:
            raise
        except OpenAICompatibleUpstreamError as exc:
            yield NormalizedStreamEvent(
                type="error",
                sequence=sequence,
                error=exc.error,
                stop_reason="error",
            )
            return

        if not saw_done or not terminal_choices:
            raise _protocol_error(
                "incomplete_stream", "Upstream stream was incomplete."
            )

    async def discover_models(self) -> tuple[str, ...]:
        """Return strict bounded model ids without inferring capabilities."""
        payload = await self._request_json(
            url=self.profile.models_url,
            method="GET",
            purpose=_REQUEST_PURPOSE_MODELS,
            payload=None,
        )
        return parse_openai_compatible_models(payload)

    def _admit(
        self,
        request: NormalizedChatRequest,
        *,
        downstream: DownstreamProtocol,
        downstream_capabilities: Collection[BridgeFeature],
        input_token_count: int | None,
    ) -> ProtocolBridgeAdmission:
        if request.model != self.profile.model:
            raise ValueError(
                "normalized request model does not match the admitted route"
            )
        return admit_protocol_bridge_request(
            request,
            downstream=downstream,
            upstream=self.profile.capabilities,
            downstream_capabilities=downstream_capabilities,
            input_token_count=input_token_count,
        )

    async def _request_json(
        self,
        *,
        url: str,
        method: Literal["GET", "POST"],
        purpose: str,
        payload: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        body = _json_body(payload)
        authorization = self._authorize(url, method, purpose, body)
        try:
            async with self._client.stream(
                method,
                url,
                content=body or None,
                headers=self._headers(has_body=bool(body)),
            ) as response:
                self._validate_peer(response, authorization)
                content = await _read_bounded_response(response, authorization)
                if response.is_error:
                    raise _http_error(response, content)
        except httpx.TimeoutException as exc:
            raise _transport_error("timeout", "Upstream request timed out.") from exc
        except httpx.RequestError as exc:
            raise _transport_error(
                "connection_error",
                "Upstream connection failed.",
            ) from exc
        try:
            parsed = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _protocol_error(
                "invalid_json_response",
                "Upstream returned invalid JSON.",
            ) from exc
        if not isinstance(parsed, Mapping):
            raise _protocol_error(
                "invalid_json_response",
                "Upstream JSON response must be an object.",
            )
        return parsed

    async def _stream_json(
        self,
        *,
        url: str,
        purpose: str,
        payload: Mapping[str, Any],
    ) -> AsyncGenerator[Mapping[str, Any] | None, None]:
        body = _json_body(payload)
        authorization = self._authorize(url, "POST", purpose, body)
        total_bytes = 0
        buffer = b""
        try:
            async with self._client.stream(
                "POST",
                url,
                content=body,
                headers=self._headers(has_body=True),
            ) as response:
                self._validate_peer(response, authorization)
                if response.is_error:
                    content = await _read_bounded_response(response, authorization)
                    raise _http_error(response, content)
                async for chunk in response.aiter_bytes():
                    total_bytes += len(chunk)
                    if total_bytes > authorization.max_response_bytes:
                        raise _transport_error(
                            "response_too_large",
                            "Upstream response exceeded the reviewed limit.",
                        )
                    buffer += chunk
                    while True:
                        block, buffer = _pop_sse_block(buffer)
                        if block is None:
                            break
                        raw_event = _sse_data(block)
                        if raw_event is None:
                            continue
                        if raw_event == b"[DONE]":
                            authorization.validate_response_body(body_bytes=total_bytes)
                            yield None
                            return
                        try:
                            parsed = json.loads(raw_event)
                        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                            raise _protocol_error(
                                "invalid_stream_json",
                                "Upstream stream contained invalid JSON.",
                            ) from exc
                        if not isinstance(parsed, Mapping):
                            raise _protocol_error(
                                "invalid_stream_chunk",
                                "Upstream stream chunk must be an object.",
                            )
                        yield parsed
                authorization.validate_response_body(body_bytes=total_bytes)
        except asyncio.CancelledError:
            raise
        except OpenAICompatibleUpstreamError:
            raise
        except httpx.TimeoutException as exc:
            raise _transport_error("timeout", "Upstream stream timed out.") from exc
        except httpx.RequestError as exc:
            raise _transport_error(
                "connection_error",
                "Upstream stream connection failed.",
            ) from exc

    def _authorize(
        self,
        url: str,
        method: Literal["GET", "POST"],
        purpose: str,
        body: bytes,
    ) -> OpenAICompatibleNetworkAuthorization:
        digest = hashlib.sha256(body).hexdigest() if body else None
        intent = OpenAICompatibleNetworkIntent(
            url=url,
            method=method,
            purpose=purpose,
            request_body_bytes=len(body),
            request_body_sha256=digest,
            max_response_bytes=self.profile.max_response_bytes,
        )
        authorization = self._authorize_network(intent)
        if authorization.max_response_bytes != self.profile.max_response_bytes:
            raise ValueError("network authorization changed the response limit")
        authorization.validate_request_body(
            body_bytes=len(body),
            body_sha256=digest,
        )
        return authorization

    def _headers(self, *, has_body: bool) -> dict[str, str]:
        headers = {"Accept": "text/event-stream, application/json"}
        if has_body:
            headers["Content-Type"] = "application/json"
        if self._credential is not None:
            headers["Authorization"] = f"Bearer {self._credential}"
        return headers

    @staticmethod
    def _validate_peer(
        response: httpx.Response,
        authorization: OpenAICompatibleNetworkAuthorization,
    ) -> None:
        if not authorization.peer_validation_required:
            return
        address = _response_peer_address(response)
        if address is None:
            raise _transport_error(
                "peer_evidence_unavailable",
                "Upstream transport peer evidence is unavailable.",
            )
        authorization.validate_connected_peer(address)


def normalized_chat_to_openai_compatible_payload(
    request: NormalizedChatRequest,
) -> dict[str, Any]:
    """Serialize only the admitted normalized v1 Chat Completions subset."""
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": [_message_to_openai(message) for message in request.messages],
        "stream": request.stream,
    }
    if request.stream:
        payload["stream_options"] = {"include_usage": True}
    if request.user is not None:
        payload["user"] = request.user
    if request.metadata:
        payload["metadata"] = dict(request.metadata)
    if request.tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    **(
                        {"description": tool.description}
                        if tool.description is not None
                        else {}
                    ),
                    "parameters": dict(tool.parameters),
                },
            }
            for tool in request.tools
        ]
    if request.tool_choice is not None:
        payload["tool_choice"] = request.tool_choice
    if request.parallel_tool_calls is not None:
        payload["parallel_tool_calls"] = request.parallel_tool_calls
    if request.response_format is not None:
        payload["response_format"] = {
            "type": request.response_format.type,
            "json_schema": request.response_format.json_schema,
        }
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
    return payload


def openai_compatible_response_to_normalized(
    payload: Mapping[str, Any],
    *,
    profile: OpenAICompatibleUpstreamProfile,
    admission: ProtocolBridgeAdmission,
) -> NormalizedResponse:
    """Normalize a strict OpenAI-compatible non-streaming response."""
    choices_value = payload.get("choices")
    if not isinstance(choices_value, list):
        raise _protocol_error(
            "invalid_choices",
            "Upstream response choices must be a list.",
        )
    choices: list[NormalizedChoice] = []
    for raw_choice in choices_value:
        if not isinstance(raw_choice, Mapping):
            raise _protocol_error(
                "invalid_choice",
                "Upstream response choice must be an object.",
            )
        message = raw_choice.get("message")
        if not isinstance(message, Mapping):
            raise _protocol_error(
                "invalid_message",
                "Upstream response message must be an object.",
            )
        finish_reason = _optional_string(raw_choice.get("finish_reason"))
        choices.append(
            NormalizedChoice(
                index=_integer(raw_choice.get("index"), default=len(choices)),
                message=_response_message(message),
                finish_reason=finish_reason,
                stop_reason=_normalize_stop_reason(finish_reason),
            )
        )
    return NormalizedResponse(
        id=_optional_string(payload.get("id")),
        created_at=_created_at(payload.get("created")),
        model=_optional_string(payload.get("model")),
        provider=profile.id,
        choices=choices,
        usage=_usage(payload.get("usage")),
        provider_metadata=_response_provider_metadata(
            profile,
            admission=admission,
            system_fingerprint=_optional_string(payload.get("system_fingerprint")),
        ),
    )


def parse_openai_compatible_models(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Parse the bounded standard model-list response."""
    if payload.get("object") != "list":
        raise _protocol_error(
            "invalid_models_response",
            "Upstream models response object must be list.",
        )
    data = payload.get("data")
    if not isinstance(data, list) or len(data) > MAX_MODEL_DISCOVERY_ITEMS:
        raise _protocol_error(
            "invalid_models_response",
            "Upstream models response is invalid or too large.",
        )
    models: set[str] = set()
    for item in data:
        if not isinstance(item, Mapping):
            raise _protocol_error(
                "invalid_model",
                "Upstream model entry must be an object.",
            )
        model_id = item.get("id")
        if (
            not isinstance(model_id, str)
            or not model_id.strip()
            or len(model_id.strip()) > MAX_MODEL_ID_CHARS
            or any(ord(character) < 32 for character in model_id)
        ):
            raise _protocol_error(
                "invalid_model",
                "Upstream model id is invalid.",
            )
        models.add(model_id.strip())
    return tuple(sorted(models))


def _message_to_openai(message: NormalizedMessage) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": message.role}
    if isinstance(message.content, list):
        payload["content"] = [_content_part_to_openai(part) for part in message.content]
    else:
        payload["content"] = message.content
    if message.name is not None:
        payload["name"] = message.name
    if message.tool_call_id is not None:
        payload["tool_call_id"] = message.tool_call_id
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": call.arguments,
                },
            }
            for call in message.tool_calls
        ]
    return payload


def _content_part_to_openai(part: NormalizedContentPart) -> dict[str, Any]:
    if part.type == "text":
        return {"type": "text", "text": part.text}
    reference = part.image_reference
    if part.type == "image_reference" and reference is not None:
        image_url: dict[str, Any] = {"url": reference.uri}
        if reference.detail is not None:
            image_url["detail"] = reference.detail
        return {"type": "image_url", "image_url": image_url}
    raise ValueError("content part is outside admitted normalized v1")


def _response_message(payload: Mapping[str, Any]) -> NormalizedMessage:
    tool_calls_value = payload.get("tool_calls")
    tool_calls = (
        [_response_tool_call(item) for item in tool_calls_value]
        if isinstance(tool_calls_value, list)
        else []
    )
    content = payload.get("content")
    if content is not None and not isinstance(content, str):
        raise _protocol_error(
            "invalid_message_content",
            "Upstream response message content must be text or null.",
        )
    return NormalizedMessage(
        role=_optional_string(payload.get("role")) or "assistant",
        content=content,
        tool_calls=tool_calls,
    )


def _response_tool_call(payload: Any) -> NormalizedToolCall:
    if not isinstance(payload, Mapping):
        raise _protocol_error(
            "invalid_tool_call",
            "Upstream tool call must be an object.",
        )
    function = payload.get("function")
    if not isinstance(function, Mapping):
        raise _protocol_error(
            "invalid_tool_call",
            "Upstream tool call function must be an object.",
        )
    return NormalizedToolCall(
        id=_optional_string(payload.get("id")),
        type=_optional_string(payload.get("type")) or "function",
        name=_optional_string(function.get("name")),
        arguments=function.get("arguments"),
    )


def _chunk_to_events(
    payload: Mapping[str, Any],
    *,
    sequence: int,
    started_tool_calls: set[tuple[int, int]],
    terminal_choices: set[int],
) -> list[NormalizedStreamEvent]:
    events: list[NormalizedStreamEvent] = []
    choices = payload.get("choices")
    if not isinstance(choices, list):
        raise _protocol_error(
            "invalid_stream_choices",
            "Upstream stream choices must be a list.",
        )
    model = _optional_string(payload.get("model"))
    for raw_choice in choices:
        if not isinstance(raw_choice, Mapping):
            raise _protocol_error(
                "invalid_stream_choice",
                "Upstream stream choice must be an object.",
            )
        choice_index = _integer(raw_choice.get("index"), default=0)
        delta = raw_choice.get("delta")
        if not isinstance(delta, Mapping):
            raise _protocol_error(
                "invalid_stream_delta",
                "Upstream stream delta must be an object.",
            )
        content = delta.get("content")
        if content is not None:
            if not isinstance(content, str):
                raise _protocol_error(
                    "invalid_stream_content",
                    "Upstream stream content delta must be text.",
                )
            events.append(
                NormalizedStreamEvent(
                    type="content_delta",
                    sequence=sequence + len(events),
                    choice_index=choice_index,
                    model=model,
                    content_delta=content,
                )
            )
        raw_tool_calls = delta.get("tool_calls")
        if raw_tool_calls is not None:
            if not isinstance(raw_tool_calls, list):
                raise _protocol_error(
                    "invalid_stream_tool_calls",
                    "Upstream stream tool calls must be a list.",
                )
            for fallback_index, raw_call in enumerate(raw_tool_calls):
                call = _stream_tool_call(raw_call)
                call_index = (
                    _integer(raw_call.get("index"), default=fallback_index)
                    if isinstance(raw_call, Mapping)
                    else fallback_index
                )
                key = (choice_index, call_index)
                event_type = (
                    "tool_call_delta"
                    if key in started_tool_calls
                    else "tool_call_start"
                )
                started_tool_calls.add(key)
                events.append(
                    NormalizedStreamEvent(
                        type=event_type,
                        sequence=sequence + len(events),
                        choice_index=choice_index,
                        model=model,
                        tool_call=call,
                    )
                )
        finish_reason = _optional_string(raw_choice.get("finish_reason"))
        if finish_reason is not None:
            if choice_index in terminal_choices:
                raise _protocol_error(
                    "duplicate_stream_terminal",
                    "Upstream stream repeated a terminal choice.",
                )
            terminal_choices.add(choice_index)
            events.append(
                NormalizedStreamEvent(
                    type="message_end",
                    sequence=sequence + len(events),
                    choice_index=choice_index,
                    model=model,
                    finish_reason=finish_reason,
                    stop_reason=_normalize_stop_reason(finish_reason),
                )
            )
    usage = _usage(payload.get("usage"))
    if usage is not None:
        events.append(
            NormalizedStreamEvent(
                type="usage",
                sequence=sequence + len(events),
                model=model,
                usage=usage,
            )
        )
    return events


def _stream_tool_call(payload: Any) -> NormalizedToolCall:
    if not isinstance(payload, Mapping):
        raise _protocol_error(
            "invalid_stream_tool_call",
            "Upstream stream tool call must be an object.",
        )
    function = payload.get("function")
    function_payload = function if isinstance(function, Mapping) else {}
    return NormalizedToolCall(
        id=_optional_string(payload.get("id")),
        type=_optional_string(payload.get("type")) or "function",
        name=_optional_string(function_payload.get("name")),
        arguments=function_payload.get("arguments"),
    )


def _usage(payload: Any) -> NormalizedUsage | None:
    if payload is None:
        return None
    if not isinstance(payload, Mapping):
        raise _protocol_error(
            "invalid_usage",
            "Upstream usage must be an object.",
        )
    return NormalizedUsage(
        input_tokens=_optional_integer(payload.get("prompt_tokens")),
        output_tokens=_optional_integer(payload.get("completion_tokens")),
        total_tokens=_optional_integer(payload.get("total_tokens")),
    )


def _normalize_stop_reason(value: str | None) -> NormalizedStopReason | None:
    return {
        "stop": "stop",
        "length": "max_tokens",
        "tool_calls": "tool_calls",
        "function_call": "tool_calls",
        "content_filter": "content_filter",
    }.get(value)


def _response_provider_metadata(
    profile: OpenAICompatibleUpstreamProfile,
    *,
    admission: ProtocolBridgeAdmission,
    system_fingerprint: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "profile_id": profile.id,
        "profile_revision": profile.revision,
        "dialect": profile.dialect,
        "admission_schema_version": admission.schema_version,
    }
    if system_fingerprint is not None:
        payload["system_fingerprint"] = system_fingerprint
    return {"openai_compatible": payload}


def _json_body(payload: Mapping[str, Any] | None) -> bytes:
    if payload is None:
        return b""
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


async def _read_bounded_response(
    response: httpx.Response,
    authorization: OpenAICompatibleNetworkAuthorization,
) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > authorization.max_response_bytes:
            raise _transport_error(
                "response_too_large",
                "Upstream response exceeded the reviewed limit.",
            )
        chunks.append(chunk)
    authorization.validate_response_body(body_bytes=size)
    return b"".join(chunks)


def _pop_sse_block(buffer: bytes) -> tuple[bytes | None, bytes]:
    separators = (
        (buffer.find(b"\r\n\r\n"), 4),
        (buffer.find(b"\n\n"), 2),
        (buffer.find(b"\r\r"), 2),
    )
    found = [(index, length) for index, length in separators if index >= 0]
    if not found:
        return None, buffer
    index, length = min(found, key=lambda item: item[0])
    return buffer[:index], buffer[index + length :]


def _sse_data(block: bytes) -> bytes | None:
    data_lines: list[bytes] = []
    for line in block.replace(b"\r\n", b"\n").replace(b"\r", b"\n").split(b"\n"):
        if line.startswith(b":"):
            continue
        if line == b"data":
            data_lines.append(b"")
        elif line.startswith(b"data:"):
            data_lines.append(line[5:].lstrip())
    return b"\n".join(data_lines) if data_lines else None


def _http_error(
    response: httpx.Response, content: bytes
) -> OpenAICompatibleUpstreamError:
    message = f"Upstream returned HTTP {response.status_code}."
    error_type = "api_error"
    code: str | int | None = response.status_code
    param: str | None = None
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, Mapping):
        raw_error = payload.get("error")
        if isinstance(raw_error, Mapping):
            message = _optional_string(raw_error.get("message")) or message
            error_type = _optional_string(raw_error.get("type")) or error_type
            raw_code = raw_error.get("code")
            if isinstance(raw_code, (str, int)) and not isinstance(raw_code, bool):
                code = raw_code
            param = _optional_string(raw_error.get("param"))
    status = response.status_code
    error_class = (
        "authentication"
        if status == 401
        else "permission"
        if status == 403
        else "not_found"
        if status == 404
        else "timeout"
        if status in {408, 504}
        else "rate_limit"
        if status == 429
        else "upstream"
        if status >= 500
        else "invalid_request"
    )
    return OpenAICompatibleUpstreamError(
        NormalizedError(
            type=error_type,
            message=message,
            code=code,
            param=param,
            error_class=error_class,
            retryable=status in {408, 429} or status >= 500,
        ),
        status_code=status,
    )


def _transport_error(code: str, message: str) -> OpenAICompatibleUpstreamError:
    error_class = "timeout" if code == "timeout" else "upstream"
    return OpenAICompatibleUpstreamError(
        NormalizedError(
            type="transport_error",
            message=message,
            code=code,
            error_class=error_class,
            retryable=code in {"timeout", "connection_error"},
        )
    )


def _protocol_error(code: str, message: str) -> OpenAICompatibleProtocolError:
    return OpenAICompatibleProtocolError(
        NormalizedError(
            type="protocol_error",
            message=message,
            code=code,
            error_class="upstream",
            retryable=False,
        )
    )


def _response_peer_address(response: httpx.Response) -> str | None:
    stream = response.extensions.get("network_stream")
    get_extra_info = getattr(stream, "get_extra_info", None)
    if not callable(get_extra_info):
        return None
    server = get_extra_info("server_addr")
    if isinstance(server, tuple) and server:
        return str(server[0])
    if isinstance(server, str):
        return server
    return None


def _canonical_base_url(value: str) -> str:
    parsed = urlsplit(str(value).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("OpenAI-compatible base_url must be absolute HTTP(S)")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("OpenAI-compatible base_url cannot contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("OpenAI-compatible base_url cannot contain query or fragment")
    if parsed.scheme == "http" and parsed.hostname not in {
        "127.0.0.1",
        "::1",
        "localhost",
    }:
        raise ValueError("plain HTTP is allowed only for loopback endpoints")
    path = parsed.path.rstrip("/")
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            "",
            "",
        )
    )


def _endpoint_url(base_url: str, suffix: str) -> str:
    return urljoin(f"{base_url.rstrip('/')}/", suffix)


def _created_at(value: Any) -> datetime:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    return datetime.now(timezone.utc)


def _integer(value: Any, *, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


def _optional_integer(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    raise _protocol_error(
        "invalid_usage",
        "Upstream usage token counts must be non-negative integers.",
    )


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


async def _is_disconnected(callback: Callable[[], Any] | None) -> bool:
    if callback is None:
        return False
    result = callback()
    if hasattr(result, "__await__"):
        result = await result
    return bool(result)


def openai_compatible_profile(
    *,
    profile_id: str,
    revision: str,
    base_url: str,
    model: str,
    features: Collection[BridgeFeature],
    limits: NormalizedTokenLimits,
    network_policy_ref: str,
    credential_reference_id: str | None = None,
    tls_policy_ref: str | None = None,
    proxy_policy_ref: str | None = None,
    timeout_seconds: float = 30.0,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
) -> OpenAICompatibleUpstreamProfile:
    """Build an exact generic profile after explicit capability review."""
    capabilities = NormalizedProtocolCapabilities(
        profile=f"{profile_id}@{revision}",
        features=frozenset(features),
        limits=limits,
    )
    return OpenAICompatibleUpstreamProfile(
        id=profile_id,
        revision=revision,
        base_url=base_url,
        model=model,
        capabilities=capabilities,
        timeout_seconds=timeout_seconds,
        max_response_bytes=max_response_bytes,
        credential_reference_id=credential_reference_id,
        network_policy_ref=network_policy_ref,
        tls_policy_ref=tls_policy_ref,
        proxy_policy_ref=proxy_policy_ref,
    )
