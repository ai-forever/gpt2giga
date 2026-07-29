"""Gemini-compatible provider templates and hermetic probe contracts."""

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


GEMINI_OFFICIAL_BASE_URL = "https://generativelanguage.googleapis.com"
GEMINI_VERTEX_BASE_URL = "https://aiplatform.googleapis.com"
GEMINI_API_KEY_ENVIRONMENT = "GEMINI_API_KEY"
GOOGLE_API_KEY_ENVIRONMENT = "GOOGLE_API_KEY"
GEMINI_GENERATE_CONTENT_DIALECT = "gemini-generate-content-v1beta"
GEMINI_VERTEX_DIALECT = "gemini-vertex-v1"
GEMINI_MODELS_DISCOVERY_STRATEGY = "gemini-models-v1beta"
GEMINI_VERTEX_DISCOVERY_STRATEGY = "gemini-vertex-models-v1"
GEMINI_PROBE_OWNER = "provider-probe:gemini-compatible"
GEMINI_DISCOVERY_CACHE_TTL_SECONDS = 300
MAX_GEMINI_MODELS = 1000
MAX_GEMINI_MODEL_ID_CHARS = 256


class GeminiPlatform(str, Enum):
    """Reviewed Gemini protocol platform with distinct auth ownership."""

    GEMINI_API = "gemini_api"
    VERTEX_AI = "vertex_ai"

    @property
    def dialect(self) -> str:
        """Return the stable provider-profile dialect identifier."""
        if self is GeminiPlatform.GEMINI_API:
            return GEMINI_GENERATE_CONTENT_DIALECT
        return GEMINI_VERTEX_DIALECT

    @property
    def discovery_strategy(self) -> str:
        """Return the discovery contract owned by this platform."""
        if self is GeminiPlatform.GEMINI_API:
            return GEMINI_MODELS_DISCOVERY_STRATEGY
        return GEMINI_VERTEX_DISCOVERY_STRATEGY


class GeminiCliAuthMode(str, Enum):
    """Reviewed Gemini CLI auth selectors without credential material."""

    GOOGLE_LOGIN = "oauth-personal"
    GEMINI_API_KEY = "gemini-api-key"
    VERTEX_AI = "vertex-ai"
    GATEWAY = "gateway"


@dataclass(frozen=True)
class GeminiProbeTransportRequest:
    """Runtime-only Gemini probe input with an optional opaque credential."""

    provider: ProviderRef
    platform: GeminiPlatform
    probe_url: str
    timeout_seconds: float
    discover_models: bool
    credential: ResolvedSecret | None
    proxy_policy_ref: str | None
    tls_policy_ref: str | None
    egress_policy_ref: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.provider, ProviderRef):
            raise ValueError("Gemini probe provider is invalid")
        if not isinstance(self.platform, GeminiPlatform):
            raise ValueError("Gemini probe platform is invalid")
        if not isinstance(self.probe_url, str) or not self.probe_url.startswith(
            ("http://", "https://")
        ):
            raise ValueError("Gemini probe URL is invalid")
        if "@" in self.probe_url.split("://", 1)[-1].split("/", 1)[0]:
            raise ValueError("Gemini probe URL cannot contain credentials")
        if self.platform is GeminiPlatform.GEMINI_API and not self.probe_url.endswith(
            "/models"
        ):
            raise ValueError("Gemini models probe URL is invalid")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or self.timeout_seconds <= 0
        ):
            raise ValueError("Gemini probe timeout is invalid")
        if not isinstance(self.discover_models, bool):
            raise ValueError("Gemini probe discovery flag is invalid")
        if self.credential is not None and not isinstance(
            self.credential, ResolvedSecret
        ):
            raise ValueError("Gemini probe credential must remain opaque")


