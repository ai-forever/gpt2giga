"""OpenAI-compatible provider templates and hermetic probe contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
from importlib import metadata
import json
from typing import Any, Mapping, Protocol

from gpt2giga_harness.execution import (
    ExecutionTransport,
    ProviderRef,
    SnapshotEvidenceRef,
)
from gpt2giga_harness.provider_profiles import (
    AdapterProtocolCompatibility,
    AuthenticationOwnership,
    ModelPurpose,
    ModelPurposeDefault,
    ProviderAuthentication,
    ProviderOwnership,
    ProviderProfile,
    ProviderProtocol,
    RouteProfile,
    provider_profile_to_dict,
    route_profile_to_dict,
)
from gpt2giga_harness.provider_registry import (
    ProviderAuthenticationFailure,
    ProviderCompatibilityFailure,
    ProviderHealthFailure,
    ProviderProbeRequest,
    ProviderProbeResponse,
    ProviderTransportFailure,
)
from gpt2giga_harness.secrets import (
    ResolvedSecret,
    SecretReference,
    SecretReferenceKind,
    SecretResolutionError,
    SecretResolutionService,
)


OPENAI_OFFICIAL_BASE_URL = "https://api.openai.com"
OPENAI_API_KEY_ENVIRONMENT = "OPENAI_API_KEY"
OPENAI_RESPONSES_DIALECT = "openai-responses-v1"
OPENAI_CHAT_COMPLETIONS_DIALECT = "openai-chat-completions-v1"
OPENAI_MODELS_DISCOVERY_STRATEGY = "openai-models-v1"
OPENAI_PROBE_OWNER = "provider-probe:openai-compatible"
OPENAI_DISCOVERY_CACHE_TTL_SECONDS = 300
VLLM_OPENAI_COMPATIBLE_PROFILE_VERSION = "gigaloom.vllm-openai-compatible.v1"
MAX_OPENAI_MODELS = 500
MAX_OPENAI_MODEL_ID_CHARS = 256


class OpenAIWireAPI(str, Enum):
    """Reviewed OpenAI-compatible execution dialect."""

    RESPONSES = "responses"
    CHAT_COMPLETIONS = "chat_completions"

    @property
    def dialect(self) -> str:
        """Return the stable provider-profile dialect identifier."""
        if self is OpenAIWireAPI.RESPONSES:
            return OPENAI_RESPONSES_DIALECT
        return OPENAI_CHAT_COMPLETIONS_DIALECT


@dataclass(frozen=True)
class OpenAIModelsProbeRequest:
    """Runtime-only OpenAI probe input with an opaque credential."""

    provider: ProviderRef
    wire_api: OpenAIWireAPI
    models_url: str
    timeout_seconds: float
    discover_models: bool
    credential: ResolvedSecret | None
    proxy_policy_ref: str | None
    tls_policy_ref: str | None
    egress_policy_ref: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.provider, ProviderRef):
            raise ValueError("OpenAI probe provider is invalid")
        if not isinstance(self.wire_api, OpenAIWireAPI):
            raise ValueError("OpenAI probe wire API is invalid")
        if not self.models_url.endswith("/models"):
            raise ValueError("OpenAI probe models URL is invalid")
        if "@" in self.models_url.split("://", 1)[-1].split("/", 1)[0]:
            raise ValueError("OpenAI probe models URL cannot contain credentials")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or self.timeout_seconds <= 0
        ):
            raise ValueError("OpenAI probe timeout is invalid")
        if not isinstance(self.discover_models, bool):
            raise ValueError("OpenAI probe discovery flag is invalid")
        if self.credential is not None and not isinstance(
            self.credential, ResolvedSecret
        ):
            raise ValueError("OpenAI probe credential must remain opaque")


@dataclass(frozen=True)
class OpenAITransportResponse:
    """Connection result returned by an injected OpenAI transport."""

    payload: Mapping[str, Any] | None = None
    discovery_succeeded: bool = True
    discovery_reason_code: str | None = None

    def __post_init__(self) -> None:
        if self.payload is not None and not isinstance(self.payload, Mapping):
            raise ValueError("OpenAI transport payload must be an object")
        if not isinstance(self.discovery_succeeded, bool):
            raise ValueError("OpenAI transport discovery state is invalid")
        if self.discovery_succeeded == (self.discovery_reason_code is not None):
            raise ValueError("OpenAI transport discovery reason is inconsistent")
        if self.discovery_reason_code is not None:
            _validate_reason_code(self.discovery_reason_code)

    def __repr__(self) -> str:
        payload_state = "present" if self.payload is not None else "absent"
        return (
            "OpenAITransportResponse("
            f"payload=<{payload_state}>, "
            f"discovery_succeeded={self.discovery_succeeded!r}, "
            f"discovery_reason_code={self.discovery_reason_code!r})"
        )

    def __gpt2giga_redacted__(self) -> dict[str, Any]:
        """Return content-free transport evidence for shared redaction."""
        return {
            "payload": "present" if self.payload is not None else "absent",
            "discovery_succeeded": self.discovery_succeeded,
            "discovery_reason_code": self.discovery_reason_code,
        }


class OpenAIProbeTransport(Protocol):
    """Injected owner of HTTP, proxy, TLS, and credential reveal behavior."""

    def probe(self, request: OpenAIModelsProbeRequest) -> OpenAITransportResponse:
        """Check the endpoint and optionally return its models payload."""


class OpenAIProbeError(RuntimeError):
    """Stable provider-specific failure without response bodies or credentials."""

    def __init__(self, reason_code: str) -> None:
        _validate_reason_code(reason_code)
        super().__init__(reason_code)
        self.reason_code = reason_code


class OpenAIProbeAuthenticationError(OpenAIProbeError):
    """OpenAI-compatible authentication was rejected."""


class OpenAIProbeCompatibilityError(OpenAIProbeError):
    """Endpoint or dialect compatibility was rejected."""


class OpenAIProbeProviderHealthError(OpenAIProbeError):
    """Provider responded but was unavailable or unhealthy."""


class OpenAIProbeTransportError(OpenAIProbeError):
    """Network transport failed before a provider response."""


class OpenAICompatibleProbeBackend:
    """Resolve auth at the final boundary and normalize OpenAI model discovery."""

    def __init__(
        self,
        transport: OpenAIProbeTransport,
        secrets: SecretResolutionService | None = None,
    ) -> None:
        self.transport = transport
        self.secrets = secrets

    def check(self, request: ProviderProbeRequest) -> ProviderProbeResponse:
        """Run one bounded probe without persisting credentials or payloads."""
        profile = request.profile
        wire_api = _wire_api_for_profile(profile)
        if profile.discovery_strategy != OPENAI_MODELS_DISCOVERY_STRATEGY:
            raise ProviderCompatibilityFailure("discovery_strategy_incompatible")
        credential = self._resolve_credential(profile)
        transport_request = OpenAIModelsProbeRequest(
            provider=profile.ref,
            wire_api=wire_api,
            models_url=f"{profile.effective_base_url.rstrip('/')}/models",
            timeout_seconds=request.timeout_seconds,
            discover_models=request.discover_models,
            credential=credential,
            proxy_policy_ref=request.proxy_policy_ref,
            tls_policy_ref=request.tls_policy_ref,
            egress_policy_ref=request.egress_policy_ref,
        )
        try:
            response = self.transport.probe(transport_request)
        except OpenAIProbeAuthenticationError as exc:
            raise ProviderAuthenticationFailure(exc.reason_code) from None
        except OpenAIProbeCompatibilityError as exc:
            raise ProviderCompatibilityFailure(exc.reason_code) from None
        except OpenAIProbeProviderHealthError as exc:
            raise ProviderHealthFailure(exc.reason_code) from None
        except OpenAIProbeTransportError as exc:
            raise ProviderTransportFailure(exc.reason_code) from None
        if not isinstance(response, OpenAITransportResponse):
            raise ProviderCompatibilityFailure("invalid_probe_response")
        if not request.discover_models:
            return ProviderProbeResponse()
        if not response.discovery_succeeded:
            return ProviderProbeResponse(
                discovery_succeeded=False,
                discovery_reason_code=response.discovery_reason_code,
            )
        try:
            models = parse_openai_models_response(response.payload)
        except ValueError:
            return ProviderProbeResponse(
                discovery_succeeded=False,
                discovery_reason_code="invalid_models_response",
            )
        return ProviderProbeResponse(models=models)

    def _resolve_credential(self, profile: ProviderProfile) -> ResolvedSecret | None:
        authentication = profile.authentication
        if authentication.ownership is AuthenticationOwnership.NONE:
            return None
        if authentication.ownership is not AuthenticationOwnership.SECRET_REFERENCE:
            raise ProviderCompatibilityFailure("authentication_ownership_incompatible")
        reference = authentication.secret_reference
        if reference is None:
            raise ProviderAuthenticationFailure("secret_reference_missing")
        if self.secrets is None:
            raise ProviderAuthenticationFailure("secret_resolver_unavailable")
        try:
            return self.secrets.resolve(reference, owner=OPENAI_PROBE_OWNER)
        except SecretResolutionError as exc:
            raise ProviderAuthenticationFailure(f"secret_{exc.code.value}") from None


def official_openai_profile(
    wire_api: OpenAIWireAPI,
    *,
    secret_reference: SecretReference | None = None,
    default_models: tuple[ModelPurposeDefault, ...] = (),
    discovery_cache_ttl_seconds: int = OPENAI_DISCOVERY_CACHE_TTL_SECONDS,
) -> ProviderProfile:
    """Build the immutable official OpenAI endpoint template."""
    if not isinstance(wire_api, OpenAIWireAPI):
        raise ValueError("OpenAI wire API is invalid")
    provider_id = (
        "openai" if wire_api is OpenAIWireAPI.RESPONSES else "openai-chat-completions"
    )
    display_name = (
        "OpenAI" if wire_api is OpenAIWireAPI.RESPONSES else "OpenAI Chat Completions"
    )
    reference = secret_reference or SecretReference(
        SecretReferenceKind.ENVIRONMENT,
        OPENAI_API_KEY_ENVIRONMENT,
    )
    return _build_profile(
        provider_id=provider_id,
        display_name=display_name,
        base_url=OPENAI_OFFICIAL_BASE_URL,
        route_prefix="/v1",
        wire_api=wire_api,
        authentication=ProviderAuthentication(
            AuthenticationOwnership.SECRET_REFERENCE,
            reference,
        ),
        ownership=ProviderOwnership.BUILT_IN,
        default_models=default_models,
        discovery_cache_ttl_seconds=discovery_cache_ttl_seconds,
        capability_source="openai-official-contract",
    )


def custom_openai_compatible_profile(
    *,
    provider_id: str,
    display_name: str,
    base_url: str,
    route_prefix: str | None,
    wire_api: OpenAIWireAPI,
    authentication: ProviderAuthentication | None = None,
    ownership: ProviderOwnership = ProviderOwnership.USER,
    default_models: tuple[ModelPurposeDefault, ...] = (),
    proxy_policy_ref: str | None = None,
    tls_policy_ref: str | None = None,
    egress_policy_ref: str | None = None,
    offline: bool = False,
    discovery_cache_ttl_seconds: int = OPENAI_DISCOVERY_CACHE_TTL_SECONDS,
) -> ProviderProfile:
    """Build a custom OpenAI-compatible endpoint without credential values."""
    if not isinstance(wire_api, OpenAIWireAPI):
        raise ValueError("OpenAI wire API is invalid")
    resolved_authentication = authentication or ProviderAuthentication(
        AuthenticationOwnership.SECRET_REFERENCE,
        SecretReference(
            SecretReferenceKind.ENVIRONMENT,
            OPENAI_API_KEY_ENVIRONMENT,
        ),
    )
    return _build_profile(
        provider_id=provider_id,
        display_name=display_name,
        base_url=base_url,
        route_prefix=route_prefix,
        wire_api=wire_api,
        authentication=resolved_authentication,
        ownership=ownership,
        default_models=default_models,
        proxy_policy_ref=proxy_policy_ref,
        tls_policy_ref=tls_policy_ref,
        egress_policy_ref=egress_policy_ref,
        offline=offline,
        discovery_cache_ttl_seconds=discovery_cache_ttl_seconds,
        capability_source="openai-compatible-template",
    )


def vllm_openai_compatible_profile(
    *,
    provider_id: str,
    base_url: str,
    model: str,
    display_name: str = "vLLM",
    route_prefix: str | None = "/v1",
    secret_reference: SecretReference | None = None,
    ownership: ProviderOwnership = ProviderOwnership.USER,
    proxy_policy_ref: str | None = None,
    tls_policy_ref: str | None = None,
    egress_policy_ref: str | None = None,
    offline: bool = False,
    discovery_cache_ttl_seconds: int = OPENAI_DISCOVERY_CACHE_TTL_SECONDS,
) -> ProviderProfile:
    """Build the reviewed v1 vLLM Chat Completions profile."""
    authentication = (
        ProviderAuthentication(
            AuthenticationOwnership.SECRET_REFERENCE,
            secret_reference,
        )
        if secret_reference is not None
        else ProviderAuthentication(AuthenticationOwnership.NONE)
    )
    return _build_profile(
        provider_id=provider_id,
        display_name=display_name,
        base_url=base_url,
        route_prefix=route_prefix,
        wire_api=OpenAIWireAPI.CHAT_COMPLETIONS,
        authentication=authentication,
        ownership=ownership,
        default_models=(ModelPurposeDefault(ModelPurpose.CODING, model),),
        proxy_policy_ref=proxy_policy_ref,
        tls_policy_ref=tls_policy_ref,
        egress_policy_ref=egress_policy_ref,
        offline=offline,
        discovery_cache_ttl_seconds=discovery_cache_ttl_seconds,
        capability_source=VLLM_OPENAI_COMPATIBLE_PROFILE_VERSION,
    )


def openai_compatible_route(
    provider: ProviderProfile,
    *,
    route_id: str,
    model: str,
    purpose: ModelPurpose,
    capability_evidence: tuple[SnapshotEvidenceRef, ...] | None = None,
) -> RouteProfile:
    """Bind one OpenAI-compatible model purpose to an exact provider revision."""
    _wire_api_for_profile(provider)
    route = RouteProfile(
        id=route_id,
        revision="pending",
        provider=provider.ref,
        protocol=provider.protocol,
        dialect=provider.dialect,
        effective_base_url=provider.effective_base_url,
        purpose=purpose,
        model=model,
        authentication_ownership=provider.authentication.ownership,
        capability_evidence=(
            provider.capability_evidence
            if capability_evidence is None
            else capability_evidence
        ),
    )
    semantic = route_profile_to_dict(route)
    semantic.pop("revision")
    return replace(route, revision=_semantic_revision(semantic))


def parse_openai_models_response(payload: Any) -> tuple[str, ...]:
    """Parse the bounded standard model-list shape without inferring features."""
    if not isinstance(payload, Mapping):
        raise ValueError("OpenAI models response must be an object")
    if payload.get("object") != "list":
        raise ValueError("OpenAI models response object must be list")
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("OpenAI models response data must be a list")
    if len(data) > MAX_OPENAI_MODELS:
        raise ValueError("OpenAI models response is too large")
    models: set[str] = set()
    for item in data:
        if not isinstance(item, Mapping):
            raise ValueError("OpenAI model entry must be an object")
        if item.get("object") not in {None, "model"}:
            raise ValueError("OpenAI model object is invalid")
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            raise ValueError("OpenAI model id is invalid")
        normalized = model_id.strip()
        if len(normalized) > MAX_OPENAI_MODEL_ID_CHARS or any(
            ord(character) < 32 for character in normalized
        ):
            raise ValueError("OpenAI model id is invalid")
        models.add(normalized)
    return tuple(sorted(models))


def direct_chat_openai_compatibility() -> AdapterProtocolCompatibility:
    """Return Direct Chat evidence for OpenAI Chat Completions fixtures."""
    return _openai_compatibility(
        harness_id="direct-chat",
        dialects=(OPENAI_CHAT_COMPLETIONS_DIALECT,),
        transports=(ExecutionTransport.ONE_SHOT,),
    )


def codex_openai_compatibility() -> AdapterProtocolCompatibility:
    """Return Codex evidence for OpenAI Responses-compatible fixtures."""
    return _openai_compatibility(
        harness_id="codex-cli",
        dialects=(OPENAI_RESPONSES_DIALECT,),
        transports=(
            ExecutionTransport.NATIVE_STRUCTURED,
            ExecutionTransport.NATIVE_TERMINAL,
            ExecutionTransport.ONE_SHOT,
        ),
    )


def _build_profile(
    *,
    provider_id: str,
    display_name: str,
    base_url: str,
    route_prefix: str | None,
    wire_api: OpenAIWireAPI,
    authentication: ProviderAuthentication,
    ownership: ProviderOwnership,
    default_models: tuple[ModelPurposeDefault, ...],
    discovery_cache_ttl_seconds: int,
    capability_source: str,
    proxy_policy_ref: str | None = None,
    tls_policy_ref: str | None = None,
    egress_policy_ref: str | None = None,
    offline: bool = False,
) -> ProviderProfile:
    if authentication.ownership not in {
        AuthenticationOwnership.SECRET_REFERENCE,
        AuthenticationOwnership.NONE,
    }:
        raise ValueError(
            "OpenAI-compatible templates require SecretRef or no authentication"
        )
    evidence = _capability_evidence(wire_api, source=capability_source)
    profile = ProviderProfile(
        id=provider_id,
        revision="pending",
        display_name=display_name,
        protocol=ProviderProtocol.OPENAI_COMPATIBLE,
        dialect=wire_api.dialect,
        base_url=base_url,
        route_prefix=route_prefix,
        authentication=authentication,
        ownership=ownership,
        capability_evidence=evidence,
        default_models=default_models,
        proxy_policy_ref=proxy_policy_ref,
        tls_policy_ref=tls_policy_ref,
        egress_policy_ref=egress_policy_ref,
        offline=offline,
        discovery_strategy=OPENAI_MODELS_DISCOVERY_STRATEGY,
        discovery_cache_ttl_seconds=discovery_cache_ttl_seconds,
    )
    semantic = provider_profile_to_dict(profile)
    semantic.pop("revision")
    return replace(profile, revision=_semantic_revision(semantic))


def _capability_evidence(
    wire_api: OpenAIWireAPI,
    *,
    source: str,
) -> tuple[SnapshotEvidenceRef, ...]:
    contract = {
        "wire_api": wire_api.value,
        "dialect": wire_api.dialect,
        "models_endpoint": "/v1/models",
        "capabilities": {
            "chat": "supported",
            "images": "model-dependent",
            "reasoning": "model-dependent",
            "streaming": "supported",
            "structured-output": "model-dependent",
            "tools": "model-dependent",
            "usage": "supported",
        },
    }
    revision = _semantic_revision(contract)
    return tuple(
        SnapshotEvidenceRef(
            id=capability,
            revision=revision,
            status=status,
            source=source,
        )
        for capability, status in contract["capabilities"].items()
    )


def _openai_compatibility(
    *,
    harness_id: str,
    dialects: tuple[str, ...],
    transports: tuple[ExecutionTransport, ...],
) -> AdapterProtocolCompatibility:
    adapter_version = _adapter_version()
    semantic = {
        "harness_id": harness_id,
        "adapter_version": adapter_version,
        "protocol": ProviderProtocol.OPENAI_COMPATIBLE.value,
        "dialects": dialects,
        "transports": tuple(item.value for item in transports),
        "capabilities": ("chat", "streaming", "usage"),
        "native_auth": False,
    }
    revision = _semantic_revision(semantic)
    return AdapterProtocolCompatibility(
        id=f"openai-compatible-{harness_id}",
        revision=revision,
        harness_id=harness_id,
        adapter_version=adapter_version,
        protocol=ProviderProtocol.OPENAI_COMPATIBLE,
        dialects=dialects,
        transports=transports,
        capabilities=("chat", "streaming", "usage"),
        native_auth=False,
        evidence=(
            SnapshotEvidenceRef(
                id=f"{harness_id}-openai-compatible-fixture",
                revision=revision,
                status="supported",
                source="built-in-contract",
            ),
        ),
    )


def _wire_api_for_profile(profile: ProviderProfile) -> OpenAIWireAPI:
    if not isinstance(profile, ProviderProfile):
        raise ProviderCompatibilityFailure("profile_invalid")
    if profile.protocol is not ProviderProtocol.OPENAI_COMPATIBLE:
        raise ProviderCompatibilityFailure("protocol_incompatible")
    by_dialect = {
        OPENAI_RESPONSES_DIALECT: OpenAIWireAPI.RESPONSES,
        OPENAI_CHAT_COMPLETIONS_DIALECT: OpenAIWireAPI.CHAT_COMPLETIONS,
    }
    try:
        return by_dialect[profile.dialect]
    except KeyError:
        raise ProviderCompatibilityFailure("dialect_incompatible") from None


def _semantic_revision(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _adapter_version() -> str:
    try:
        return metadata.version("gigaloom")
    except metadata.PackageNotFoundError:  # pragma: no cover - source checkout only
        return "0"


def _validate_reason_code(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or not all(character.isalnum() or character in "._-" for character in value)
    ):
        raise ValueError("OpenAI probe reason code is invalid")
