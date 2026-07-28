"""Anthropic-compatible provider templates and hermetic probe contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
from importlib import metadata
import json
from typing import Any, Mapping, Protocol

from gpt2giga_harness.claude_agent_sdk import ClaudeSdkAuthMode
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


ANTHROPIC_OFFICIAL_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_API_KEY_ENVIRONMENT = "ANTHROPIC_API_KEY"
ANTHROPIC_API_VERSION = "2023-06-01"
ANTHROPIC_MESSAGES_DIALECT = "anthropic-messages-v1"
ANTHROPIC_BEDROCK_DIALECT = "anthropic-bedrock-v1"
ANTHROPIC_VERTEX_DIALECT = "anthropic-vertex-v1"
ANTHROPIC_FOUNDRY_DIALECT = "anthropic-foundry-v1"
ANTHROPIC_MODELS_DISCOVERY_STRATEGY = "anthropic-models-v1"
ANTHROPIC_PLATFORM_DISCOVERY_STRATEGY = "anthropic-platform-models-v1"
ANTHROPIC_PROBE_OWNER = "provider-probe:anthropic-compatible"
ANTHROPIC_DISCOVERY_CACHE_TTL_SECONDS = 300
MAX_ANTHROPIC_MODELS = 500
MAX_ANTHROPIC_MODEL_ID_CHARS = 256


class AnthropicPlatform(str, Enum):
    """Reviewed Anthropic protocol platform with distinct auth ownership."""

    ANTHROPIC_API = "anthropic_api"
    AMAZON_BEDROCK = "amazon_bedrock"
    GOOGLE_VERTEX = "google_vertex"
    MICROSOFT_FOUNDRY = "microsoft_foundry"

    @property
    def dialect(self) -> str:
        """Return the stable provider-profile dialect identifier."""
        return {
            AnthropicPlatform.ANTHROPIC_API: ANTHROPIC_MESSAGES_DIALECT,
            AnthropicPlatform.AMAZON_BEDROCK: ANTHROPIC_BEDROCK_DIALECT,
            AnthropicPlatform.GOOGLE_VERTEX: ANTHROPIC_VERTEX_DIALECT,
            AnthropicPlatform.MICROSOFT_FOUNDRY: ANTHROPIC_FOUNDRY_DIALECT,
        }[self]

    @property
    def discovery_strategy(self) -> str:
        """Return the discovery contract owned by the selected platform."""
        if self is AnthropicPlatform.ANTHROPIC_API:
            return ANTHROPIC_MODELS_DISCOVERY_STRATEGY
        return ANTHROPIC_PLATFORM_DISCOVERY_STRATEGY


@dataclass(frozen=True)
class AnthropicProbeTransportRequest:
    """Runtime-only Anthropic probe input with an optional opaque credential."""

    provider: ProviderRef
    platform: AnthropicPlatform
    probe_url: str
    api_version: str | None
    timeout_seconds: float
    discover_models: bool
    credential: ResolvedSecret | None
    proxy_policy_ref: str | None
    tls_policy_ref: str | None
    egress_policy_ref: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.provider, ProviderRef):
            raise ValueError("Anthropic probe provider is invalid")
        if not isinstance(self.platform, AnthropicPlatform):
            raise ValueError("Anthropic probe platform is invalid")
        if not isinstance(self.probe_url, str) or not self.probe_url.startswith(
            ("http://", "https://")
        ):
            raise ValueError("Anthropic probe URL is invalid")
        if "@" in self.probe_url.split("://", 1)[-1].split("/", 1)[0]:
            raise ValueError("Anthropic probe URL cannot contain credentials")
        if self.platform is AnthropicPlatform.ANTHROPIC_API:
            if not self.probe_url.endswith("/models"):
                raise ValueError("Anthropic models probe URL is invalid")
            if self.api_version != ANTHROPIC_API_VERSION:
                raise ValueError("Anthropic API version is invalid")
        elif self.api_version is not None:
            raise ValueError("cloud platform probes do not use Anthropic API version")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or self.timeout_seconds <= 0
        ):
            raise ValueError("Anthropic probe timeout is invalid")
        if not isinstance(self.discover_models, bool):
            raise ValueError("Anthropic probe discovery flag is invalid")
        if self.credential is not None and not isinstance(
            self.credential, ResolvedSecret
        ):
            raise ValueError("Anthropic probe credential must remain opaque")


@dataclass(frozen=True)
class AnthropicTransportResponse:
    """Connection result returned by an injected Anthropic transport."""

    payload: Mapping[str, Any] | None = None
    models: tuple[str, ...] = ()
    discovery_succeeded: bool = True
    discovery_reason_code: str | None = None

    def __post_init__(self) -> None:
        if self.payload is not None and not isinstance(self.payload, Mapping):
            raise ValueError("Anthropic transport payload must be an object")
        object.__setattr__(self, "models", _normalize_models(self.models))
        if self.payload is not None and self.models:
            raise ValueError(
                "Anthropic transport cannot return raw and normalized models"
            )
        if not isinstance(self.discovery_succeeded, bool):
            raise ValueError("Anthropic transport discovery state is invalid")
        if self.discovery_succeeded == (self.discovery_reason_code is not None):
            raise ValueError("Anthropic transport discovery reason is inconsistent")
        if self.discovery_reason_code is not None:
            _validate_reason_code(self.discovery_reason_code)

    def __repr__(self) -> str:
        payload_state = "present" if self.payload is not None else "absent"
        return (
            "AnthropicTransportResponse("
            f"payload=<{payload_state}>, models_count={len(self.models)!r}, "
            f"discovery_succeeded={self.discovery_succeeded!r}, "
            f"discovery_reason_code={self.discovery_reason_code!r})"
        )

    def __gpt2giga_redacted__(self) -> dict[str, Any]:
        """Return content-free transport evidence for shared redaction."""
        return {
            "payload": "present" if self.payload is not None else "absent",
            "models_count": len(self.models),
            "discovery_succeeded": self.discovery_succeeded,
            "discovery_reason_code": self.discovery_reason_code,
        }


class AnthropicProbeTransport(Protocol):
    """Injected owner of HTTP/cloud I/O, policy, and credential reveal."""

    def probe(
        self,
        request: AnthropicProbeTransportRequest,
    ) -> AnthropicTransportResponse:
        """Check the endpoint and optionally return model evidence."""


class AnthropicProbeError(RuntimeError):
    """Stable provider-specific failure without response bodies or credentials."""

    def __init__(self, reason_code: str) -> None:
        _validate_reason_code(reason_code)
        super().__init__(reason_code)
        self.reason_code = reason_code


class AnthropicProbeAuthenticationError(AnthropicProbeError):
    """Anthropic-compatible authentication was rejected."""


class AnthropicProbeCompatibilityError(AnthropicProbeError):
    """Endpoint, platform, or dialect compatibility was rejected."""


class AnthropicProbeProviderHealthError(AnthropicProbeError):
    """Provider responded but was unavailable or unhealthy."""


class AnthropicProbeTransportError(AnthropicProbeError):
    """Network or cloud transport failed before a provider response."""


class AnthropicCompatibleProbeBackend:
    """Resolve direct auth at the final boundary and normalize discovery."""

    def __init__(
        self,
        transport: AnthropicProbeTransport,
        secrets: SecretResolutionService | None = None,
    ) -> None:
        self.transport = transport
        self.secrets = secrets

    def check(self, request: ProviderProbeRequest) -> ProviderProbeResponse:
        """Run one bounded probe without persisting credentials or payloads."""
        profile = request.profile
        platform = _platform_for_profile(profile)
        if profile.discovery_strategy != platform.discovery_strategy:
            raise ProviderCompatibilityFailure("discovery_strategy_incompatible")
        credential = self._resolve_credential(profile, platform=platform)
        transport_request = AnthropicProbeTransportRequest(
            provider=profile.ref,
            platform=platform,
            probe_url=(
                f"{profile.effective_base_url.rstrip('/')}/models"
                if platform is AnthropicPlatform.ANTHROPIC_API
                else profile.effective_base_url
            ),
            api_version=(
                ANTHROPIC_API_VERSION
                if platform is AnthropicPlatform.ANTHROPIC_API
                else None
            ),
            timeout_seconds=request.timeout_seconds,
            discover_models=request.discover_models,
            credential=credential,
            proxy_policy_ref=request.proxy_policy_ref,
            tls_policy_ref=request.tls_policy_ref,
            egress_policy_ref=request.egress_policy_ref,
        )
        try:
            response = self.transport.probe(transport_request)
        except AnthropicProbeAuthenticationError as exc:
            raise ProviderAuthenticationFailure(exc.reason_code) from None
        except AnthropicProbeCompatibilityError as exc:
            raise ProviderCompatibilityFailure(exc.reason_code) from None
        except AnthropicProbeProviderHealthError as exc:
            raise ProviderHealthFailure(exc.reason_code) from None
        except AnthropicProbeTransportError as exc:
            raise ProviderTransportFailure(exc.reason_code) from None
        if not isinstance(response, AnthropicTransportResponse):
            raise ProviderCompatibilityFailure("invalid_probe_response")
        if not request.discover_models:
            return ProviderProbeResponse()
        if not response.discovery_succeeded:
            return ProviderProbeResponse(
                discovery_succeeded=False,
                discovery_reason_code=response.discovery_reason_code,
            )
        if platform is not AnthropicPlatform.ANTHROPIC_API:
            if response.payload is not None:
                raise ProviderCompatibilityFailure("invalid_platform_probe_response")
            return ProviderProbeResponse(models=response.models)
        if response.models:
            raise ProviderCompatibilityFailure("invalid_api_probe_response")
        try:
            models = parse_anthropic_models_response(response.payload)
        except ValueError:
            return ProviderProbeResponse(
                discovery_succeeded=False,
                discovery_reason_code="invalid_models_response",
            )
        return ProviderProbeResponse(models=models)

    def _resolve_credential(
        self,
        profile: ProviderProfile,
        *,
        platform: AnthropicPlatform,
    ) -> ResolvedSecret | None:
        authentication = profile.authentication
        if authentication.ownership in {
            AuthenticationOwnership.NONE,
            AuthenticationOwnership.PROVIDER_NATIVE,
        }:
            return None
        if authentication.ownership is not AuthenticationOwnership.SECRET_REFERENCE:
            raise ProviderCompatibilityFailure("authentication_ownership_incompatible")
        if platform in {
            AnthropicPlatform.AMAZON_BEDROCK,
            AnthropicPlatform.GOOGLE_VERTEX,
        }:
            raise ProviderCompatibilityFailure("authentication_ownership_incompatible")
        reference = authentication.secret_reference
        if reference is None:
            raise ProviderAuthenticationFailure("secret_reference_missing")
        if self.secrets is None:
            raise ProviderAuthenticationFailure("secret_resolver_unavailable")
        try:
            return self.secrets.resolve(reference, owner=ANTHROPIC_PROBE_OWNER)
        except SecretResolutionError as exc:
            raise ProviderAuthenticationFailure(f"secret_{exc.code.value}") from None


@dataclass(frozen=True)
class ClaudeEmbeddedProviderDecision:
    """N3 compatibility decision that preserves the negative N2-04 gate."""

    platform: AnthropicPlatform
    auth_mode: ClaudeSdkAuthMode | None
    protocol_compatible: bool
    structured_transport_ready: bool
    subscription_embedding_allowed: bool
    blockers: tuple[str, ...]


def official_anthropic_profile(
    *,
    secret_reference: SecretReference | None = None,
    default_models: tuple[ModelPurposeDefault, ...] = (),
    discovery_cache_ttl_seconds: int = ANTHROPIC_DISCOVERY_CACHE_TTL_SECONDS,
) -> ProviderProfile:
    """Build the immutable official Anthropic API endpoint template."""
    reference = secret_reference or SecretReference(
        SecretReferenceKind.ENVIRONMENT,
        ANTHROPIC_API_KEY_ENVIRONMENT,
    )
    return _build_profile(
        provider_id="anthropic",
        display_name="Anthropic",
        base_url=ANTHROPIC_OFFICIAL_BASE_URL,
        route_prefix="/v1",
        platform=AnthropicPlatform.ANTHROPIC_API,
        authentication=ProviderAuthentication(
            AuthenticationOwnership.SECRET_REFERENCE,
            reference,
        ),
        ownership=ProviderOwnership.BUILT_IN,
        default_models=default_models,
        discovery_cache_ttl_seconds=discovery_cache_ttl_seconds,
        capability_source="anthropic-official-contract",
    )


def custom_anthropic_compatible_profile(
    *,
    provider_id: str,
    display_name: str,
    base_url: str,
    route_prefix: str | None,
    authentication: ProviderAuthentication | None = None,
    ownership: ProviderOwnership = ProviderOwnership.USER,
    default_models: tuple[ModelPurposeDefault, ...] = (),
    proxy_policy_ref: str | None = None,
    tls_policy_ref: str | None = None,
    egress_policy_ref: str | None = None,
    offline: bool = False,
    discovery_cache_ttl_seconds: int = ANTHROPIC_DISCOVERY_CACHE_TTL_SECONDS,
) -> ProviderProfile:
    """Build a custom Messages-compatible endpoint without credential values."""
    resolved_authentication = authentication or ProviderAuthentication(
        AuthenticationOwnership.SECRET_REFERENCE,
        SecretReference(
            SecretReferenceKind.ENVIRONMENT,
            ANTHROPIC_API_KEY_ENVIRONMENT,
        ),
    )
    return _build_profile(
        provider_id=provider_id,
        display_name=display_name,
        base_url=base_url,
        route_prefix=route_prefix,
        platform=AnthropicPlatform.ANTHROPIC_API,
        authentication=resolved_authentication,
        ownership=ownership,
        default_models=default_models,
        proxy_policy_ref=proxy_policy_ref,
        tls_policy_ref=tls_policy_ref,
        egress_policy_ref=egress_policy_ref,
        offline=offline,
        discovery_cache_ttl_seconds=discovery_cache_ttl_seconds,
        capability_source="anthropic-compatible-template",
    )


def anthropic_cloud_profile(
    platform: AnthropicPlatform,
    *,
    provider_id: str,
    display_name: str,
    base_url: str,
    authentication: ProviderAuthentication | None = None,
    ownership: ProviderOwnership = ProviderOwnership.USER,
    default_models: tuple[ModelPurposeDefault, ...] = (),
    proxy_policy_ref: str | None = None,
    tls_policy_ref: str | None = None,
    egress_policy_ref: str | None = None,
    offline: bool = False,
) -> ProviderProfile:
    """Build a provider-native Bedrock, Vertex, or Foundry route template."""
    if not isinstance(platform, AnthropicPlatform) or (
        platform is AnthropicPlatform.ANTHROPIC_API
    ):
        raise ValueError("Anthropic cloud platform is invalid")
    resolved_authentication = authentication or ProviderAuthentication(
        AuthenticationOwnership.PROVIDER_NATIVE
    )
    return _build_profile(
        provider_id=provider_id,
        display_name=display_name,
        base_url=base_url,
        route_prefix=None,
        platform=platform,
        authentication=resolved_authentication,
        ownership=ownership,
        default_models=default_models,
        proxy_policy_ref=proxy_policy_ref,
        tls_policy_ref=tls_policy_ref,
        egress_policy_ref=egress_policy_ref,
        offline=offline,
        discovery_cache_ttl_seconds=0,
        capability_source=f"{platform.value}-official-contract",
    )


def anthropic_compatible_route(
    provider: ProviderProfile,
    *,
    route_id: str,
    model: str,
    purpose: ModelPurpose,
    capability_evidence: tuple[SnapshotEvidenceRef, ...] | None = None,
) -> RouteProfile:
    """Bind one Anthropic-compatible purpose to an exact provider revision."""
    _platform_for_profile(provider)
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


def parse_anthropic_models_response(payload: Any) -> tuple[str, ...]:
    """Parse one bounded Models API page without inferring model features."""
    if not isinstance(payload, Mapping):
        raise ValueError("Anthropic models response must be an object")
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("Anthropic models response data must be a list")
    if len(data) > MAX_ANTHROPIC_MODELS:
        raise ValueError("Anthropic models response is too large")
    has_more = payload.get("has_more", False)
    if not isinstance(has_more, bool):
        raise ValueError("Anthropic models pagination state is invalid")
    if has_more:
        raise ValueError("Anthropic models response requires another page")
    models: list[str] = []
    for item in data:
        if not isinstance(item, Mapping):
            raise ValueError("Anthropic model entry must be an object")
        if item.get("type") not in {None, "model"}:
            raise ValueError("Anthropic model type is invalid")
        models.append(_normalize_model(item.get("id")))
    return tuple(sorted(set(models)))


def claude_code_anthropic_api_compatibility() -> AdapterProtocolCompatibility:
    """Return Claude Code evidence for direct Messages-compatible routes."""
    return _claude_compatibility(
        compatibility_id="anthropic-compatible-claude-code",
        dialects=(ANTHROPIC_MESSAGES_DIALECT,),
        native_auth=False,
    )


def claude_code_anthropic_cloud_compatibility() -> AdapterProtocolCompatibility:
    """Return Claude Code evidence for provider-native cloud routes."""
    return _claude_compatibility(
        compatibility_id="anthropic-cloud-claude-code",
        dialects=(
            ANTHROPIC_BEDROCK_DIALECT,
            ANTHROPIC_VERTEX_DIALECT,
            ANTHROPIC_FOUNDRY_DIALECT,
        ),
        native_auth=True,
    )


def claude_agent_sdk_provider_decision(
    profile: ProviderProfile,
) -> ClaudeEmbeddedProviderDecision:
    """Map reviewed provider auth while retaining the blocked embedded driver."""
    platform = _platform_for_profile(profile)
    ownership = profile.authentication.ownership
    auth_mode: ClaudeSdkAuthMode | None = None
    blockers = ["n2_04_embedded_driver_blocked"]
    if platform is AnthropicPlatform.ANTHROPIC_API:
        if ownership is AuthenticationOwnership.SECRET_REFERENCE:
            auth_mode = ClaudeSdkAuthMode.API_KEY
        else:
            blockers.append("sdk_authentication_incompatible")
    elif platform is AnthropicPlatform.AMAZON_BEDROCK:
        auth_mode = ClaudeSdkAuthMode.BEDROCK
    elif platform is AnthropicPlatform.GOOGLE_VERTEX:
        auth_mode = ClaudeSdkAuthMode.VERTEX
    elif platform is AnthropicPlatform.MICROSOFT_FOUNDRY:
        auth_mode = ClaudeSdkAuthMode.FOUNDRY
    return ClaudeEmbeddedProviderDecision(
        platform=platform,
        auth_mode=auth_mode,
        protocol_compatible=auth_mode is not None,
        structured_transport_ready=False,
        subscription_embedding_allowed=False,
        blockers=tuple(blockers),
    )


def _build_profile(
    *,
    provider_id: str,
    display_name: str,
    base_url: str,
    route_prefix: str | None,
    platform: AnthropicPlatform,
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
    if not isinstance(platform, AnthropicPlatform):
        raise ValueError("Anthropic platform is invalid")
    _validate_authentication(platform, authentication)
    profile = ProviderProfile(
        id=provider_id,
        revision="pending",
        display_name=display_name,
        protocol=ProviderProtocol.ANTHROPIC_COMPATIBLE,
        dialect=platform.dialect,
        base_url=base_url,
        route_prefix=route_prefix,
        authentication=authentication,
        ownership=ownership,
        capability_evidence=_capability_evidence(platform, source=capability_source),
        default_models=default_models,
        proxy_policy_ref=proxy_policy_ref,
        tls_policy_ref=tls_policy_ref,
        egress_policy_ref=egress_policy_ref,
        offline=offline,
        discovery_strategy=platform.discovery_strategy,
        discovery_cache_ttl_seconds=discovery_cache_ttl_seconds,
    )
    semantic = provider_profile_to_dict(profile)
    semantic.pop("revision")
    return replace(profile, revision=_semantic_revision(semantic))


def _validate_authentication(
    platform: AnthropicPlatform,
    authentication: ProviderAuthentication,
) -> None:
    if not isinstance(authentication, ProviderAuthentication):
        raise ValueError("Anthropic authentication is invalid")
    ownership = authentication.ownership
    allowed = {
        AnthropicPlatform.ANTHROPIC_API: {
            AuthenticationOwnership.SECRET_REFERENCE,
            AuthenticationOwnership.NONE,
        },
        AnthropicPlatform.AMAZON_BEDROCK: {
            AuthenticationOwnership.PROVIDER_NATIVE,
        },
        AnthropicPlatform.GOOGLE_VERTEX: {
            AuthenticationOwnership.PROVIDER_NATIVE,
        },
        AnthropicPlatform.MICROSOFT_FOUNDRY: {
            AuthenticationOwnership.PROVIDER_NATIVE,
            AuthenticationOwnership.SECRET_REFERENCE,
        },
    }[platform]
    if ownership not in allowed:
        raise ValueError(f"{platform.value} authentication ownership is incompatible")


def _capability_evidence(
    platform: AnthropicPlatform,
    *,
    source: str,
) -> tuple[SnapshotEvidenceRef, ...]:
    contract = {
        "platform": platform.value,
        "dialect": platform.dialect,
        "models_discovery": platform.discovery_strategy,
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


def _claude_compatibility(
    *,
    compatibility_id: str,
    dialects: tuple[str, ...],
    native_auth: bool,
) -> AdapterProtocolCompatibility:
    adapter_version = _adapter_version()
    transports = (
        ExecutionTransport.NATIVE_TERMINAL,
        ExecutionTransport.ONE_SHOT,
    )
    semantic = {
        "harness_id": "claude-code",
        "adapter_version": adapter_version,
        "protocol": ProviderProtocol.ANTHROPIC_COMPATIBLE.value,
        "dialects": dialects,
        "transports": tuple(item.value for item in transports),
        "capabilities": ("chat", "streaming", "usage"),
        "native_auth": native_auth,
        "structured_transport": "blocked-by-n2-04",
    }
    revision = _semantic_revision(semantic)
    return AdapterProtocolCompatibility(
        id=compatibility_id,
        revision=revision,
        harness_id="claude-code",
        adapter_version=adapter_version,
        protocol=ProviderProtocol.ANTHROPIC_COMPATIBLE,
        dialects=dialects,
        transports=transports,
        capabilities=("chat", "streaming", "usage"),
        native_auth=native_auth,
        evidence=(
            SnapshotEvidenceRef(
                id=f"{compatibility_id}-fixture",
                revision=revision,
                status="supported",
                source="built-in-contract",
            ),
        ),
    )


def _platform_for_profile(profile: ProviderProfile) -> AnthropicPlatform:
    if not isinstance(profile, ProviderProfile):
        raise ProviderCompatibilityFailure("profile_invalid")
    if profile.protocol is not ProviderProtocol.ANTHROPIC_COMPATIBLE:
        raise ProviderCompatibilityFailure("protocol_incompatible")
    by_dialect = {item.dialect: item for item in AnthropicPlatform}
    try:
        platform = by_dialect[profile.dialect]
    except KeyError:
        raise ProviderCompatibilityFailure("dialect_incompatible") from None
    try:
        _validate_authentication(platform, profile.authentication)
    except ValueError:
        raise ProviderCompatibilityFailure(
            "authentication_ownership_incompatible"
        ) from None
    return platform


def _normalize_models(values: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(values, tuple) or len(values) > MAX_ANTHROPIC_MODELS:
        raise ValueError("Anthropic normalized models are invalid")
    return tuple(sorted({_normalize_model(value) for value in values}))


def _normalize_model(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Anthropic model id is invalid")
    normalized = value.strip()
    if len(normalized) > MAX_ANTHROPIC_MODEL_ID_CHARS or any(
        ord(character) < 32 for character in normalized
    ):
        raise ValueError("Anthropic model id is invalid")
    return normalized


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
        return metadata.version("gpt2giga-harness")
    except metadata.PackageNotFoundError:  # pragma: no cover - source checkout only
        return "0"


def _validate_reason_code(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or not all(character.isalnum() or character in "._-" for character in value)
    ):
        raise ValueError("Anthropic probe reason code is invalid")