@dataclass(frozen=True)
class GeminiTransportResponse:
    """Connection result returned by an injected Gemini transport."""

    payload: Mapping[str, Any] | None = None
    models: tuple[str, ...] = ()
    discovery_succeeded: bool = True
    discovery_reason_code: str | None = None

    def __post_init__(self) -> None:
        if self.payload is not None and not isinstance(self.payload, Mapping):
            raise ValueError("Gemini transport payload must be an object")
        object.__setattr__(self, "models", _normalize_models(self.models))
        if self.payload is not None and self.models:
            raise ValueError("Gemini transport cannot return raw and normalized models")
        if not isinstance(self.discovery_succeeded, bool):
            raise ValueError("Gemini transport discovery state is invalid")
        if self.discovery_succeeded == (self.discovery_reason_code is not None):
            raise ValueError("Gemini transport discovery reason is inconsistent")
        if self.discovery_reason_code is not None:
            _validate_reason_code(self.discovery_reason_code)

    def __repr__(self) -> str:
        payload_state = "present" if self.payload is not None else "absent"
        return (
            "GeminiTransportResponse("
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


class GeminiProbeTransport(Protocol):
    """Injected owner of HTTP/cloud I/O, policy, and credential reveal."""

    def probe(self, request: GeminiProbeTransportRequest) -> GeminiTransportResponse:
        """Check the endpoint and optionally return model evidence."""


class GeminiProbeError(RuntimeError):
    """Stable provider-specific failure without response bodies or credentials."""

    def __init__(self, reason_code: str) -> None:
        _validate_reason_code(reason_code)
        super().__init__(reason_code)
        self.reason_code = reason_code


class GeminiProbeAuthenticationError(GeminiProbeError):
    """Gemini-compatible authentication was rejected."""


class GeminiProbeCompatibilityError(GeminiProbeError):
    """Endpoint, platform, or dialect compatibility was rejected."""


class GeminiProbeProviderHealthError(GeminiProbeError):
    """Provider responded but was unavailable or unhealthy."""


class GeminiProbeTransportError(GeminiProbeError):
    """Network or cloud transport failed before a provider response."""


class GeminiCompatibleProbeBackend:
    """Resolve explicit auth at the final boundary and normalize discovery."""

    def __init__(
        self,
        transport: GeminiProbeTransport,
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
        credential = self._resolve_credential(profile)
        transport_request = GeminiProbeTransportRequest(
            provider=profile.ref,
            platform=platform,
            probe_url=(
                f"{profile.effective_base_url.rstrip('/')}/models"
                if platform is GeminiPlatform.GEMINI_API
                else profile.effective_base_url
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
        except GeminiProbeAuthenticationError as exc:
            raise ProviderAuthenticationFailure(exc.reason_code) from None
        except GeminiProbeCompatibilityError as exc:
            raise ProviderCompatibilityFailure(exc.reason_code) from None
        except GeminiProbeProviderHealthError as exc:
            raise ProviderHealthFailure(exc.reason_code) from None
        except GeminiProbeTransportError as exc:
            raise ProviderTransportFailure(exc.reason_code) from None
        if not isinstance(response, GeminiTransportResponse):
            raise ProviderCompatibilityFailure("invalid_probe_response")
        if not request.discover_models:
            return ProviderProbeResponse()
        if not response.discovery_succeeded:
            return ProviderProbeResponse(
                discovery_succeeded=False,
                discovery_reason_code=response.discovery_reason_code,
            )
        if platform is GeminiPlatform.VERTEX_AI:
            if response.payload is not None:
                raise ProviderCompatibilityFailure("invalid_platform_probe_response")
            return ProviderProbeResponse(models=response.models)
        if response.models:
            raise ProviderCompatibilityFailure("invalid_api_probe_response")
        try:
            models = parse_gemini_models_response(response.payload)
        except ValueError:
            return ProviderProbeResponse(
                discovery_succeeded=False,
                discovery_reason_code="invalid_models_response",
            )
        return ProviderProbeResponse(models=models)

    def _resolve_credential(self, profile: ProviderProfile) -> ResolvedSecret | None:
        authentication = profile.authentication
        if authentication.ownership in {
            AuthenticationOwnership.NONE,
            AuthenticationOwnership.PROVIDER_NATIVE,
        }:
            return None
        if authentication.ownership is not AuthenticationOwnership.SECRET_REFERENCE:
            raise ProviderCompatibilityFailure("authentication_ownership_incompatible")
        reference = authentication.secret_reference
        if reference is None:
            raise ProviderAuthenticationFailure("secret_reference_missing")
        if self.secrets is None:
            raise ProviderAuthenticationFailure("secret_resolver_unavailable")
        try:
            return self.secrets.resolve(reference, owner=GEMINI_PROBE_OWNER)
        except SecretResolutionError as exc:
            raise ProviderAuthenticationFailure(f"secret_{exc.code.value}") from None


@dataclass(frozen=True)
class GeminiNativeClientConfiguration:
    """Content-free Gemini CLI configuration evidence for one auth mode."""

    auth_mode: GeminiCliAuthMode
    provider: ProviderRef | None
    authentication_ownership: AuthenticationOwnership
    settings_auth_type: str
    environment_variables: tuple[str, ...]
    endpoint_override: bool
    oauth_token_access: bool
    evidence: tuple[SnapshotEvidenceRef, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.auth_mode, GeminiCliAuthMode):
            raise ValueError("Gemini CLI auth mode is invalid")
        if self.provider is not None and not isinstance(self.provider, ProviderRef):
            raise ValueError("Gemini CLI provider reference is invalid")
        if not isinstance(self.authentication_ownership, AuthenticationOwnership):
            raise ValueError("Gemini CLI authentication ownership is invalid")
        if self.settings_auth_type != self.auth_mode.value:
            raise ValueError("Gemini CLI settings auth type is inconsistent")
        raw_environment_variables = self.environment_variables
        if not isinstance(raw_environment_variables, tuple) or any(
            not isinstance(item, str)
            or not item
            or len(item) > 256
            or not item.replace("_", "").isalnum()
            or item.upper() != item
            for item in raw_environment_variables
        ):
            raise ValueError("Gemini CLI environment evidence is invalid")
        object.__setattr__(
            self,
            "environment_variables",
            tuple(sorted(set(raw_environment_variables))),
        )
        if not isinstance(self.endpoint_override, bool):
            raise ValueError("Gemini CLI endpoint override state is invalid")
        if not isinstance(self.oauth_token_access, bool):
            raise ValueError("Gemini OAuth token access state is invalid")
        if self.oauth_token_access:
            raise ValueError("Gemini OAuth token access is never permitted")
        if (
            not isinstance(self.evidence, tuple)
            or not self.evidence
            or any(not isinstance(item, SnapshotEvidenceRef) for item in self.evidence)
        ):
            raise ValueError("Gemini CLI configuration requires evidence")


def official_gemini_profile(
    *,
    secret_reference: SecretReference | None = None,
    default_models: tuple[ModelPurposeDefault, ...] = (),
    discovery_cache_ttl_seconds: int = GEMINI_DISCOVERY_CACHE_TTL_SECONDS,
) -> ProviderProfile:
    """Build the immutable official Gemini Developer API template."""
    reference = secret_reference or SecretReference(
        SecretReferenceKind.ENVIRONMENT,
        GEMINI_API_KEY_ENVIRONMENT,
    )
    return _build_profile(
        provider_id="gemini",
        display_name="Gemini",
        base_url=GEMINI_OFFICIAL_BASE_URL,
        route_prefix="/v1beta",
        platform=GeminiPlatform.GEMINI_API,
        authentication=ProviderAuthentication(
            AuthenticationOwnership.SECRET_REFERENCE,
            reference,
        ),
        ownership=ProviderOwnership.BUILT_IN,
        default_models=default_models,
        discovery_cache_ttl_seconds=discovery_cache_ttl_seconds,
        capability_source="gemini-official-contract",
    )


def custom_gemini_compatible_profile(
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
    discovery_cache_ttl_seconds: int = GEMINI_DISCOVERY_CACHE_TTL_SECONDS,
) -> ProviderProfile:
    """Build a custom GenerateContent-compatible endpoint without secret values."""
    resolved_authentication = authentication or ProviderAuthentication(
        AuthenticationOwnership.SECRET_REFERENCE,
        SecretReference(
            SecretReferenceKind.ENVIRONMENT,
            GEMINI_API_KEY_ENVIRONMENT,
        ),
    )
    return _build_profile(
        provider_id=provider_id,
        display_name=display_name,
        base_url=base_url,
        route_prefix=route_prefix,
        platform=GeminiPlatform.GEMINI_API,
        authentication=resolved_authentication,
        ownership=ownership,
        default_models=default_models,
        proxy_policy_ref=proxy_policy_ref,
        tls_policy_ref=tls_policy_ref,
        egress_policy_ref=egress_policy_ref,
        offline=offline,
        discovery_cache_ttl_seconds=discovery_cache_ttl_seconds,
        capability_source="gemini-compatible-template",
    )


def vertex_ai_gemini_profile(
    *,
    provider_id: str = "gemini-vertex",
    display_name: str = "Gemini on Vertex AI",
    base_url: str = GEMINI_VERTEX_BASE_URL,
    route_prefix: str | None = None,
    authentication: ProviderAuthentication | None = None,
    ownership: ProviderOwnership = ProviderOwnership.USER,
    default_models: tuple[ModelPurposeDefault, ...] = (),
    proxy_policy_ref: str | None = None,
    tls_policy_ref: str | None = None,
    egress_policy_ref: str | None = None,
    offline: bool = False,
) -> ProviderProfile:
    """Build a distinct Vertex AI template with native auth by default."""
    resolved_authentication = authentication or ProviderAuthentication(
        AuthenticationOwnership.PROVIDER_NATIVE
    )
    return _build_profile(
        provider_id=provider_id,
        display_name=display_name,
        base_url=base_url,
        route_prefix=route_prefix,
        platform=GeminiPlatform.VERTEX_AI,
        authentication=resolved_authentication,
        ownership=ownership,
        default_models=default_models,
        proxy_policy_ref=proxy_policy_ref,
        tls_policy_ref=tls_policy_ref,
        egress_policy_ref=egress_policy_ref,
        offline=offline,
        discovery_cache_ttl_seconds=0,
        capability_source="gemini-vertex-official-contract",
    )


def gemini_compatible_route(
    provider: ProviderProfile,
    *,
    route_id: str,
    model: str,
    purpose: ModelPurpose,
    capability_evidence: tuple[SnapshotEvidenceRef, ...] | None = None,
) -> RouteProfile:
    """Bind one Gemini-compatible purpose to an exact provider revision."""
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


def parse_gemini_models_response(payload: Any) -> tuple[str, ...]:
    """Parse one bounded Models API page without inferring model features."""
    if not isinstance(payload, Mapping):
        raise ValueError("Gemini models response must be an object")
    models_payload = payload.get("models")
    if not isinstance(models_payload, list):
        raise ValueError("Gemini models response models must be a list")
    if len(models_payload) > MAX_GEMINI_MODELS:
        raise ValueError("Gemini models response is too large")
    next_page_token = payload.get("nextPageToken")
    if next_page_token is not None and not isinstance(next_page_token, str):
        raise ValueError("Gemini models pagination state is invalid")
    if next_page_token:
        raise ValueError("Gemini models response requires another page")
    models: list[str] = []
    for item in models_payload:
        if not isinstance(item, Mapping):
            raise ValueError("Gemini model entry must be an object")
        name = item.get("name")
        if not isinstance(name, str) or not name.startswith("models/"):
            raise ValueError("Gemini model resource name is invalid")
        resource_model = name.removeprefix("models/")
        if not resource_model or "/" in resource_model:
            raise ValueError("Gemini model resource name is invalid")
        base_model_id = item.get("baseModelId", resource_model)
        models.append(_normalize_model(base_model_id))
    return tuple(sorted(set(models)))


def gemini_cli_configuration_evidence(
    auth_mode: GeminiCliAuthMode,
    profile: ProviderProfile | None = None,
    *,
    cli_version: str,
) -> GeminiNativeClientConfiguration:
    """Describe supported Gemini CLI configuration without reading native state."""
    if not isinstance(auth_mode, GeminiCliAuthMode):
        raise ValueError("Gemini CLI auth mode is invalid")
    if (
        not isinstance(cli_version, str)
        or not cli_version
        or len(cli_version) > 128
        or any(ord(character) < 32 for character in cli_version)
    ):
        raise ValueError("Gemini CLI version evidence is invalid")
    platform: GeminiPlatform | None = None
    if profile is not None:
        platform = _platform_for_profile(profile)
    if auth_mode is GeminiCliAuthMode.GOOGLE_LOGIN:
        if profile is not None:
            raise ValueError("Google login cannot be attached to an endpoint profile")
        ownership = AuthenticationOwnership.PROVIDER_NATIVE
        environment_variables = ("GOOGLE_CLOUD_PROJECT",)
        endpoint_override = False
    else:
        if profile is None or platform is None:
            raise ValueError("Gemini CLI endpoint auth requires a provider profile")
        ownership = profile.authentication.ownership
        if auth_mode is GeminiCliAuthMode.GEMINI_API_KEY:
            if platform is not GeminiPlatform.GEMINI_API or (
                ownership is not AuthenticationOwnership.SECRET_REFERENCE
            ):
                raise ValueError("Gemini API key mode requires a SecretRef API profile")
            environment_variables = (GEMINI_API_KEY_ENVIRONMENT,)
            endpoint_override = False
        elif auth_mode is GeminiCliAuthMode.GATEWAY:
            if platform is not GeminiPlatform.GEMINI_API or ownership not in {
                AuthenticationOwnership.SECRET_REFERENCE,
                AuthenticationOwnership.NONE,
            }:
                raise ValueError(
                    "Gemini gateway mode requires a compatible API profile"
                )
            environment_variables = ("GOOGLE_GEMINI_BASE_URL",)
            if ownership is AuthenticationOwnership.SECRET_REFERENCE:
                environment_variables += (GEMINI_API_KEY_ENVIRONMENT,)
            endpoint_override = True
        else:
            if platform is not GeminiPlatform.VERTEX_AI or ownership not in {
                AuthenticationOwnership.PROVIDER_NATIVE,
                AuthenticationOwnership.SECRET_REFERENCE,
            }:
                raise ValueError("Vertex mode requires a Vertex AI profile")
            environment_variables = (
                "GOOGLE_CLOUD_LOCATION",
                "GOOGLE_CLOUD_PROJECT",
                "GOOGLE_GENAI_USE_VERTEXAI",
            )
            if ownership is AuthenticationOwnership.SECRET_REFERENCE:
                environment_variables += (GOOGLE_API_KEY_ENVIRONMENT,)
            endpoint_override = False
    semantic = {
        "auth_mode": auth_mode.value,
        "provider": (
            {"id": profile.id, "revision": profile.revision}
            if profile is not None
            else None
        ),
        "authentication_ownership": ownership.value,
        "environment_variables": tuple(sorted(environment_variables)),
        "endpoint_override": endpoint_override,
        "oauth_token_access": False,
        "gemini_cli_version": cli_version,
    }
    revision = _semantic_revision(semantic)
    return GeminiNativeClientConfiguration(
        auth_mode=auth_mode,
        provider=profile.ref if profile is not None else None,
        authentication_ownership=ownership,
        settings_auth_type=auth_mode.value,
        environment_variables=environment_variables,
        endpoint_override=endpoint_override,
        oauth_token_access=False,
        evidence=(
            SnapshotEvidenceRef(
                id=f"gemini-cli-{auth_mode.value}-configuration",
                revision=revision,
                status="supported",
                source=f"installed-gemini-cli-{cli_version}",
            ),
        ),
    )


def gemini_cli_api_compatibility() -> AdapterProtocolCompatibility:
    """Return Gemini CLI evidence for API and custom gateway routes."""
    return _gemini_compatibility(
        compatibility_id="gemini-compatible-gemini-cli",
        dialects=(GEMINI_GENERATE_CONTENT_DIALECT,),
        native_auth=False,
    )


def gemini_cli_vertex_compatibility() -> AdapterProtocolCompatibility:
    """Return Gemini CLI evidence for provider-native Vertex AI routes."""
    return _gemini_compatibility(
        compatibility_id="gemini-vertex-gemini-cli",
        dialects=(GEMINI_VERTEX_DIALECT,),
        native_auth=True,
    )


def _build_profile(
    *,
    provider_id: str,
    display_name: str,
    base_url: str,
    route_prefix: str | None,
    platform: GeminiPlatform,
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
    if not isinstance(platform, GeminiPlatform):
        raise ValueError("Gemini platform is invalid")
    _validate_authentication(platform, authentication)
    profile = ProviderProfile(
        id=provider_id,
        revision="pending",
        display_name=display_name,
        protocol=ProviderProtocol.GEMINI_COMPATIBLE,
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
    platform: GeminiPlatform,
    authentication: ProviderAuthentication,
) -> None:
    if not isinstance(authentication, ProviderAuthentication):
        raise ValueError("Gemini authentication is invalid")
    allowed = {
        GeminiPlatform.GEMINI_API: {
            AuthenticationOwnership.SECRET_REFERENCE,
            AuthenticationOwnership.NONE,
        },
        GeminiPlatform.VERTEX_AI: {
            AuthenticationOwnership.PROVIDER_NATIVE,
            AuthenticationOwnership.SECRET_REFERENCE,
        },
    }[platform]
    if authentication.ownership not in allowed:
        raise ValueError(f"{platform.value} authentication ownership is incompatible")


def _capability_evidence(
    platform: GeminiPlatform,
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


def _gemini_compatibility(
    *,
    compatibility_id: str,
    dialects: tuple[str, ...],
    native_auth: bool,
) -> AdapterProtocolCompatibility:
    adapter_version = _adapter_version()
    transports = (
        ExecutionTransport.NATIVE_STRUCTURED,
        ExecutionTransport.NATIVE_TERMINAL,
        ExecutionTransport.ONE_SHOT,
    )
    semantic = {
        "harness_id": "gemini-cli",
        "adapter_version": adapter_version,
        "protocol": ProviderProtocol.GEMINI_COMPATIBLE.value,
        "dialects": dialects,
        "transports": tuple(item.value for item in transports),
        "capabilities": ("chat", "streaming", "usage"),
        "native_auth": native_auth,
        "reviewed_cli_window": "0.46.x",
        "structured_surface": "acp",
    }
    revision = _semantic_revision(semantic)
    return AdapterProtocolCompatibility(
        id=compatibility_id,
        revision=revision,
        harness_id="gemini-cli",
        adapter_version=adapter_version,
        protocol=ProviderProtocol.GEMINI_COMPATIBLE,
        dialects=dialects,
        transports=transports,
        capabilities=("chat", "streaming", "usage"),
        native_auth=native_auth,
        evidence=(
            SnapshotEvidenceRef(
                id=f"{compatibility_id}-fixture",
                revision=revision,
                status="supported",
                source="built-in-gemini-cli-0.46-contract",
            ),
        ),
    )


def _platform_for_profile(profile: ProviderProfile) -> GeminiPlatform:
    if not isinstance(profile, ProviderProfile):
        raise ProviderCompatibilityFailure("profile_invalid")
    if profile.protocol is not ProviderProtocol.GEMINI_COMPATIBLE:
        raise ProviderCompatibilityFailure("protocol_incompatible")
    by_dialect = {item.dialect: item for item in GeminiPlatform}
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
    if not isinstance(values, tuple) or len(values) > MAX_GEMINI_MODELS:
        raise ValueError("Gemini normalized models are invalid")
    return tuple(sorted({_normalize_model(value) for value in values}))


def _normalize_model(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Gemini model id is invalid")
    normalized = value.strip()
    if len(normalized) > MAX_GEMINI_MODEL_ID_CHARS or any(
        ord(character) < 32 for character in normalized
    ):
        raise ValueError("Gemini model id is invalid")
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
        return metadata.version("gigaloom")
    except metadata.PackageNotFoundError:  # pragma: no cover - source checkout
        return "0.0.0+source"


def _validate_reason_code(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789_-"
            for character in value
        )
    ):
        raise ValueError("Gemini reason code is invalid")
