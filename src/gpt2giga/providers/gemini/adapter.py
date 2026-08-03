"""Normalized Gemini GenerateContent upstream execution."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable, Collection, Mapping
from dataclasses import dataclass
import asyncio
import base64
import binascii
import hashlib
import json
import ssl
from typing import Any, Literal, Protocol
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

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


GEMINI_UPSTREAM_SCHEMA_VERSION = "gigaloom.gemini-upstream.v1"
GEMINI_GENERATE_CONTENT_DIALECT = "gemini-generate-content-v1beta"
GEMINI_EXECUTION_OWNER = "provider-execution:gemini"
DEFAULT_MAX_RESPONSE_BYTES = 1024 * 1024
DEFAULT_MAX_INLINE_IMAGE_BYTES = 4 * 1024 * 1024
_REQUEST_PURPOSE_GENERATE = "provider.gemini.generate-content"
_KNOWN_ERROR_STATUSES = frozenset(
    {
        "ABORTED",
        "ALREADY_EXISTS",
        "CANCELLED",
        "DATA_LOSS",
        "DEADLINE_EXCEEDED",
        "FAILED_PRECONDITION",
        "INTERNAL",
        "INVALID_ARGUMENT",
        "NOT_FOUND",
        "OUT_OF_RANGE",
        "PERMISSION_DENIED",
        "RESOURCE_EXHAUSTED",
        "UNAUTHENTICATED",
        "UNAVAILABLE",
        "UNIMPLEMENTED",
        "UNKNOWN",
    }
)


class GeminiUpstreamProfile(NormalizedBaseModel):
    """Versioned Gemini execution profile without credential values."""

    schema_version: Literal["gigaloom.gemini-upstream.v1"] = (
        GEMINI_UPSTREAM_SCHEMA_VERSION
    )
    id: str = Field(min_length=1, max_length=256)
    revision: str = Field(min_length=1, max_length=256)
    dialect: Literal["gemini-generate-content-v1beta"] = GEMINI_GENERATE_CONTENT_DIALECT
    base_url: str
    model: str = Field(min_length=1, max_length=256)
    capabilities: NormalizedProtocolCapabilities
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    max_response_bytes: int = Field(
        default=DEFAULT_MAX_RESPONSE_BYTES,
        gt=0,
        le=16 * 1024 * 1024,
    )
    max_inline_image_bytes: int = Field(
        default=DEFAULT_MAX_INLINE_IMAGE_BYTES,
        gt=0,
        le=16 * 1024 * 1024,
    )
    allowed_inline_image_mime_types: frozenset[str] = Field(
        default_factory=lambda: frozenset(
            {"image/gif", "image/jpeg", "image/png", "image/webp"}
        )
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

    @field_validator("allowed_inline_image_mime_types")
    @classmethod
    def _validate_image_mime_types(cls, value: frozenset[str]) -> frozenset[str]:
        if not value or any(not item.startswith("image/") for item in value):
            raise ValueError("Gemini inline MIME types must be non-empty image types")
        return value

    @model_validator(mode="after")
    def _validate_profile(self) -> GeminiUpstreamProfile:
        if self.raw_extensions or self.provider_metadata:
            raise ValueError("Gemini upstream profile extensions are not admitted")
        if self.capabilities.profile != f"{self.id}@{self.revision}":
            raise ValueError("Gemini capabilities do not bind the profile revision")
        if self.capabilities.raw_extensions or self.capabilities.provider_metadata:
            raise ValueError("Gemini capability extensions are not admitted")
        return self

    @property
    def generate_content_url(self) -> str:
        """Return the exact reviewed GenerateContent endpoint."""
        model = quote(self.model, safe="-._~")
        return _endpoint_url(self.base_url, f"models/{model}:generateContent")

    @property
    def stream_generate_content_url(self) -> str:
        """Return the exact reviewed streaming GenerateContent endpoint."""
        model = quote(self.model, safe="-._~")
        endpoint = _endpoint_url(self.base_url, f"models/{model}:streamGenerateContent")
        return f"{endpoint}?alt=sse"


@dataclass(frozen=True)
class GeminiNetworkIntent:
    """Exact outbound request intent presented to the network-policy owner."""

    url: str
    method: Literal["POST"]
    purpose: str
    request_body_bytes: int
    request_body_sha256: str
    max_response_bytes: int


class GeminiNetworkAuthorization(Protocol):
    """Validated network ticket used at the final transport boundary."""

    max_response_bytes: int
    peer_validation_required: bool

    def validate_request_body(self, *, body_bytes: int, body_sha256: str) -> None:
        """Reject a body that differs from the reviewed intent."""

    def validate_connected_peer(self, address: str) -> None:
        """Reject a connected peer outside the reviewed address set."""

    def validate_response_body(self, *, body_bytes: int) -> None:
        """Reject a response outside the reviewed byte ceiling."""


GeminiNetworkAuthorizer = Callable[[GeminiNetworkIntent], GeminiNetworkAuthorization]


class GeminiUpstreamError(RuntimeError):
    """Stable normalized Gemini upstream failure."""

    def __init__(self, error: NormalizedError, *, status_code: int | None = None):
        super().__init__(error.message)
        self.error = error
        self.status_code = status_code


class GeminiProtocolError(GeminiUpstreamError):
    """Malformed or incomplete Gemini response."""


def _verified_ssl_context(
    value: ssl.SSLContext | bool | None,
) -> ssl.SSLContext | Literal[True]:
    """Return only TLS settings that verify certificates and hostnames."""
    if value is None or value is True:
        return True
    if value is False:
        raise ValueError("Gemini TLS certificate verification cannot be disabled")
    if not isinstance(value, ssl.SSLContext):
        raise TypeError("Gemini TLS context is invalid")
    if value.verify_mode != ssl.CERT_REQUIRED or not value.check_hostname:
        raise ValueError("Gemini TLS context must verify certificates and hostnames")
    return value


class GeminiProviderAdapter:
    """Execute normalized chat requests through one admitted Gemini profile."""

    name = "gemini"

    def __init__(
        self,
        profile: GeminiUpstreamProfile,
        *,
        credential: str | None,
        authorize_network: GeminiNetworkAuthorizer,
        http_client: httpx.AsyncClient | None = None,
        ssl_context: ssl.SSLContext | bool | None = None,
    ) -> None:
        if not isinstance(profile, GeminiUpstreamProfile):
            raise TypeError("Gemini profile is invalid")
        if profile.credential_reference_id is not None and not credential:
            raise ValueError("referenced Gemini credential is unresolved")
        if profile.credential_reference_id is None and credential is not None:
            raise ValueError("unreferenced Gemini credential is forbidden")
        if not callable(authorize_network):
            raise TypeError("Gemini network authorizer is required")
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
            verify=_verified_ssl_context(ssl_context),
            follow_redirects=False,
            trust_env=False,
        )

    def __repr__(self) -> str:
        return (
            "GeminiProviderAdapter("
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

    async def __aenter__(self) -> GeminiProviderAdapter:
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
        """Execute one admitted non-streaming GenerateContent request."""
        if request.stream:
            raise ValueError("complete() requires a non-streaming request")
        admission = self._admit(
            request,
            downstream=downstream,
            downstream_capabilities=downstream_capabilities,
            input_token_count=input_token_count,
        )
        payload = normalized_chat_to_gemini_payload(request, profile=self.profile)
        response = await self._request_json(
            url=self.profile.generate_content_url,
            purpose=_REQUEST_PURPOSE_GENERATE,
            payload=payload,
        )
        return gemini_response_to_normalized(
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
        """Execute one admitted streaming GenerateContent request."""
        if not request.stream:
            raise ValueError("stream_chat() requires request.stream=true")
        admission = self._admit(
            request,
            downstream=downstream,
            downstream_capabilities=downstream_capabilities,
            input_token_count=input_token_count,
        )
        payload = normalized_chat_to_gemini_payload(request, profile=self.profile)
        sequence = 0
        terminal_seen = False
        usage_seen = False
        started_tool_calls: set[str] = set()
        pending_terminal_events: list[NormalizedStreamEvent] = []

        yield _stream_event(
            "message_start",
            sequence=sequence,
            provider_metadata=_response_provider_metadata(
                self.profile,
                admission=admission,
            ),
        )
        sequence += 1
        if await _is_disconnected(is_disconnected):
            yield _stream_event(
                "cancelled",
                sequence=sequence,
                cancellation=request.cancellation,
                stop_reason="cancelled",
            )
            return
        try:
            async for chunk in self._stream_json(
                url=self.profile.stream_generate_content_url,
                purpose=_REQUEST_PURPOSE_GENERATE,
                payload=payload,
            ):
                if await _is_disconnected(is_disconnected):
                    yield _stream_event(
                        "cancelled",
                        sequence=sequence,
                        cancellation=request.cancellation,
                        stop_reason="cancelled",
                    )
                    return
                events, chunk_terminal, chunk_usage = _stream_chunk_to_events(
                    chunk,
                    sequence=sequence,
                    terminal_seen=terminal_seen,
                    usage_seen=usage_seen,
                    started_tool_calls=started_tool_calls,
                )
                terminal_seen = terminal_seen or chunk_terminal
                usage_seen = usage_seen or chunk_usage
                for event in events:
                    sequence = (event.sequence or sequence) + 1
                    if event.type in {"message_end", "usage"}:
                        pending_terminal_events.append(event)
                    else:
                        yield event
            if not terminal_seen:
                raise _protocol_error(
                    "incomplete_stream",
                    "Gemini upstream stream ended without a terminal state.",
                )
        except asyncio.CancelledError:
            raise
        except GeminiUpstreamError as exc:
            yield _stream_event(
                "error",
                sequence=sequence,
                error=exc.error,
                stop_reason="error",
            )
            return
        for event in pending_terminal_events:
            yield event

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
                if response.is_redirect:
                    raise _transport_error(
                        "destination_mismatch",
                        "Gemini upstream redirect is forbidden.",
                    )
                if response.is_error:
                    raise _http_error(response, content)
        except httpx.TimeoutException as exc:
            raise _transport_error(
                "timeout", "Gemini upstream request timed out."
            ) from exc
        except httpx.RequestError as exc:
            raise _transport_error(
                "connection_error",
                "Gemini upstream connection failed.",
            ) from exc
        try:
            parsed = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _protocol_error(
                "invalid_json_response",
                "Gemini upstream returned invalid JSON.",
            ) from exc
        if not isinstance(parsed, Mapping):
            raise _protocol_error(
                "invalid_json_response",
                "Gemini upstream JSON response must be an object.",
            )
        return parsed

    async def _stream_json(
        self,
        *,
        url: str,
        purpose: str,
        payload: Mapping[str, Any],
    ) -> AsyncGenerator[Mapping[str, Any], None]:
        body = _json_body(payload)
        authorization = self._authorize(url, purpose, body)
        total_bytes = 0
        buffer = b""
        try:
            async with self._client.stream(
                "POST",
                url,
                content=body,
                headers=self._headers(stream=True),
            ) as response:
                self._validate_peer(response, authorization)
                if response.is_redirect:
                    await _read_bounded_response(response, authorization)
                    raise _transport_error(
                        "destination_mismatch",
                        "Gemini upstream redirect is forbidden.",
                    )
                if response.is_error:
                    content = await _read_bounded_response(response, authorization)
                    raise _http_error(response, content)
                async for chunk in response.aiter_bytes():
                    total_bytes += len(chunk)
                    if total_bytes > authorization.max_response_bytes:
                        raise _transport_error(
                            "response_too_large",
                            "Gemini upstream response exceeded the reviewed limit.",
                        )
                    buffer += chunk
                    while True:
                        block, buffer = _pop_sse_block(buffer)
                        if block is None:
                            break
                        parsed = _parse_sse_block(block)
                        if parsed is not None:
                            yield parsed
                if buffer.strip():
                    parsed = _parse_sse_block(buffer)
                    if parsed is not None:
                        yield parsed
                authorization.validate_response_body(body_bytes=total_bytes)
        except asyncio.CancelledError:
            raise
        except GeminiUpstreamError:
            raise
        except httpx.TimeoutException as exc:
            raise _transport_error(
                "timeout", "Gemini upstream stream timed out."
            ) from exc
        except httpx.RequestError as exc:
            raise _transport_error(
                "connection_error",
                "Gemini upstream stream connection failed.",
            ) from exc

    def _authorize(
        self,
        url: str,
        purpose: str,
        body: bytes,
    ) -> GeminiNetworkAuthorization:
        digest = hashlib.sha256(body).hexdigest()
        intent = GeminiNetworkIntent(
            url=url,
            method="POST",
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

    def _headers(self, *, stream: bool = False) -> dict[str, str]:
        headers = {
            "Accept": "text/event-stream" if stream else "application/json",
            "Content-Type": "application/json",
        }
        if self._credential is not None:
            headers["x-goog-api-key"] = self._credential
        return headers

    @staticmethod
    def _validate_peer(
        response: httpx.Response,
        authorization: GeminiNetworkAuthorization,
    ) -> None:
        if not authorization.peer_validation_required:
            return
        address = _response_peer_address(response)
        if address is None:
            raise _transport_error(
                "peer_evidence_unavailable",
                "Gemini upstream transport peer evidence is unavailable.",
            )
        authorization.validate_connected_peer(address)


def normalized_chat_to_gemini_payload(
    request: NormalizedChatRequest,
    *,
    profile: GeminiUpstreamProfile,
) -> dict[str, Any]:
    """Serialize only the admitted normalized GenerateContent subset."""
    system_parts: list[dict[str, Any]] = []
    contents: list[dict[str, Any]] = []
    saw_non_system = False
    for message in request.messages:
        if message.role == "system":
            if saw_non_system:
                raise ValueError(
                    "Gemini system instructions must precede conversation content"
                )
            system_parts.extend(_system_message_parts(message))
        else:
            saw_non_system = True
            contents.append(_message_to_gemini(message, profile=profile))
    if not contents:
        raise ValueError("Gemini GenerateContent requires non-system content")

    payload: dict[str, Any] = {"contents": contents}
    if system_parts:
        payload["systemInstruction"] = {"parts": system_parts}
    if request.tools:
        payload["tools"] = [
            {
                "functionDeclarations": [
                    {
                        "name": tool.name,
                        **(
                            {"description": tool.description}
                            if tool.description is not None
                            else {}
                        ),
                        "parametersJsonSchema": dict(tool.parameters),
                    }
                    for tool in request.tools
                ]
            }
        ]
    tool_config = _tool_config(request.tool_choice)
    if tool_config is not None:
        payload["toolConfig"] = {"functionCallingConfig": tool_config}

    generation = _generation_config(request)
    if generation:
        payload["generationConfig"] = generation
    return payload


def gemini_response_to_normalized(
    payload: Mapping[str, Any],
    *,
    profile: GeminiUpstreamProfile,
    admission: ProtocolBridgeAdmission,
) -> NormalizedResponse:
    """Normalize a strict Gemini non-streaming response."""
    candidates_value = payload.get("candidates")
    if isinstance(candidates_value, list) and candidates_value:
        choices = [
            _candidate_to_choice(candidate, fallback_index=index)
            for index, candidate in enumerate(candidates_value)
        ]
    else:
        prompt_feedback = _prompt_feedback(payload)
        if prompt_feedback is None or "block_reason" not in prompt_feedback:
            raise _protocol_error(
                "invalid_candidates",
                "Gemini upstream response candidates must be a non-empty list.",
            )
        choices = [
            NormalizedChoice(
                index=0,
                message=NormalizedMessage(role="assistant", content=None),
                finish_reason=prompt_feedback["block_reason"],
                stop_reason="content_filter",
                provider_metadata={"gemini": {"prompt_feedback": prompt_feedback}},
            )
        ]
    return NormalizedResponse(
        id=_optional_string(payload.get("responseId")),
        model=_optional_string(payload.get("modelVersion")) or profile.model,
        provider=profile.id,
        choices=choices,
        usage=_usage(payload.get("usageMetadata")),
        provider_metadata=_response_provider_metadata(
            profile,
            admission=admission,
            payload=payload,
        ),
    )


def _system_message_parts(message: NormalizedMessage) -> list[dict[str, Any]]:
    if message.tool_calls or message.tool_call_id is not None:
        raise ValueError("Gemini system instructions cannot contain tool state")
    if isinstance(message.content, str):
        return [{"text": message.content}]
    if isinstance(message.content, list):
        parts = []
        for part in message.content:
            if part.type != "text" or part.text is None:
                raise ValueError("Gemini system instructions admit text only")
            parts.append({"text": part.text})
        return parts
    raise ValueError("Gemini system instructions require text")


def _message_to_gemini(
    message: NormalizedMessage,
    *,
    profile: GeminiUpstreamProfile,
) -> dict[str, Any]:
    role = {"user": "user", "assistant": "model", "tool": "user"}.get(message.role)
    if role is None:
        raise ValueError(f"Gemini upstream cannot represent role {message.role!r}")
    if message.role == "tool":
        parts = [_tool_result_part(message)]
    else:
        parts = _message_content_parts(message, profile=profile)
        parts.extend(_tool_call_part(call) for call in message.tool_calls)
    if not parts:
        raise ValueError("Gemini content entries require at least one part")
    return {"role": role, "parts": parts}


def _message_content_parts(
    message: NormalizedMessage,
    *,
    profile: GeminiUpstreamProfile,
) -> list[dict[str, Any]]:
    if message.content is None:
        return []
    if isinstance(message.content, str):
        return [{"text": message.content}]
    return [_content_part_to_gemini(part, profile=profile) for part in message.content]


def _content_part_to_gemini(
    part: NormalizedContentPart,
    *,
    profile: GeminiUpstreamProfile,
) -> dict[str, Any]:
    if part.type == "text" and part.text is not None:
        return {"text": part.text}
    if part.type != "image_reference" or part.image_reference is None:
        raise ValueError("content part is outside the admitted Gemini subset")
    reference = part.image_reference
    if reference.source != "data_url":
        raise ValueError("Gemini upstream admits inline data URL images only")
    mime_type, encoded, decoded_size = _parse_image_data_url(reference.uri)
    if reference.mime_type is not None and reference.mime_type != mime_type:
        raise ValueError("image MIME type does not match its data URL")
    if mime_type not in profile.allowed_inline_image_mime_types:
        raise ValueError("image MIME type is outside the reviewed profile")
    if decoded_size > profile.max_inline_image_bytes:
        raise ValueError("inline image exceeds the reviewed byte limit")
    return {"inlineData": {"mimeType": mime_type, "data": encoded}}


def _parse_image_data_url(value: str) -> tuple[str, str, int]:
    if not value.startswith("data:") or ";base64," not in value:
        raise ValueError("Gemini inline image must be a base64 data URL")
    header, encoded = value[5:].split(";base64,", 1)
    if not header or not encoded:
        raise ValueError("Gemini inline image data URL is incomplete")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Gemini inline image contains invalid base64") from exc
    return header.lower(), encoded, len(decoded)


def _tool_call_part(call: NormalizedToolCall) -> dict[str, Any]:
    if not call.name or call.type != "function":
        raise ValueError("Gemini tool calls require a named function")
    if call.arguments is None:
        arguments: Mapping[str, Any] = {}
    elif isinstance(call.arguments, Mapping):
        arguments = call.arguments
    elif isinstance(call.arguments, str):
        try:
            parsed = json.loads(call.arguments)
        except json.JSONDecodeError as exc:
            raise ValueError("Gemini tool arguments must be a JSON object") from exc
        if not isinstance(parsed, Mapping):
            raise ValueError("Gemini tool arguments must be a JSON object")
        arguments = parsed
    else:
        raise ValueError("Gemini tool arguments must be an object")
    value: dict[str, Any] = {"name": call.name, "args": dict(arguments)}
    if call.id is not None:
        value["id"] = call.id
    return {"functionCall": value}


def _tool_result_part(message: NormalizedMessage) -> dict[str, Any]:
    if not message.name or not message.tool_call_id:
        raise ValueError("Gemini tool results require function name and call id")
    if not isinstance(message.content, str):
        raise ValueError("Gemini tool result content must be a JSON object string")
    try:
        response = json.loads(message.content)
    except json.JSONDecodeError as exc:
        raise ValueError("Gemini tool result content must be valid JSON") from exc
    if not isinstance(response, Mapping):
        raise ValueError("Gemini tool result content must decode to an object")
    return {
        "functionResponse": {
            "id": message.tool_call_id,
            "name": message.name,
            "response": dict(response),
        }
    }


def _tool_config(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if value == "auto":
        return {"mode": "AUTO"}
    if value == "none":
        return {"mode": "NONE"}
    if value == "required":
        return {"mode": "ANY"}
    if isinstance(value, Mapping):
        function = value.get("function")
        if value.get("type") == "function" and isinstance(function, Mapping):
            name = function.get("name")
            if isinstance(name, str) and name:
                return {"mode": "ANY", "allowedFunctionNames": [name]}
    raise ValueError("tool_choice is outside the admitted Gemini subset")


def _generation_config(request: NormalizedChatRequest) -> dict[str, Any]:
    generation = request.generation_config
    payload: dict[str, Any] = {}
    for source, target in (
        ("temperature", "temperature"),
        ("top_p", "topP"),
        ("max_tokens", "maxOutputTokens"),
        ("presence_penalty", "presencePenalty"),
        ("frequency_penalty", "frequencyPenalty"),
        ("seed", "seed"),
    ):
        value = getattr(generation, source)
        if value is not None:
            payload[target] = value
    if generation.stop is not None:
        payload["stopSequences"] = (
            [generation.stop]
            if isinstance(generation.stop, str)
            else list(generation.stop)
        )
    if request.response_format is not None:
        payload["responseMimeType"] = "application/json"
        payload["responseJsonSchema"] = dict(request.response_format.json_schema or {})
    return payload


def _candidate_to_choice(value: Any, *, fallback_index: int) -> NormalizedChoice:
    if not isinstance(value, Mapping):
        raise _protocol_error(
            "invalid_candidate", "Gemini upstream candidate must be an object."
        )
    finish_reason = _optional_string(value.get("finishReason"))
    if finish_reason is None:
        raise _protocol_error(
            "missing_finish_reason",
            "Gemini upstream candidate requires a finishReason.",
        )
    stop_reason = _normalize_stop_reason(finish_reason)
    content = value.get("content")
    if content is None and stop_reason in {"content_filter", "error"}:
        parts: list[Any] = []
    elif isinstance(content, Mapping) and isinstance(content.get("parts"), list):
        parts = content["parts"]
    else:
        raise _protocol_error(
            "invalid_candidate_content",
            "Gemini upstream candidate content must contain a parts list.",
        )
    texts: list[str] = []
    tool_calls: list[NormalizedToolCall] = []
    for part in parts:
        if not isinstance(part, Mapping):
            raise _protocol_error(
                "invalid_candidate_part",
                "Gemini upstream candidate part must be an object.",
            )
        if "text" in part:
            text = part.get("text")
            if not isinstance(text, str):
                raise _protocol_error(
                    "invalid_candidate_text",
                    "Gemini upstream text part must contain text.",
                )
            texts.append(text)
            continue
        if "functionCall" in part:
            tool_calls.append(_response_tool_call(part.get("functionCall")))
            continue
        raise _protocol_error(
            "unsupported_candidate_part",
            "Gemini upstream returned an unsupported candidate part.",
        )
    return NormalizedChoice(
        index=_integer(value.get("index"), default=fallback_index),
        message=NormalizedMessage(
            role="assistant",
            content="".join(texts) if texts else None,
            tool_calls=tool_calls,
        ),
        finish_reason=finish_reason,
        stop_reason=stop_reason,
        provider_metadata=_candidate_provider_metadata(value),
    )


def _response_tool_call(value: Any) -> NormalizedToolCall:
    if not isinstance(value, Mapping):
        raise _protocol_error(
            "invalid_function_call",
            "Gemini upstream function call must be an object.",
        )
    name = value.get("name")
    arguments = value.get("args", {})
    if not isinstance(name, str) or not name or not isinstance(arguments, Mapping):
        raise _protocol_error(
            "invalid_function_call",
            "Gemini upstream function call requires a name and object args.",
        )
    return NormalizedToolCall(
        id=_optional_string(value.get("id")),
        name=name,
        arguments=dict(arguments),
    )


def _usage(value: Any) -> NormalizedUsage | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise _protocol_error(
            "invalid_usage", "Gemini upstream usageMetadata must be an object."
        )
    return NormalizedUsage(
        input_tokens=_optional_integer(value.get("promptTokenCount")),
        output_tokens=_optional_integer(value.get("candidatesTokenCount")),
        total_tokens=_optional_integer(value.get("totalTokenCount")),
    )


def _normalize_stop_reason(value: str | None) -> NormalizedStopReason | None:
    if value is None:
        return None
    if value == "STOP":
        return "stop"
    if value == "MAX_TOKENS":
        return "max_tokens"
    if value in {
        "SAFETY",
        "RECITATION",
        "BLOCKLIST",
        "PROHIBITED_CONTENT",
        "SPII",
        "IMAGE_SAFETY",
        "IMAGE_PROHIBITED_CONTENT",
        "IMAGE_RECITATION",
        "LANGUAGE",
    }:
        return "content_filter"
    if value in {
        "FINISH_REASON_UNSPECIFIED",
        "IMAGE_OTHER",
        "MALFORMED_FUNCTION_CALL",
        "NO_IMAGE",
        "OTHER",
        "TOO_MANY_TOOL_CALLS",
        "UNEXPECTED_TOOL_CALL",
    }:
        return "error"
    raise _protocol_error(
        "unknown_finish_reason",
        "Gemini upstream returned an unknown finishReason.",
    )


def _stream_chunk_to_events(
    payload: Mapping[str, Any],
    *,
    sequence: int,
    terminal_seen: bool,
    usage_seen: bool,
    started_tool_calls: set[str],
) -> tuple[list[NormalizedStreamEvent], bool, bool]:
    events: list[NormalizedStreamEvent] = []
    candidates = payload.get("candidates")
    prompt_feedback = _prompt_feedback(payload)
    if candidates is None:
        candidate_items: list[Any] = []
    elif isinstance(candidates, list):
        candidate_items = candidates
    else:
        raise _protocol_error(
            "invalid_stream_candidates",
            "Gemini upstream stream candidates must be a list.",
        )
    if len(candidate_items) > 1:
        raise _protocol_error(
            "unsupported_stream_candidates",
            "Gemini normalized streaming admits exactly one candidate.",
        )
    if usage_seen and (candidate_items or prompt_feedback is not None):
        raise _protocol_error(
            "stream_data_after_usage",
            "Gemini upstream stream continued after its usage summary.",
        )

    chunk_terminal = False
    if candidate_items:
        candidate = candidate_items[0]
        if not isinstance(candidate, Mapping):
            raise _protocol_error(
                "invalid_stream_candidate",
                "Gemini upstream stream candidate must be an object.",
            )
        index = _integer(candidate.get("index"), default=0)
        if index != 0:
            raise _protocol_error(
                "unsupported_stream_candidate_index",
                "Gemini normalized streaming admits candidate index zero only.",
            )
        content = candidate.get("content")
        finish_reason = _optional_string(candidate.get("finishReason"))
        if content is None:
            parts: list[Any] = []
        elif isinstance(content, Mapping) and isinstance(content.get("parts"), list):
            parts = content["parts"]
        else:
            raise _protocol_error(
                "invalid_stream_content",
                "Gemini upstream stream content must contain a parts list.",
            )
        if terminal_seen and (parts or finish_reason is not None):
            raise _protocol_error(
                "stream_data_after_terminal",
                "Gemini upstream stream continued after its terminal state.",
            )
        for part_index, part in enumerate(parts):
            if not isinstance(part, Mapping):
                raise _protocol_error(
                    "invalid_stream_part",
                    "Gemini upstream stream part must be an object.",
                )
            if "text" in part:
                text = part.get("text")
                if not isinstance(text, str):
                    raise _protocol_error(
                        "invalid_stream_text",
                        "Gemini upstream stream text part must contain text.",
                    )
                events.append(
                    _stream_event(
                        "content_delta",
                        sequence=sequence + len(events),
                        choice_index=0,
                        model=_optional_string(payload.get("modelVersion")),
                        content_delta=text,
                    )
                )
                continue
            if "functionCall" in part:
                call = _response_tool_call(part.get("functionCall"))
                key = call.id or f"{call.name}:{part_index}"
                event_type = (
                    "tool_call_delta"
                    if key in started_tool_calls
                    else "tool_call_start"
                )
                started_tool_calls.add(key)
                events.append(
                    _stream_event(
                        event_type,
                        sequence=sequence + len(events),
                        choice_index=0,
                        model=_optional_string(payload.get("modelVersion")),
                        tool_call=call,
                    )
                )
                continue
            raise _protocol_error(
                "unsupported_stream_part",
                "Gemini upstream returned an unsupported stream part.",
            )
        if finish_reason is not None:
            if terminal_seen:
                raise _protocol_error(
                    "duplicate_stream_terminal",
                    "Gemini upstream repeated its terminal state.",
                )
            chunk_terminal = True
            events.append(
                _stream_event(
                    "message_end",
                    sequence=sequence + len(events),
                    choice_index=0,
                    model=_optional_string(payload.get("modelVersion")),
                    finish_reason=finish_reason,
                    stop_reason=_normalize_stop_reason(finish_reason),
                    provider_metadata=_candidate_provider_metadata(candidate),
                )
            )
    elif prompt_feedback is not None and "block_reason" in prompt_feedback:
        if terminal_seen:
            raise _protocol_error(
                "duplicate_stream_terminal",
                "Gemini upstream repeated its terminal state.",
            )
        chunk_terminal = True
        events.append(
            _stream_event(
                "message_end",
                sequence=sequence + len(events),
                choice_index=0,
                finish_reason=prompt_feedback["block_reason"],
                stop_reason="content_filter",
                provider_metadata={"gemini": {"prompt_feedback": prompt_feedback}},
            )
        )

    usage = _usage(payload.get("usageMetadata"))
    chunk_usage = usage is not None
    if usage is not None:
        if usage_seen:
            raise _protocol_error(
                "duplicate_stream_usage",
                "Gemini upstream repeated its usage summary.",
            )
        if not (terminal_seen or chunk_terminal):
            raise _protocol_error(
                "usage_before_stream_terminal",
                "Gemini upstream reported usage before its terminal state.",
            )
        events.append(
            _stream_event(
                "usage",
                sequence=sequence + len(events),
                model=_optional_string(payload.get("modelVersion")),
                usage=usage,
            )
        )
    if not candidate_items and prompt_feedback is None and usage is None:
        raise _protocol_error(
            "empty_stream_chunk",
            "Gemini upstream stream chunk contained no admitted event.",
        )
    return events, chunk_terminal, chunk_usage


def _stream_event(event_type: Any, **values: Any) -> NormalizedStreamEvent:
    return NormalizedStreamEvent(type=event_type, **values)


def _candidate_provider_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    ratings = _safety_ratings(value.get("safetyRatings"))
    return {"gemini": {"safety_ratings": ratings}} if ratings is not None else {}


def _prompt_feedback(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    value = payload.get("promptFeedback")
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise _protocol_error(
            "invalid_prompt_feedback",
            "Gemini upstream promptFeedback must be an object.",
        )
    block_reason = value.get("blockReason")
    if block_reason is not None and (
        not isinstance(block_reason, str) or not block_reason
    ):
        raise _protocol_error(
            "invalid_prompt_feedback",
            "Gemini upstream promptFeedback blockReason must be non-empty.",
        )
    result: dict[str, Any] = {}
    if isinstance(block_reason, str):
        result["block_reason"] = block_reason
    ratings = _safety_ratings(value.get("safetyRatings"))
    if ratings is not None:
        result["safety_ratings"] = ratings
    if not result:
        raise _protocol_error(
            "invalid_prompt_feedback",
            "Gemini upstream promptFeedback contained no admitted facts.",
        )
    return result


def _safety_ratings(value: Any) -> list[dict[str, Any]] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise _protocol_error(
            "invalid_safety_ratings",
            "Gemini upstream safetyRatings must be a list.",
        )
    ratings: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise _protocol_error(
                "invalid_safety_rating",
                "Gemini upstream safety rating must be an object.",
            )
        rating = {
            key: item[key]
            for key in ("category", "probability", "probabilityScore", "blocked")
            if key in item
        }
        if not isinstance(rating.get("category"), str):
            raise _protocol_error(
                "invalid_safety_rating",
                "Gemini upstream safety rating requires a category.",
            )
        ratings.append(
            {
                "category": rating["category"],
                **(
                    {"probability": rating["probability"]}
                    if isinstance(rating.get("probability"), str)
                    else {}
                ),
                **(
                    {"probability_score": rating["probabilityScore"]}
                    if isinstance(rating.get("probabilityScore"), (int, float))
                    and not isinstance(rating.get("probabilityScore"), bool)
                    else {}
                ),
                **(
                    {"blocked": rating["blocked"]}
                    if isinstance(rating.get("blocked"), bool)
                    else {}
                ),
            }
        )
    return ratings


def _response_provider_metadata(
    profile: GeminiUpstreamProfile,
    *,
    admission: ProtocolBridgeAdmission,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "profile_id": profile.id,
        "profile_revision": profile.revision,
        "dialect": profile.dialect,
        "admission_schema_version": admission.schema_version,
    }
    if payload is not None:
        prompt_feedback = _prompt_feedback(payload)
        if prompt_feedback is not None:
            metadata["prompt_feedback"] = prompt_feedback
    return {"gemini": metadata}


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
    data_lines: list[bytes] = []
    for line in block.replace(b"\r\n", b"\n").replace(b"\r", b"\n").split(b"\n"):
        if line.startswith(b":"):
            continue
        if line == b"data":
            data_lines.append(b"")
        elif line.startswith(b"data:"):
            data_lines.append(line[5:].lstrip())
    if not data_lines:
        return None
    raw_event = b"\n".join(data_lines)
    if raw_event == b"[DONE]":
        raise _protocol_error(
            "unexpected_stream_done",
            "Gemini GenerateContent stream used an unexpected done marker.",
        )
    try:
        parsed = json.loads(raw_event)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _protocol_error(
            "invalid_stream_json",
            "Gemini upstream stream contained invalid JSON.",
        ) from exc
    if not isinstance(parsed, Mapping):
        raise _protocol_error(
            "invalid_stream_chunk",
            "Gemini upstream stream chunk must be an object.",
        )
    return parsed


async def _is_disconnected(callback: Callable[[], Any] | None) -> bool:
    if callback is None:
        return False
    result = callback()
    if hasattr(result, "__await__"):
        result = await result
    return bool(result)


def _json_body(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


async def _read_bounded_response(
    response: httpx.Response,
    authorization: GeminiNetworkAuthorization,
) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > authorization.max_response_bytes:
            raise _transport_error(
                "response_too_large",
                "Gemini upstream response exceeded the reviewed limit.",
            )
        chunks.append(chunk)
    authorization.validate_response_body(body_bytes=size)
    return b"".join(chunks)


def _http_error(response: httpx.Response, content: bytes) -> GeminiUpstreamError:
    status_code = response.status_code
    provider_status: str | None = None
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, Mapping):
        raw_error = payload.get("error")
        if isinstance(raw_error, Mapping):
            candidate_status = _optional_string(raw_error.get("status"))
            if candidate_status in _KNOWN_ERROR_STATUSES:
                provider_status = candidate_status
    error_class: Literal[
        "invalid_request",
        "authentication",
        "permission",
        "not_found",
        "rate_limit",
        "timeout",
        "upstream",
    ]
    if provider_status == "UNAUTHENTICATED":
        error_class = "authentication"
    elif provider_status == "PERMISSION_DENIED":
        error_class = "permission"
    elif provider_status == "NOT_FOUND":
        error_class = "not_found"
    elif provider_status == "RESOURCE_EXHAUSTED":
        error_class = "rate_limit"
    elif provider_status == "DEADLINE_EXCEEDED":
        error_class = "timeout"
    elif status_code == 400:
        error_class = "invalid_request"
    elif status_code == 401:
        error_class = "authentication"
    elif status_code == 403:
        error_class = "permission"
    elif status_code == 404:
        error_class = "not_found"
    elif status_code == 429:
        error_class = "rate_limit"
    elif status_code in {408, 504}:
        error_class = "timeout"
    else:
        error_class = "upstream"
    return GeminiUpstreamError(
        NormalizedError(
            type="gemini_api_error",
            message=f"Gemini upstream returned HTTP {status_code}.",
            code=provider_status or status_code,
            error_class=error_class,
            retryable=status_code in {408, 429, 500, 502, 503, 504},
        ),
        status_code=status_code,
    )


def _transport_error(code: str, message: str) -> GeminiUpstreamError:
    error_class = "timeout" if code == "timeout" else "upstream"
    return GeminiUpstreamError(
        NormalizedError(
            type="gemini_transport_error",
            message=message,
            code=code,
            error_class=error_class,
            retryable=code in {"timeout", "connection_error"},
        )
    )


def _protocol_error(code: str, message: str) -> GeminiProtocolError:
    return GeminiProtocolError(
        NormalizedError(
            type="gemini_protocol_error",
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
        raise ValueError("Gemini base_url must be absolute HTTP(S)")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Gemini base_url cannot contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("Gemini base_url cannot contain query or fragment")
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
        "Gemini upstream usage token counts must be non-negative integers.",
    )


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def gemini_upstream_profile(
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
    max_inline_image_bytes: int = DEFAULT_MAX_INLINE_IMAGE_BYTES,
    allowed_inline_image_mime_types: Collection[str] = (
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/webp",
    ),
) -> GeminiUpstreamProfile:
    """Build one exact Gemini profile after explicit capability review."""
    capabilities = NormalizedProtocolCapabilities(
        profile=f"{profile_id}@{revision}",
        features=frozenset(features),
        limits=limits,
    )
    return GeminiUpstreamProfile(
        id=profile_id,
        revision=revision,
        base_url=base_url,
        model=model,
        capabilities=capabilities,
        timeout_seconds=timeout_seconds,
        max_response_bytes=max_response_bytes,
        max_inline_image_bytes=max_inline_image_bytes,
        allowed_inline_image_mime_types=frozenset(allowed_inline_image_mime_types),
        credential_reference_id=credential_reference_id,
        network_policy_ref=network_policy_ref,
        tls_policy_ref=tls_policy_ref,
        proxy_policy_ref=proxy_policy_ref,
    )
