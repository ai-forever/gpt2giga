"""Normalized Anthropic Messages upstream execution."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable, Collection, Mapping
from dataclasses import dataclass
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
    NormalizedTokenCountRequest,
    NormalizedTokenCountResponse,
    NormalizedTokenLimits,
    NormalizedToolCall,
    NormalizedUsage,
    ProtocolBridgeAdmission,
    admit_protocol_bridge_request,
)


ANTHROPIC_UPSTREAM_SCHEMA_VERSION = "gpt2giga.anthropic-upstream.v1"
ANTHROPIC_MESSAGES_DIALECT = "anthropic-messages-2023-06-01"
ANTHROPIC_MESSAGES_EXECUTION_OWNER = "provider-execution:anthropic"
ANTHROPIC_API_VERSION = "2023-06-01"
DEFAULT_MAX_RESPONSE_BYTES = 1024 * 1024
_REQUEST_PURPOSE_MESSAGES = "provider.anthropic.messages"
_REQUEST_PURPOSE_COUNT_TOKENS = "provider.anthropic.count-tokens"
_ANTHROPIC_ERROR_TYPES = frozenset(
    {
        "api_error",
        "authentication_error",
        "billing_error",
        "gateway_timeout_error",
        "invalid_request_error",
        "not_found_error",
        "overloaded_error",
        "permission_error",
        "rate_limit_error",
        "request_too_large",
    }
)

ANTHROPIC_IMPLEMENTED_FEATURES_V1 = frozenset(
    {
        BridgeFeature.ROLES,
        BridgeFeature.ORDERED_CONTENT_PARTS,
        BridgeFeature.TEXT,
        BridgeFeature.GENERATION_CONTROLS,
        BridgeFeature.FUNCTION_TOOLS,
        BridgeFeature.TOOL_CHOICE,
        BridgeFeature.PARALLEL_TOOL_CALLS,
        BridgeFeature.TOOL_RESULTS,
        BridgeFeature.STOP_REASON,
        BridgeFeature.USAGE,
        BridgeFeature.MODEL_IDENTITY,
        BridgeFeature.REQUEST_ERROR_CLASSES,
        BridgeFeature.CANCELLATION,
        BridgeFeature.CONTEXT_TOKEN_LIMITS,
        BridgeFeature.STREAM_DELTAS,
        BridgeFeature.STREAM_TERMINAL_EVENTS,
        BridgeFeature.COUNT_TOKENS,
    }
)


class AnthropicUpstreamProfile(NormalizedBaseModel):
    """Versioned Anthropic execution profile without credential values."""

    schema_version: Literal["gpt2giga.anthropic-upstream.v1"] = (
        ANTHROPIC_UPSTREAM_SCHEMA_VERSION
    )
    id: str = Field(min_length=1, max_length=256)
    revision: str = Field(min_length=1, max_length=256)
    dialect: Literal["anthropic-messages-2023-06-01"] = ANTHROPIC_MESSAGES_DIALECT
    base_url: str
    model: str = Field(min_length=1, max_length=256)
    capabilities: NormalizedProtocolCapabilities
    default_max_tokens: int = Field(default=1024, gt=0)
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
    def _validate_profile(self) -> AnthropicUpstreamProfile:
        if self.raw_extensions or self.provider_metadata:
            raise ValueError("Anthropic profile extensions are not admitted")
        if self.capabilities.profile != f"{self.id}@{self.revision}":
            raise ValueError("Anthropic capabilities do not bind the profile revision")
        if self.capabilities.raw_extensions or self.capabilities.provider_metadata:
            raise ValueError("Anthropic capability extensions are not admitted")
        unsupported = set(self.capabilities.features) - set(
            ANTHROPIC_IMPLEMENTED_FEATURES_V1
        )
        if unsupported:
            names = ", ".join(sorted(feature.value for feature in unsupported))
            raise ValueError(f"Anthropic profile claims unsupported features: {names}")
        streaming = {
            BridgeFeature.STREAM_DELTAS,
            BridgeFeature.STREAM_TERMINAL_EVENTS,
        }
        claimed_streaming = set(self.capabilities.features) & streaming
        if claimed_streaming and claimed_streaming != streaming:
            raise ValueError(
                "Anthropic streaming capabilities must be enabled together"
            )
        max_output_tokens = (
            self.capabilities.limits.max_output_tokens
            if self.capabilities.limits is not None
            else None
        )
        if (
            max_output_tokens is not None
            and self.default_max_tokens > max_output_tokens
        ):
            raise ValueError("Anthropic default_max_tokens exceeds the profile limit")
        return self

    @property
    def messages_url(self) -> str:
        """Return the exact Messages endpoint."""
        return _endpoint_url(self.base_url, "v1/messages")

    @property
    def count_tokens_url(self) -> str:
        """Return the exact Messages token-count endpoint."""
        return _endpoint_url(self.base_url, "v1/messages/count_tokens")


@dataclass(frozen=True)
class AnthropicNetworkIntent:
    """Exact outbound request intent presented to a network-grant owner."""

    url: str
    method: Literal["POST"]
    purpose: str
    request_body_bytes: int
    request_body_sha256: str
    max_response_bytes: int


class AnthropicNetworkAuthorization(Protocol):
    """Validated network ticket used at the final transport boundary."""

    max_response_bytes: int
    peer_validation_required: bool

    def validate_request_body(
        self,
        *,
        body_bytes: int,
        body_sha256: str,
    ) -> None:
        """Reject a body that differs from the reviewed request."""

    def validate_connected_peer(self, address: str) -> None:
        """Reject a transport peer that differs from pre-connect resolution."""

    def validate_response_body(self, *, body_bytes: int) -> None:
        """Reject a response larger than the reviewed ceiling."""


AnthropicNetworkAuthorizer = Callable[
    [AnthropicNetworkIntent], AnthropicNetworkAuthorization
]


class AnthropicUpstreamError(RuntimeError):
    """Stable normalized Anthropic upstream failure."""

    def __init__(self, error: NormalizedError, *, status_code: int | None = None):
        super().__init__(error.message)
        self.error = error
        self.status_code = status_code


class AnthropicProtocolError(AnthropicUpstreamError):
    """Malformed or semantically incomplete Anthropic response."""


class AnthropicUnsupportedSemanticError(ValueError):
    """Normalized request field that Anthropic cannot preserve exactly."""

    def __init__(self, param: str, detail: str):
        self.param = param
        self.code = "unsupported_semantic"
        super().__init__(f"{param}: {detail}")


class AnthropicProviderAdapter:
    """Execute normalized chat requests through an admitted Anthropic profile."""

    name = "anthropic"

    def __init__(
        self,
        profile: AnthropicUpstreamProfile,
        *,
        credential: str | None,
        authorize_network: AnthropicNetworkAuthorizer,
        http_client: httpx.AsyncClient | None = None,
        ssl_context: ssl.SSLContext | bool | None = None,
    ) -> None:
        if not isinstance(profile, AnthropicUpstreamProfile):
            raise TypeError("Anthropic profile is invalid")
        if profile.credential_reference_id is not None and not credential:
            raise ValueError("referenced Anthropic credential is unresolved")
        if profile.credential_reference_id is None and credential is not None:
            raise ValueError("unreferenced Anthropic credential is forbidden")
        if not callable(authorize_network):
            raise TypeError("Anthropic network authorizer is required")
        if (
            profile.tls_policy_ref is not None or profile.proxy_policy_ref is not None
        ) and http_client is None:
            raise ValueError(
                "reviewed TLS or proxy policy requires an injected HTTP client"
            )
        if http_client is not None and http_client.follow_redirects:
            raise ValueError("Anthropic HTTP client must disable redirects")
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
            "AnthropicProviderAdapter("
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

    async def __aenter__(self) -> AnthropicProviderAdapter:
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
        """Execute one admitted non-streaming Messages request."""
        if request.stream:
            raise ValueError("complete() requires a non-streaming request")
        admission = self._admit(
            request,
            downstream=downstream,
            downstream_capabilities=downstream_capabilities,
            input_token_count=input_token_count,
        )
        payload = normalized_chat_to_anthropic_payload(request, profile=self.profile)
        response = await self._request_json(
            url=self.profile.messages_url,
            purpose=_REQUEST_PURPOSE_MESSAGES,
            payload=payload,
        )
        return anthropic_response_to_normalized(
            response,
            profile=self.profile,
            admission=admission,
        )

    async def count_tokens(
        self,
        request: NormalizedTokenCountRequest,
        *,
        downstream: DownstreamProtocol,
        downstream_capabilities: Collection[BridgeFeature] = (),
        input_token_count: int | None = None,
    ) -> NormalizedTokenCountResponse:
        """Execute only the explicit normalized count-tokens operation."""
        requested_models = {
            model for model in (request.model, request.input.model) if model is not None
        }
        if requested_models != {self.profile.model}:
            raise ValueError(
                "normalized token-count model does not match the admitted Anthropic route"
            )
        admit_protocol_bridge_request(
            request,
            downstream=downstream,
            upstream=self.profile.capabilities,
            downstream_capabilities=downstream_capabilities,
            input_token_count=input_token_count,
        )
        payload = normalized_token_count_to_anthropic_payload(
            request,
            profile=self.profile,
        )
        response = await self._request_json(
            url=self.profile.count_tokens_url,
            purpose=_REQUEST_PURPOSE_COUNT_TOKENS,
            payload=payload,
        )
        return NormalizedTokenCountResponse(
            model=self.profile.model,
            input_tokens=_non_negative_integer(
                response.get("input_tokens"),
                "input_tokens",
            ),
            limits=self.profile.capabilities.limits,
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
        """Execute one admitted streaming Messages request."""
        if not request.stream:
            raise ValueError("stream_chat() requires request.stream=true")
        admission = self._admit(
            request,
            downstream=downstream,
            downstream_capabilities=downstream_capabilities,
            input_token_count=input_token_count,
        )
        payload = normalized_chat_to_anthropic_payload(request, profile=self.profile)
        sequence = 0
        message_id: str | None = None
        response_model: str | None = None
        initial_usage: Mapping[str, Any] | None = None
        active_blocks: dict[int, dict[str, Any]] = {}
        closed_blocks: set[int] = set()
        pending_end: (
            tuple[
                str,
                NormalizedStopReason,
                NormalizedUsage,
                str | None,
            ]
            | None
        ) = None
        started = False
        terminal_emitted = False

        if await _is_disconnected(is_disconnected):
            yield NormalizedStreamEvent(
                type="message_start",
                model=self.profile.model,
                sequence=sequence,
                message=NormalizedMessage(role="assistant", content=[]),
                provider_metadata=_response_provider_metadata(
                    self.profile,
                    admission=admission,
                    stop_sequence=None,
                ),
            )
            sequence += 1
            yield NormalizedStreamEvent(
                type="cancelled",
                model=self.profile.model,
                sequence=sequence,
                cancellation=request.cancellation,
                stop_reason="cancelled",
            )
            return
        try:
            async for raw_event in self._stream_events(
                url=self.profile.messages_url,
                purpose=_REQUEST_PURPOSE_MESSAGES,
                payload=payload,
            ):
                event_type = _required_string(raw_event.get("type"), field="type")
                if terminal_emitted:
                    raise _protocol_error(
                        "stream_data_after_terminal",
                        "Anthropic stream continued after message_stop.",
                    )
                if event_type != "message_start" and await _is_disconnected(
                    is_disconnected
                ):
                    yield NormalizedStreamEvent(
                        type="cancelled",
                        id=message_id,
                        model=response_model,
                        sequence=sequence,
                        cancellation=request.cancellation,
                        stop_reason="cancelled",
                    )
                    return

                if event_type == "message_start":
                    if started:
                        raise _protocol_error(
                            "duplicate_message_start",
                            "Anthropic stream repeated message_start.",
                        )
                    message = raw_event.get("message")
                    if not isinstance(message, Mapping):
                        raise _protocol_error(
                            "invalid_message_start",
                            "Anthropic message_start must contain a message.",
                        )
                    if (
                        message.get("type") != "message"
                        or message.get("role") != "assistant"
                    ):
                        raise _protocol_error(
                            "invalid_message_start",
                            "Anthropic stream must start with an assistant message.",
                        )
                    response_model = _required_string(
                        message.get("model"), field="message.model"
                    )
                    if response_model != self.profile.model:
                        raise _protocol_error(
                            "model_mismatch",
                            "Anthropic stream model differs from the admitted route.",
                        )
                    message_id = _required_string(message.get("id"), field="message.id")
                    initial_usage_value = message.get("usage")
                    if not isinstance(initial_usage_value, Mapping):
                        raise _protocol_error(
                            "invalid_usage",
                            "Anthropic message_start usage must be an object.",
                        )
                    initial_usage = initial_usage_value
                    started = True
                    yield NormalizedStreamEvent(
                        type="message_start",
                        id=message_id,
                        model=response_model,
                        sequence=sequence,
                        message=NormalizedMessage(role="assistant", content=[]),
                        provider_metadata=_response_provider_metadata(
                            self.profile,
                            admission=admission,
                            stop_sequence=None,
                        ),
                    )
                    sequence += 1
                    continue

                if not started:
                    raise _protocol_error(
                        "event_before_message_start",
                        "Anthropic stream event preceded message_start.",
                    )
                if event_type == "ping":
                    yield NormalizedStreamEvent(
                        type="heartbeat",
                        id=message_id,
                        model=response_model,
                        sequence=sequence,
                    )
                    sequence += 1
                    continue
                if event_type == "content_block_start":
                    index = _stream_index(raw_event)
                    if index in active_blocks or index in closed_blocks:
                        raise _protocol_error(
                            "duplicate_content_block",
                            "Anthropic stream repeated a content block index.",
                        )
                    block = raw_event.get("content_block")
                    if not isinstance(block, Mapping):
                        raise _protocol_error(
                            "invalid_content_block",
                            "Anthropic content_block_start must contain a block.",
                        )
                    block_type = _required_string(
                        block.get("type"), field="content_block.type"
                    )
                    state = {"type": block_type}
                    if block_type == "text":
                        initial_text = block.get("text", "")
                        if not isinstance(initial_text, str):
                            raise _protocol_error(
                                "invalid_text_block",
                                "Anthropic text block must contain text.",
                            )
                        active_blocks[index] = state
                        if initial_text:
                            yield NormalizedStreamEvent(
                                type="content_delta",
                                id=message_id,
                                model=response_model,
                                sequence=sequence,
                                content_delta=initial_text,
                            )
                            sequence += 1
                    elif block_type == "tool_use":
                        tool_id = _required_string(
                            block.get("id"), field="content_block.id"
                        )
                        tool_name = _required_string(
                            block.get("name"), field="content_block.name"
                        )
                        initial_input = block.get("input", {})
                        if not isinstance(initial_input, Mapping):
                            raise _protocol_error(
                                "invalid_tool_input",
                                "Anthropic tool block input must be an object.",
                            )
                        state.update(
                            {
                                "id": tool_id,
                                "name": tool_name,
                                "initial_input": dict(initial_input),
                                "json_parts": [],
                            }
                        )
                        active_blocks[index] = state
                        yield NormalizedStreamEvent(
                            type="tool_call_start",
                            id=message_id,
                            model=response_model,
                            sequence=sequence,
                            tool_call=NormalizedToolCall(
                                id=tool_id,
                                name=tool_name,
                                arguments=(
                                    dict(initial_input) if initial_input else None
                                ),
                                raw_extensions={"index": index},
                            ),
                        )
                        sequence += 1
                    else:
                        raise _protocol_error(
                            "unsupported_content_block",
                            f"Anthropic stream block {block_type!r} is not admitted.",
                        )
                    continue
                if event_type == "content_block_delta":
                    index = _stream_index(raw_event)
                    state = active_blocks.get(index)
                    if state is None:
                        raise _protocol_error(
                            "delta_without_content_block",
                            "Anthropic content delta has no active block.",
                        )
                    delta = raw_event.get("delta")
                    if not isinstance(delta, Mapping):
                        raise _protocol_error(
                            "invalid_content_delta",
                            "Anthropic content delta must be an object.",
                        )
                    delta_type = _required_string(delta.get("type"), field="delta.type")
                    if state["type"] == "text" and delta_type == "text_delta":
                        yield NormalizedStreamEvent(
                            type="content_delta",
                            id=message_id,
                            model=response_model,
                            sequence=sequence,
                            content_delta=_required_text(
                                delta.get("text"), field="delta.text"
                            ),
                        )
                    elif (
                        state["type"] == "tool_use" and delta_type == "input_json_delta"
                    ):
                        if state["initial_input"]:
                            raise _protocol_error(
                                "duplicate_tool_input",
                                "Anthropic tool input cannot mix initial and delta values.",
                            )
                        partial_json = _required_text(
                            delta.get("partial_json"),
                            field="delta.partial_json",
                        )
                        state["json_parts"].append(partial_json)
                        yield NormalizedStreamEvent(
                            type="tool_call_delta",
                            id=message_id,
                            model=response_model,
                            sequence=sequence,
                            tool_call=NormalizedToolCall(
                                arguments=partial_json,
                                raw_extensions={"index": index},
                            ),
                        )
                    else:
                        raise _protocol_error(
                            "content_delta_type_mismatch",
                            "Anthropic content delta does not match its active block.",
                        )
                    sequence += 1
                    continue
                if event_type == "content_block_stop":
                    index = _stream_index(raw_event)
                    state = active_blocks.get(index)
                    if state is None:
                        raise _protocol_error(
                            "stop_without_content_block",
                            "Anthropic content block stopped without being active.",
                        )
                    if state["type"] == "tool_use" and state["json_parts"]:
                        try:
                            tool_input = json.loads("".join(state["json_parts"]))
                        except json.JSONDecodeError as exc:
                            raise _protocol_error(
                                "invalid_stream_tool_input",
                                "Anthropic tool input deltas do not form valid JSON.",
                            ) from exc
                        if not isinstance(tool_input, Mapping):
                            raise _protocol_error(
                                "invalid_stream_tool_input",
                                "Anthropic streamed tool input must be an object.",
                            )
                    del active_blocks[index]
                    closed_blocks.add(index)
                    continue
                if event_type == "message_delta":
                    if active_blocks:
                        raise _protocol_error(
                            "message_delta_before_block_stop",
                            "Anthropic message_delta preceded content block stop.",
                        )
                    if pending_end is not None:
                        raise _protocol_error(
                            "duplicate_message_delta",
                            "Anthropic stream repeated its terminal message_delta.",
                        )
                    delta = raw_event.get("delta")
                    if not isinstance(delta, Mapping):
                        raise _protocol_error(
                            "invalid_message_delta",
                            "Anthropic message_delta must contain a delta.",
                        )
                    raw_stop_reason = _required_string(
                        delta.get("stop_reason"), field="delta.stop_reason"
                    )
                    normalized_stop_reason = _normalize_stop_reason(raw_stop_reason)
                    refusal_category = _refusal_category(
                        raw_stop_reason,
                        delta.get("stop_details"),
                    )
                    usage = _stream_usage(initial_usage, raw_event.get("usage"))
                    yield NormalizedStreamEvent(
                        type="usage",
                        id=message_id,
                        model=response_model,
                        sequence=sequence,
                        usage=usage,
                    )
                    sequence += 1
                    pending_end = (
                        raw_stop_reason,
                        normalized_stop_reason,
                        usage,
                        refusal_category,
                    )
                    continue
                if event_type == "message_stop":
                    if pending_end is None:
                        raise _protocol_error(
                            "message_stop_without_delta",
                            "Anthropic message_stop requires a terminal message_delta.",
                        )
                    (
                        raw_stop_reason,
                        normalized_stop_reason,
                        usage,
                        refusal_category,
                    ) = pending_end
                    metadata = {"anthropic_stop_reason": raw_stop_reason}
                    if refusal_category is not None:
                        metadata["anthropic_refusal_category"] = refusal_category
                    yield NormalizedStreamEvent(
                        type="message_end",
                        id=message_id,
                        model=response_model,
                        sequence=sequence,
                        finish_reason=normalized_stop_reason,
                        stop_reason=normalized_stop_reason,
                        usage=usage,
                        metadata=metadata,
                    )
                    sequence += 1
                    terminal_emitted = True
                    continue
                if event_type == "error":
                    raise _stream_error(raw_event)
                raise _protocol_error(
                    "unknown_stream_event",
                    f"Anthropic stream event {event_type!r} is not admitted.",
                )
        except asyncio.CancelledError:
            raise
        except AnthropicUpstreamError as exc:
            if terminal_emitted:
                raise
            yield NormalizedStreamEvent(
                type="error",
                id=message_id,
                model=response_model,
                sequence=sequence,
                error=exc.error,
                stop_reason="error",
            )
            return

        if not terminal_emitted:
            yield NormalizedStreamEvent(
                type="error",
                id=message_id,
                model=response_model,
                sequence=sequence,
                error=_protocol_error(
                    "incomplete_stream",
                    "Anthropic stream ended before message_stop.",
                ).error,
                stop_reason="error",
            )

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
                "normalized request model does not match the admitted Anthropic route"
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
        purpose: str,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        body = _json_body(payload)
        authorization = self._authorize(url, purpose, body)
        try:
            async with self._client.stream(
                "POST",
                url,
                content=body,
                headers=self._headers(),
            ) as response:
                self._validate_peer(response, authorization)
                content = await _read_bounded_response(response, authorization)
                if response.is_error:
                    raise _http_error(response, content)
        except httpx.TimeoutException as exc:
            raise _transport_error("timeout", "Anthropic request timed out.") from exc
        except httpx.RequestError as exc:
            raise _transport_error(
                "connection_error",
                "Anthropic connection failed.",
            ) from exc
        try:
            parsed = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _protocol_error(
                "invalid_json_response",
                "Anthropic returned invalid JSON.",
            ) from exc
        if not isinstance(parsed, Mapping):
            raise _protocol_error(
                "invalid_json_response",
                "Anthropic JSON response must be an object.",
            )
        return parsed

    async def _stream_events(
        self,
        *,
        url: str,
        purpose: str,
        payload: Mapping[str, Any],
    ) -> AsyncGenerator[Mapping[str, Any], None]:
        body = _json_body(payload)
        authorization = self._authorize(url, purpose, body)
        try:
            async with self._client.stream(
                "POST",
                url,
                content=body,
                headers={**self._headers(), "Accept": "text/event-stream"},
            ) as response:
                self._validate_peer(response, authorization)
                if response.is_error:
                    content = await _read_bounded_response(response, authorization)
                    raise _http_error(response, content)
                buffer = b""
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > authorization.max_response_bytes:
                        raise _transport_error(
                            "response_too_large",
                            "Anthropic stream exceeded the reviewed limit.",
                        )
                    buffer += chunk
                    while True:
                        block, buffer = _pop_sse_block(buffer)
                        if block is None:
                            break
                        event = _parse_sse_block(block)
                        if event is not None:
                            yield event
                if buffer.strip():
                    event = _parse_sse_block(buffer)
                    if event is not None:
                        yield event
                authorization.validate_response_body(body_bytes=size)
        except httpx.TimeoutException as exc:
            raise _transport_error("timeout", "Anthropic stream timed out.") from exc
        except httpx.RequestError as exc:
            raise _transport_error(
                "connection_error",
                "Anthropic stream connection failed.",
            ) from exc

    def _authorize(
        self,
        url: str,
        purpose: str,
        body: bytes,
    ) -> AnthropicNetworkAuthorization:
        digest = hashlib.sha256(body).hexdigest()
        intent = AnthropicNetworkIntent(
            url=url,
            method="POST",
            purpose=purpose,
            request_body_bytes=len(body),
            request_body_sha256=digest,
            max_response_bytes=self.profile.max_response_bytes,
        )
        authorization = self._authorize_network(intent)
        if authorization.max_response_bytes > self.profile.max_response_bytes:
            raise ValueError("network grant exceeds the Anthropic profile ceiling")
        authorization.validate_request_body(
            body_bytes=len(body),
            body_sha256=digest,
        )
        return authorization

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Anthropic-Version": ANTHROPIC_API_VERSION,
        }
        if self._credential is not None:
            headers["X-Api-Key"] = self._credential
        return headers

    @staticmethod
    def _validate_peer(
        response: httpx.Response,
        authorization: AnthropicNetworkAuthorization,
    ) -> None:
        if not authorization.peer_validation_required:
            return
        address = _response_peer_address(response)
        if address is None:
            raise _transport_error(
                "peer_evidence_unavailable",
                "Anthropic transport peer evidence is unavailable.",
            )
        authorization.validate_connected_peer(address)


def normalized_chat_to_anthropic_payload(
    request: NormalizedChatRequest,
    *,
    profile: AnthropicUpstreamProfile,
) -> dict[str, Any]:
    """Serialize only the admitted normalized v1 Anthropic subset."""
    system, messages = _messages_to_anthropic(request.messages)
    generation = request.generation_config
    for field in ("presence_penalty", "frequency_penalty", "seed"):
        if getattr(generation, field) is not None:
            raise AnthropicUnsupportedSemanticError(
                f"generation_config.{field}",
                "Anthropic Messages has no exact representation.",
            )
    if request.response_format is not None:
        raise AnthropicUnsupportedSemanticError(
            "response_format",
            "structured output is not admitted by the Anthropic v1 profile yet.",
        )

    payload: dict[str, Any] = {
        "model": profile.model,
        "messages": messages,
        "max_tokens": generation.max_tokens or profile.default_max_tokens,
        "stream": request.stream,
    }
    if system:
        payload["system"] = system
    if request.tools:
        payload["tools"] = _tools_to_anthropic(request)
    tool_choice = _tool_choice_to_anthropic(
        request.tool_choice,
        parallel_tool_calls=request.parallel_tool_calls,
    )
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    if generation.temperature is not None:
        payload["temperature"] = generation.temperature
    if generation.top_p is not None:
        payload["top_p"] = generation.top_p
    if generation.stop is not None:
        payload["stop_sequences"] = (
            [generation.stop]
            if isinstance(generation.stop, str)
            else list(generation.stop)
        )
    metadata = _metadata_to_anthropic(request)
    if metadata:
        payload["metadata"] = metadata
    return payload


def normalized_token_count_to_anthropic_payload(
    request: NormalizedTokenCountRequest,
    *,
    profile: AnthropicUpstreamProfile,
) -> dict[str, Any]:
    """Serialize only the explicit Anthropic count-tokens operation."""
    chat = request.input
    system, messages = _messages_to_anthropic(chat.messages)
    payload: dict[str, Any] = {
        "model": profile.model,
        "messages": messages,
    }
    if system:
        payload["system"] = system
    if chat.tools:
        payload["tools"] = _tools_to_anthropic(chat)
    tool_choice = _tool_choice_to_anthropic(
        chat.tool_choice,
        parallel_tool_calls=chat.parallel_tool_calls,
    )
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    return payload


def _tools_to_anthropic(request: NormalizedChatRequest) -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            **(
                {"description": tool.description}
                if tool.description is not None
                else {}
            ),
            "input_schema": dict(tool.parameters),
        }
        for tool in request.tools
    ]


def anthropic_response_to_normalized(
    payload: Mapping[str, Any],
    *,
    profile: AnthropicUpstreamProfile,
    admission: ProtocolBridgeAdmission,
) -> NormalizedResponse:
    """Normalize a strict Anthropic non-streaming Messages response."""
    if payload.get("type") != "message" or payload.get("role") != "assistant":
        raise _protocol_error(
            "invalid_message",
            "Anthropic response must be an assistant message.",
        )
    response_model = _required_string(payload.get("model"), field="model")
    if response_model != profile.model:
        raise _protocol_error(
            "model_mismatch",
            "Anthropic response model differs from the admitted route.",
        )
    content = payload.get("content")
    if not isinstance(content, list):
        raise _protocol_error(
            "invalid_content",
            "Anthropic response content must be a list.",
        )
    message = _response_message(content)
    finish_reason = _required_string(payload.get("stop_reason"), field="stop_reason")
    stop_reason = _normalize_stop_reason(finish_reason)
    refusal_category = _refusal_category(
        finish_reason,
        payload.get("stop_details"),
    )
    usage = _usage(payload.get("usage"))
    return NormalizedResponse(
        id=_required_string(payload.get("id"), field="id"),
        model=response_model,
        provider=profile.id,
        choices=[
            NormalizedChoice(
                index=0,
                message=message,
                finish_reason=finish_reason,
                stop_reason=stop_reason,
            )
        ],
        usage=usage,
        provider_metadata=_response_provider_metadata(
            profile,
            admission=admission,
            stop_sequence=_optional_string(payload.get("stop_sequence")),
            refusal_category=refusal_category,
        ),
    )


def _messages_to_anthropic(
    normalized: list[NormalizedMessage],
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    system: list[dict[str, str]] = []
    messages: list[dict[str, Any]] = []
    saw_conversation = False
    for index, message in enumerate(normalized):
        if message.role == "system":
            if saw_conversation:
                raise AnthropicUnsupportedSemanticError(
                    f"messages[{index}].role",
                    "Anthropic system instructions must precede conversation turns.",
                )
            system.extend(_text_blocks(message.content, path=f"messages[{index}]"))
            continue
        saw_conversation = True
        if message.role == "user":
            blocks = _text_blocks(message.content, path=f"messages[{index}]")
            _append_turn(messages, "user", blocks)
        elif message.role == "assistant":
            blocks = _text_blocks(message.content, path=f"messages[{index}]")
            for call_index, call in enumerate(message.tool_calls):
                if not call.id or not call.name:
                    raise AnthropicUnsupportedSemanticError(
                        f"messages[{index}].tool_calls[{call_index}]",
                        "Anthropic tool use requires exact id and name values.",
                    )
                arguments = call.arguments
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError as exc:
                        raise AnthropicUnsupportedSemanticError(
                            f"messages[{index}].tool_calls[{call_index}].arguments",
                            "Anthropic tool input must be a JSON object.",
                        ) from exc
                if not isinstance(arguments, Mapping):
                    raise AnthropicUnsupportedSemanticError(
                        f"messages[{index}].tool_calls[{call_index}].arguments",
                        "Anthropic tool input must be a JSON object.",
                    )
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call.id,
                        "name": call.name,
                        "input": dict(arguments),
                    }
                )
            _append_turn(messages, "assistant", blocks)
        elif message.role == "tool":
            if not message.tool_call_id:
                raise AnthropicUnsupportedSemanticError(
                    f"messages[{index}].tool_call_id",
                    "Anthropic tool results require the original tool-use id.",
                )
            _append_turn(
                messages,
                "user",
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": message.tool_call_id,
                        "content": _content_text(
                            message.content,
                            path=f"messages[{index}]",
                        ),
                    }
                ],
            )
        else:
            raise AnthropicUnsupportedSemanticError(
                f"messages[{index}].role",
                "role is outside the Anthropic Messages contract.",
            )
    return system, messages


def _text_blocks(
    value: str | list[NormalizedContentPart] | None,
    *,
    path: str,
) -> list[dict[str, str]]:
    if isinstance(value, str):
        return [{"type": "text", "text": value}]
    if value is None:
        return []
    blocks: list[dict[str, str]] = []
    for index, part in enumerate(value):
        if part.type != "text" or part.text is None:
            raise AnthropicUnsupportedSemanticError(
                f"{path}.content[{index}]",
                "only text content is admitted by this Anthropic profile.",
            )
        blocks.append({"type": "text", "text": part.text})
    return blocks


def _content_text(
    value: str | list[NormalizedContentPart] | None,
    *,
    path: str,
) -> str:
    return "\n".join(block["text"] for block in _text_blocks(value, path=path))


def _append_turn(
    messages: list[dict[str, Any]],
    role: Literal["user", "assistant"],
    blocks: list[dict[str, Any]],
) -> None:
    if messages and messages[-1]["role"] == role:
        messages[-1]["content"].extend(blocks)
        return
    messages.append({"role": role, "content": blocks})


def _tool_choice_to_anthropic(
    value: Any,
    *,
    parallel_tool_calls: bool | None,
) -> dict[str, Any] | None:
    disable_parallel = None if parallel_tool_calls is None else not parallel_tool_calls
    choice: dict[str, Any] | None
    if value is None:
        choice = {"type": "auto"} if disable_parallel is not None else None
    elif value == "auto":
        choice = {"type": "auto"}
    elif value == "none":
        choice = {"type": "none"}
    elif value == "required":
        choice = {"type": "any"}
    elif isinstance(value, Mapping):
        function = value.get("function")
        name = function.get("name") if isinstance(function, Mapping) else None
        if value.get("type") != "function" or not isinstance(name, str) or not name:
            raise AnthropicUnsupportedSemanticError(
                "tool_choice",
                "named Anthropic tool choice requires one function name.",
            )
        choice = {"type": "tool", "name": name}
    else:
        raise AnthropicUnsupportedSemanticError(
            "tool_choice",
            "tool choice is outside the normalized v1 subset.",
        )
    if choice is not None and disable_parallel is not None:
        choice["disable_parallel_tool_use"] = disable_parallel
    return choice


def _metadata_to_anthropic(request: NormalizedChatRequest) -> dict[str, str]:
    metadata = dict(request.metadata)
    user_id = metadata.pop("user_id", None)
    if request.user is not None:
        if user_id is not None and user_id != request.user:
            raise AnthropicUnsupportedSemanticError(
                "metadata.user_id",
                "conflicts with the normalized user value.",
            )
        user_id = request.user
    if metadata:
        raise AnthropicUnsupportedSemanticError(
            "metadata",
            "only Anthropic metadata.user_id is admitted.",
        )
    if user_id is None:
        return {}
    if not isinstance(user_id, str) or not user_id:
        raise AnthropicUnsupportedSemanticError(
            "metadata.user_id",
            "must be a non-empty string.",
        )
    return {"user_id": user_id}


def _response_message(content: list[Any]) -> NormalizedMessage:
    parts: list[NormalizedContentPart] = []
    tool_calls: list[NormalizedToolCall] = []
    for index, block in enumerate(content):
        if not isinstance(block, Mapping):
            raise _protocol_error(
                "invalid_content_block",
                "Anthropic content block must be an object.",
            )
        block_type = block.get("type")
        if block_type == "text":
            parts.append(
                NormalizedContentPart(
                    type="text",
                    text=_required_string(
                        block.get("text"), field=f"content[{index}].text"
                    ),
                )
            )
        elif block_type == "tool_use":
            arguments = block.get("input")
            if not isinstance(arguments, Mapping):
                raise _protocol_error(
                    "invalid_tool_input",
                    "Anthropic tool input must be an object.",
                )
            tool_calls.append(
                NormalizedToolCall(
                    id=_required_string(block.get("id"), field=f"content[{index}].id"),
                    name=_required_string(
                        block.get("name"),
                        field=f"content[{index}].name",
                    ),
                    arguments=dict(arguments),
                )
            )
        else:
            raise _protocol_error(
                "unsupported_content_block",
                f"Anthropic content block {block_type!r} is not admitted.",
            )
    return NormalizedMessage(role="assistant", content=parts, tool_calls=tool_calls)


def _usage(value: Any) -> NormalizedUsage:
    if not isinstance(value, Mapping):
        raise _protocol_error("invalid_usage", "Anthropic usage must be an object.")
    uncached_input_tokens = _non_negative_integer(
        value.get("input_tokens"), "input_tokens"
    )
    output_tokens = _non_negative_integer(value.get("output_tokens"), "output_tokens")
    cache_creation_input_tokens = _optional_non_negative_integer(
        value.get("cache_creation_input_tokens"),
        "cache_creation_input_tokens",
    )
    cache_read_input_tokens = _optional_non_negative_integer(
        value.get("cache_read_input_tokens"),
        "cache_read_input_tokens",
    )
    input_tokens = (
        uncached_input_tokens
        + (cache_creation_input_tokens or 0)
        + (cache_read_input_tokens or 0)
    )
    facts: dict[str, Any] = {
        "input_tokens": uncached_input_tokens,
        "output_tokens": output_tokens,
    }
    if cache_creation_input_tokens is not None:
        facts["cache_creation_input_tokens"] = cache_creation_input_tokens
    if cache_read_input_tokens is not None:
        facts["cache_read_input_tokens"] = cache_read_input_tokens
    service_tier = value.get("service_tier")
    if service_tier is not None:
        if service_tier not in {"standard", "priority", "batch"}:
            raise _protocol_error(
                "invalid_usage",
                "Anthropic usage service_tier is invalid.",
            )
        facts["service_tier"] = service_tier
    return NormalizedUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        provider_metadata={"anthropic": facts},
    )


def _stream_usage(
    initial: Mapping[str, Any] | None,
    final: Any,
) -> NormalizedUsage:
    if initial is None or not isinstance(final, Mapping):
        raise _protocol_error(
            "invalid_usage",
            "Anthropic stream usage is incomplete.",
        )
    merged = dict(initial)
    merged.update({key: value for key, value in final.items() if value is not None})
    return _usage(merged)


def _normalize_stop_reason(value: str) -> NormalizedStopReason:
    normalized = {
        "end_turn": "stop",
        "stop_sequence": "stop",
        "max_tokens": "max_tokens",
        "model_context_window_exceeded": "max_tokens",
        "tool_use": "tool_calls",
        "pause_turn": "stop",
        "refusal": "content_filter",
    }.get(value)
    if normalized is None:
        raise _protocol_error(
            "invalid_stop_reason",
            "Anthropic response contains an unknown stop reason.",
        )
    return normalized


def _response_provider_metadata(
    profile: AnthropicUpstreamProfile,
    *,
    admission: ProtocolBridgeAdmission,
    stop_sequence: str | None,
    refusal_category: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "profile_id": profile.id,
        "profile_revision": profile.revision,
        "dialect": profile.dialect,
        "admission_schema_version": admission.schema_version,
    }
    if stop_sequence is not None:
        payload["stop_sequence"] = stop_sequence
    if refusal_category is not None:
        payload["refusal_category"] = refusal_category
    return {"anthropic": payload}


def _refusal_category(stop_reason: str, value: Any) -> str | None:
    if value is None:
        return None
    if stop_reason != "refusal" or not isinstance(value, Mapping):
        raise _protocol_error(
            "invalid_stop_details",
            "Anthropic stop_details is valid only for a refusal.",
        )
    if value.get("type") != "refusal":
        raise _protocol_error(
            "invalid_stop_details",
            "Anthropic refusal stop_details has an invalid type.",
        )
    category = value.get("category")
    if category is None:
        return None
    if category not in {
        "cyber",
        "bio",
        "frontier_llm",
        "reasoning_extraction",
        "general_harms",
    }:
        raise _protocol_error(
            "invalid_stop_details",
            "Anthropic refusal category is invalid.",
        )
    return category


def _stream_index(event: Mapping[str, Any]) -> int:
    value = event.get("index")
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    raise _protocol_error(
        "invalid_content_block_index",
        "Anthropic stream block index must be a non-negative integer.",
    )


def _stream_error(event: Mapping[str, Any]) -> AnthropicUpstreamError:
    raw_error = event.get("error")
    if not isinstance(raw_error, Mapping):
        return _protocol_error(
            "invalid_stream_error",
            "Anthropic stream error must contain an error object.",
        )
    error_type = _anthropic_error_type(raw_error.get("type"))
    message = f"Anthropic stream returned {error_type}."
    error_class = (
        "authentication"
        if error_type == "authentication_error"
        else "permission"
        if error_type == "permission_error"
        else "not_found"
        if error_type == "not_found_error"
        else "rate_limit"
        if error_type == "rate_limit_error"
        else "upstream"
        if error_type == "overloaded_error"
        else "invalid_request"
        if error_type == "invalid_request_error"
        else "upstream"
    )
    return AnthropicUpstreamError(
        NormalizedError(
            type=error_type,
            message=message,
            code=error_type,
            error_class=error_class,
            retryable=error_type
            in {"rate_limit_error", "overloaded_error", "api_error"},
        )
    )


def _json_body(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


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


def _parse_sse_block(block: bytes) -> Mapping[str, Any] | None:
    event_name: str | None = None
    data_lines: list[bytes] = []
    for line in block.replace(b"\r\n", b"\n").replace(b"\r", b"\n").split(b"\n"):
        if line.startswith(b":"):
            continue
        if line.startswith(b"event:"):
            try:
                event_name = line[6:].strip().decode("utf-8")
            except UnicodeDecodeError as exc:
                raise _protocol_error(
                    "invalid_stream_event",
                    "Anthropic stream event name is not UTF-8.",
                ) from exc
        elif line == b"data":
            data_lines.append(b"")
        elif line.startswith(b"data:"):
            data_lines.append(line[5:].lstrip())
    if not data_lines:
        return None
    try:
        payload = json.loads(b"\n".join(data_lines))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _protocol_error(
            "invalid_stream_json",
            "Anthropic stream data is not valid JSON.",
        ) from exc
    if not isinstance(payload, Mapping):
        raise _protocol_error(
            "invalid_stream_event",
            "Anthropic stream data must be an object.",
        )
    payload_type = payload.get("type")
    if event_name and event_name != payload_type:
        raise _protocol_error(
            "stream_event_type_mismatch",
            "Anthropic SSE event name differs from its payload type.",
        )
    return payload


async def _read_bounded_response(
    response: httpx.Response,
    authorization: AnthropicNetworkAuthorization,
) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > authorization.max_response_bytes:
            raise _transport_error(
                "response_too_large",
                "Anthropic response exceeded the reviewed limit.",
            )
        chunks.append(chunk)
    authorization.validate_response_body(body_bytes=size)
    return b"".join(chunks)


def _http_error(response: httpx.Response, content: bytes) -> AnthropicUpstreamError:
    status = response.status_code
    error_type = "api_error"
    request_id = response.headers.get("request-id")
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, Mapping):
        raw_error = payload.get("error")
        if isinstance(raw_error, Mapping):
            error_type = _anthropic_error_type(raw_error.get("type"))
        request_id = _optional_string(payload.get("request_id")) or request_id
    message = f"Anthropic returned {error_type} (HTTP {status})."
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
        if status == 529
        else "upstream"
        if status >= 500
        else "invalid_request"
    )
    provider_metadata: dict[str, Any] = {"anthropic": {"http_status": status}}
    request_id = _bounded_identifier(request_id)
    if request_id is not None:
        provider_metadata["anthropic"]["request_id"] = request_id
    return AnthropicUpstreamError(
        NormalizedError(
            type=error_type,
            message=message,
            code=error_type,
            error_class=error_class,
            retryable=status in {408, 409, 429, 529} or status >= 500,
            provider_metadata=provider_metadata,
        ),
        status_code=status,
    )


def _transport_error(code: str, message: str) -> AnthropicUpstreamError:
    return AnthropicUpstreamError(
        NormalizedError(
            type="transport_error",
            message=message,
            code=code,
            error_class="timeout" if code == "timeout" else "upstream",
            retryable=code in {"timeout", "connection_error"},
        )
    )


def _protocol_error(code: str, message: str) -> AnthropicProtocolError:
    return AnthropicProtocolError(
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
        raise ValueError("Anthropic base_url must be absolute HTTP(S)")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Anthropic base_url cannot contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("Anthropic base_url cannot contain query or fragment")
    if parsed.scheme == "http" and parsed.hostname not in {
        "127.0.0.1",
        "::1",
        "localhost",
    }:
        raise ValueError("plain HTTP is allowed only for loopback endpoints")
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            "",
            "",
        )
    )


def _endpoint_url(base_url: str, suffix: str) -> str:
    return urljoin(f"{base_url.rstrip('/')}/", suffix)


def _required_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise _protocol_error(
            "invalid_message",
            f"Anthropic response field {field} must be a non-empty string.",
        )
    return value


def _required_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise _protocol_error(
            "invalid_content_delta",
            f"Anthropic stream field {field} must be text.",
        )
    return value


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _anthropic_error_type(value: Any) -> str:
    return value if value in _ANTHROPIC_ERROR_TYPES else "api_error"


def _bounded_identifier(value: Any) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 256:
        return None
    if any(ord(character) < 32 for character in value):
        return None
    return value


def _non_negative_integer(value: Any, field: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    raise _protocol_error(
        "invalid_usage",
        f"Anthropic usage field {field} must be a non-negative integer.",
    )


def _optional_non_negative_integer(value: Any, field: str) -> int | None:
    if value is None:
        return None
    return _non_negative_integer(value, field)


async def _is_disconnected(callback: Callable[[], Any] | None) -> bool:
    if callback is None:
        return False
    result = callback()
    if hasattr(result, "__await__"):
        result = await result
    return bool(result)


def anthropic_profile(
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
    default_max_tokens: int = 1024,
    timeout_seconds: float = 30.0,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
) -> AnthropicUpstreamProfile:
    """Build an exact Anthropic profile after explicit capability review."""
    capabilities = NormalizedProtocolCapabilities(
        profile=f"{profile_id}@{revision}",
        features=frozenset(features),
        limits=limits,
    )
    return AnthropicUpstreamProfile(
        id=profile_id,
        revision=revision,
        base_url=base_url,
        model=model,
        capabilities=capabilities,
        default_max_tokens=default_max_tokens,
        timeout_seconds=timeout_seconds,
        max_response_bytes=max_response_bytes,
        credential_reference_id=credential_reference_id,
        network_policy_ref=network_policy_ref,
        tls_policy_ref=tls_policy_ref,
        proxy_policy_ref=proxy_policy_ref,
    )
