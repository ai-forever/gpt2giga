"""Provider-neutral profile contracts and pre-spawn compatibility admission."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
from importlib import metadata
from importlib.metadata import entry_points
import json
import re
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit, urlunsplit

from gpt2giga_harness.execution import (
    ExecutionTransport,
    ProviderRef,
    RouteRef,
    SnapshotEvidenceRef,
)
from gpt2giga_harness.registries import (
    EntryPointFamily,
    RegistrationOutcome,
    RegistryCollisionError,
    VersionedRegistryKernel,
)
from gpt2giga_harness.secrets import (
    SecretReference,
    SecretReferenceKind,
    secret_reference_from_dict,
    secret_reference_to_dict,
)
from gpt2giga_harness.types import redact_secrets


PROVIDER_PROFILE_SCHEMA_VERSION = 1
ROUTE_PROFILE_SCHEMA_VERSION = 1
PROVIDER_COMPATIBILITY_SCHEMA_VERSION = 1
NEUTRAL_PROVIDER_ENTRY_POINT_GROUP = "agent_workbench.provider_adapters.v1"
PROVIDER_ADAPTER_ENTRY_POINTS = EntryPointFamily(
    registry_id="provider_adapter",
    api_version=1,
    primary_group=NEUTRAL_PROVIDER_ENTRY_POINT_GROUP,
)
MAX_DISCOVERY_ERRORS = 20
MAX_DISCOVERY_ERROR_CHARS = 400
_IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+~-]{0,255}\Z")


class ProviderProtocol(str, Enum):
    """Protocol family spoken by one provider endpoint."""

    OPENAI_COMPATIBLE = "openai_compatible"
    ANTHROPIC_COMPATIBLE = "anthropic_compatible"
    GEMINI_COMPATIBLE = "gemini_compatible"


class ModelPurpose(str, Enum):
    """Independent purpose assigned to one model route."""

    CODING = "coding"
    TITLE = "title"
    EVALUATION = "evaluation"
    FALLBACK = "fallback"


class AuthenticationOwnership(str, Enum):
    """Owner that supplies authentication at execution time."""

    SECRET_REFERENCE = "secret_reference"
    PROVIDER_NATIVE = "provider_native"
    NONE = "none"


class ProviderOwnership(str, Enum):
    """Configuration source that owns a provider profile."""

    BUILT_IN = "built_in"
    USER = "user"
    PROJECT = "project"
    ENVIRONMENT = "environment"
    MANAGED_POLICY = "managed_policy"
    MIGRATED_LEGACY = "migrated_legacy"


@dataclass(frozen=True, order=True)
class ModelPurposeDefault:
    """Default model selected for one independent route purpose."""

    purpose: ModelPurpose
    model: str

    def __post_init__(self) -> None:
        if not isinstance(self.purpose, ModelPurpose):
            raise ValueError("model default purpose is invalid")
        _validate_text(self.model, field_name="default model")


@dataclass(frozen=True)
class ProviderAuthentication:
    """Reference-only provider authentication configuration."""

    ownership: AuthenticationOwnership
    secret_reference: SecretReference | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.ownership, AuthenticationOwnership):
            raise ValueError("authentication ownership is invalid")
        if self.ownership is AuthenticationOwnership.SECRET_REFERENCE:
            if not isinstance(self.secret_reference, SecretReference):
                raise ValueError("secret_reference authentication requires SecretRef")
            if self.secret_reference.kind is SecretReferenceKind.TEST:
                raise ValueError("test SecretRef cannot be persisted in a provider")
        elif self.secret_reference is not None:
            raise ValueError(
                "provider-native or unauthenticated profiles cannot retain SecretRef"
            )


@dataclass(frozen=True)
class ProviderProfile:
    """Strict persisted model-provider configuration without adapter claims."""

    id: str
    revision: str
    display_name: str
    protocol: ProviderProtocol
    dialect: str
    base_url: str
    route_prefix: str | None
    authentication: ProviderAuthentication
    ownership: ProviderOwnership
    capability_evidence: tuple[SnapshotEvidenceRef, ...] = ()
    default_models: tuple[ModelPurposeDefault, ...] = ()
    tls_policy_ref: str | None = None
    proxy_policy_ref: str | None = None
    egress_policy_ref: str | None = None
    offline: bool = False
    discovery_strategy: str = "none"
    discovery_cache_ttl_seconds: int = 0
    schema_version: int = PROVIDER_PROFILE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PROVIDER_PROFILE_SCHEMA_VERSION:
            raise ValueError("unsupported provider profile schema_version")
        _validate_identity(self.id, field_name="provider id")
        _validate_identity(self.revision, field_name="provider revision")
        _validate_text(self.display_name, field_name="provider display_name")
        if not isinstance(self.protocol, ProviderProtocol):
            raise ValueError("provider protocol is invalid")
        _validate_identity(self.dialect, field_name="provider dialect")
        object.__setattr__(self, "base_url", _canonical_base_url(self.base_url))
        object.__setattr__(
            self,
            "route_prefix",
            _canonical_route_prefix(self.route_prefix),
        )
        if not isinstance(self.authentication, ProviderAuthentication):
            raise ValueError("provider authentication is invalid")
        if not isinstance(self.ownership, ProviderOwnership):
            raise ValueError("provider ownership is invalid")
        object.__setattr__(
            self,
            "capability_evidence",
            _normalize_evidence(self.capability_evidence),
        )
        object.__setattr__(
            self,
            "default_models",
            _normalize_model_defaults(self.default_models),
        )
        for field_name in (
            "tls_policy_ref",
            "proxy_policy_ref",
            "egress_policy_ref",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _validate_identity(value, field_name=field_name)
        if not isinstance(self.offline, bool):
            raise ValueError("provider offline must be a boolean")
        _validate_identity(
            self.discovery_strategy,
            field_name="provider discovery_strategy",
        )
        _validate_non_negative_int(
            self.discovery_cache_ttl_seconds,
            field_name="provider discovery_cache_ttl_seconds",
        )

    @property
    def ref(self) -> ProviderRef:
        """Return the minimal immutable execution reference."""
        return ProviderRef(self.id, self.revision)

    @property
    def effective_base_url(self) -> str:
        """Return the endpoint after applying the reviewed route prefix."""
        if self.route_prefix is None:
            return self.base_url
        return f"{self.base_url.rstrip('/')}{self.route_prefix}"


@dataclass(frozen=True)
class RouteProfile:
    """Strict persisted model route, separate from execution composition."""

    id: str
    revision: str
    provider: ProviderRef
    protocol: ProviderProtocol
    dialect: str
    effective_base_url: str
    purpose: ModelPurpose
    model: str
    authentication_ownership: AuthenticationOwnership
    capability_evidence: tuple[SnapshotEvidenceRef, ...] = ()
    schema_version: int = ROUTE_PROFILE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != ROUTE_PROFILE_SCHEMA_VERSION:
            raise ValueError("unsupported route profile schema_version")
        _validate_identity(self.id, field_name="route id")
        _validate_identity(self.revision, field_name="route revision")
        if not isinstance(self.provider, ProviderRef):
            raise ValueError("route provider must be a ProviderRef")
        if not isinstance(self.protocol, ProviderProtocol):
            raise ValueError("route protocol is invalid")
        _validate_identity(self.dialect, field_name="route dialect")
        object.__setattr__(
            self,
            "effective_base_url",
            _canonical_base_url(self.effective_base_url),
        )
        if not isinstance(self.purpose, ModelPurpose):
            raise ValueError("route model purpose is invalid")
        _validate_text(self.model, field_name="route model")
        if not isinstance(self.authentication_ownership, AuthenticationOwnership):
            raise ValueError("route authentication ownership is invalid")
        object.__setattr__(
            self,
            "capability_evidence",
            _normalize_evidence(self.capability_evidence),
        )

    @property
    def ref(self) -> RouteRef:
        """Return the minimal immutable execution reference."""
        return RouteRef(self.id, self.revision, self.provider)


@dataclass(frozen=True)
class AdapterProtocolCompatibility:
    """Versioned evidence that one Harness adapter admits one protocol dialect."""

    id: str
    revision: str
    harness_id: str
    adapter_version: str
    protocol: ProviderProtocol
    dialects: tuple[str, ...]
    transports: tuple[ExecutionTransport, ...]
    capabilities: tuple[str, ...]
    native_auth: bool
    evidence: tuple[SnapshotEvidenceRef, ...]
    schema_version: int = PROVIDER_COMPATIBILITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PROVIDER_COMPATIBILITY_SCHEMA_VERSION:
            raise ValueError("unsupported provider compatibility schema_version")
        for name in ("id", "revision", "harness_id", "adapter_version"):
            _validate_identity(getattr(self, name), field_name=name)
        if not isinstance(self.protocol, ProviderProtocol):
            raise ValueError("compatibility protocol is invalid")
        object.__setattr__(
            self,
            "dialects",
            _normalize_identities(self.dialects, field_name="compatibility dialect"),
        )
        raw_transports = tuple(self.transports)
        if not raw_transports or any(
            not isinstance(item, ExecutionTransport) for item in raw_transports
        ):
            raise ValueError("compatibility transports are invalid")
        transports = tuple(sorted(set(raw_transports), key=lambda item: item.value))
        object.__setattr__(self, "transports", transports)
        object.__setattr__(
            self,
            "capabilities",
            _normalize_identities(
                self.capabilities,
                field_name="compatibility capability",
            ),
        )
        if not isinstance(self.native_auth, bool):
            raise ValueError("compatibility native_auth must be a boolean")
        normalized_evidence = _normalize_evidence(self.evidence)
        if not normalized_evidence:
            raise ValueError("compatibility requires immutable evidence")
        object.__setattr__(self, "evidence", normalized_evidence)


@dataclass(frozen=True)
class RouteAdmission:
    """Content-free result of provider/route compatibility validation."""

    provider: ProviderRef
    route: RouteRef
    compatibility_id: str
    compatibility_revision: str
    evidence: tuple[SnapshotEvidenceRef, ...]


class RouteCompatibilityError(ValueError):
    """Fail-closed reason for a route rejected before adapter spawn."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ProviderCompatibilityRegistry:
    """Discover adapter-to-provider evidence through the neutral registry kernel."""

    def __init__(self) -> None:
        self._kernel = VersionedRegistryKernel[AdapterProtocolCompatibility](
            PROVIDER_ADAPTER_ENTRY_POINTS
        )
        self.discovery_errors: list[str] = []

    def register(
        self,
        compatibility: AdapterProtocolCompatibility,
    ) -> RegistrationOutcome:
        """Register one runtime compatibility declaration."""
        return self._register(
            compatibility,
            identity=_compatibility_identity(compatibility),
            source=f"runtime:{compatibility.id}",
        )

    def _register(
        self,
        compatibility: AdapterProtocolCompatibility,
        *,
        identity: str,
        source: str,
        allow_equivalent_duplicate: bool = False,
    ) -> RegistrationOutcome:
        if not isinstance(compatibility, AdapterProtocolCompatibility):
            raise TypeError("provider entry point must return compatibility evidence")
        return self._kernel.register(
            item_id=compatibility.id,
            item=compatibility,
            identity=identity,
            source=source,
            allow_equivalent_duplicate=allow_equivalent_duplicate,
        )

    def list(self) -> tuple[AdapterProtocolCompatibility, ...]:
        """Return registered declarations in deterministic order."""
        return tuple(sorted(self._kernel.values(), key=lambda item: item.id))

    def load_entry_points(self) -> None:
        """Load third-party provider compatibility declarations."""
        try:
            all_entry_points = entry_points()
        except Exception as exc:  # pragma: no cover - defensive importlib path
            self._record_discovery_error(
                "Provider entry-point discovery failed: "
                f"{type(exc).__name__} (details omitted)."
            )
            return
        selected = sorted(
            _select_entry_points(
                all_entry_points,
                PROVIDER_ADAPTER_ENTRY_POINTS.primary_group,
            ),
            key=_entry_point_sort_key,
        )
        for entry_point in selected:
            entry_name = str(getattr(entry_point, "name", "<unnamed>"))
            source = (
                f"entry-point:{PROVIDER_ADAPTER_ENTRY_POINTS.primary_group}:"
                f"{entry_name}"
            )
            try:
                loaded = entry_point.load()
                compatibility = _load_entry_point_compatibility(loaded)
                self._register(
                    compatibility,
                    identity=_entry_point_identity(entry_point, loaded),
                    source=source,
                    allow_equivalent_duplicate=True,
                )
            except RegistryCollisionError as exc:
                self._record_discovery_error(
                    "Provider compatibility id collision for "
                    f"{exc.item_id!r}: keeping {exc.existing_source}; "
                    f"rejected {exc.incoming_source}."
                )
            except Exception as exc:  # pragma: no cover - plugin failure path
                self._record_discovery_error(
                    f"{source}: {type(exc).__name__} (details omitted)."
                )

    def admit(
        self,
        provider: ProviderProfile,
        route: RouteProfile,
        *,
        harness_id: str,
        adapter_version: str,
        transport: ExecutionTransport,
        required_capabilities: Iterable[str] = (),
    ) -> RouteAdmission:
        """Validate every compatibility axis before an adapter process can spawn."""
        _validate_profile_route(provider, route)
        _validate_identity(harness_id, field_name="harness id")
        _validate_identity(adapter_version, field_name="adapter version")
        if not isinstance(transport, ExecutionTransport):
            raise RouteCompatibilityError(
                "transport_invalid",
                "execution transport is invalid",
            )
        required = set(
            _normalize_identities(
                required_capabilities,
                field_name="required capability",
                allow_empty=True,
            )
        )
        candidates = [
            item
            for item in self._kernel.values()
            if item.harness_id == harness_id
            and item.adapter_version == adapter_version
            and item.protocol is provider.protocol
            and provider.dialect in item.dialects
        ]
        if not candidates:
            raise RouteCompatibilityError(
                "adapter_protocol_incompatible",
                "Harness adapter has no evidence for the selected protocol dialect",
            )
        transport_candidates = [
            item for item in candidates if transport in item.transports
        ]
        if not transport_candidates:
            raise RouteCompatibilityError(
                "transport_incompatible",
                "Harness adapter does not admit the selected transport",
            )
        if provider.authentication.ownership is AuthenticationOwnership.PROVIDER_NATIVE:
            transport_candidates = [
                item for item in transport_candidates if item.native_auth
            ]
            if not transport_candidates:
                raise RouteCompatibilityError(
                    "native_auth_incompatible",
                    "Harness adapter has no native-auth evidence for this route",
                )
        provider_capabilities = _supported_capabilities(provider.capability_evidence)
        route_capabilities = _supported_capabilities(route.capability_evidence)
        if route.capability_evidence:
            provider_capabilities &= route_capabilities
        capable = [
            item
            for item in transport_candidates
            if required <= provider_capabilities and required <= set(item.capabilities)
        ]
        if not capable:
            raise RouteCompatibilityError(
                "capability_incompatible",
                "selected provider route lacks required capability evidence",
            )
        selected = sorted(capable, key=lambda item: item.id)[0]
        return RouteAdmission(
            provider=provider.ref,
            route=route.ref,
            compatibility_id=selected.id,
            compatibility_revision=selected.revision,
            evidence=selected.evidence,
        )

    @classmethod
    def with_builtins(cls) -> "ProviderCompatibilityRegistry":
        """Create a registry with conservative legacy compatibility evidence."""
        registry = cls()
        from gpt2giga_harness.anthropic_compatible import (
            claude_code_anthropic_api_compatibility,
            claude_code_anthropic_cloud_compatibility,
        )
        from gpt2giga_harness.openai_compatible import (
            codex_openai_compatibility,
            direct_chat_openai_compatibility,
        )
        from gpt2giga_harness.gemini_compatible import (
            gemini_cli_api_compatibility,
            gemini_cli_vertex_compatibility,
        )

        factories = (
            *_BUILTIN_COMPATIBILITY_FACTORIES,
            direct_chat_openai_compatibility,
            codex_openai_compatibility,
            claude_code_anthropic_api_compatibility,
            claude_code_anthropic_cloud_compatibility,
            gemini_cli_api_compatibility,
            gemini_cli_vertex_compatibility,
        )
        for factory in factories:
            registry._register(
                factory(),
                identity=_implementation_identity(factory),
                source=f"built-in:{factory.__name__}",
            )
        return registry

    def _record_discovery_error(self, message: str) -> None:
        if len(self.discovery_errors) >= MAX_DISCOVERY_ERRORS:
            return
        safe_message = str(redact_secrets(message))
        self.discovery_errors.append(safe_message[:MAX_DISCOVERY_ERROR_CHARS])


def migrate_legacy_provider_route(
    *,
    proxy_url: str,
    api_mode: str,
    harness_id: str,
    model: str,
    purpose: ModelPurpose = ModelPurpose.CODING,
    secret_reference: SecretReference | None = None,
) -> tuple[ProviderProfile, RouteProfile]:
    """Map legacy proxy/api-mode values without changing their effective URL."""
    protocol = _legacy_protocol(harness_id)
    normalized_mode = str(api_mode).strip().lower()
    if normalized_mode not in {"v1", "v2"}:
        raise ValueError("legacy api_mode must be v1 or v2")
    if not isinstance(purpose, ModelPurpose):
        raise ValueError("legacy model purpose is invalid")
    _validate_text(model, field_name="legacy model")
    base_url = _canonical_base_url(proxy_url)
    dialect = f"gpt2giga-{normalized_mode}"
    reference = secret_reference or SecretReference(
        kind=SecretReferenceKind.ENVIRONMENT,
        name="GPT2GIGA_HARNESS_API_KEY",
    )
    semantic = {
        "proxy_url": base_url,
        "api_mode": normalized_mode,
        "protocol": protocol.value,
        "harness_id": harness_id,
        "model": model,
        "purpose": purpose.value,
        "secret_reference": secret_reference_to_dict(reference),
    }
    fingerprint = hashlib.sha256(
        json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    evidence = (
        SnapshotEvidenceRef(
            id=f"legacy-{harness_id}-{normalized_mode}",
            revision=fingerprint,
            status="supported",
            source="legacy-migration",
        ),
    )
    capabilities = tuple(
        SnapshotEvidenceRef(
            id=capability,
            revision=fingerprint,
            status="supported",
            source="legacy-migration",
        )
        for capability in _LEGACY_CAPABILITIES[harness_id]
    )
    provider = ProviderProfile(
        id=f"legacy-gpt2giga-{protocol.value.replace('_', '-')}",
        revision=fingerprint,
        display_name="Migrated gpt2giga proxy",
        protocol=protocol,
        dialect=dialect,
        base_url=base_url,
        route_prefix=f"/{normalized_mode}",
        authentication=ProviderAuthentication(
            ownership=AuthenticationOwnership.SECRET_REFERENCE,
            secret_reference=reference,
        ),
        ownership=ProviderOwnership.MIGRATED_LEGACY,
        capability_evidence=capabilities,
        default_models=(ModelPurposeDefault(purpose, model),),
        discovery_strategy="legacy-models-route",
    )
    route = RouteProfile(
        id=f"legacy-{harness_id}-{normalized_mode}-{purpose.value}",
        revision=fingerprint,
        provider=provider.ref,
        protocol=protocol,
        dialect=dialect,
        effective_base_url=provider.effective_base_url,
        purpose=purpose,
        model=model,
        authentication_ownership=AuthenticationOwnership.SECRET_REFERENCE,
        capability_evidence=(*capabilities, *evidence),
    )
    return provider, route


def provider_profile_to_dict(profile: ProviderProfile) -> dict[str, Any]:
    """Serialize a strict, reference-only provider profile."""
    return {
        "schema_version": profile.schema_version,
        "id": profile.id,
        "revision": profile.revision,
        "display_name": profile.display_name,
        "protocol": profile.protocol.value,
        "dialect": profile.dialect,
        "base_url": profile.base_url,
        "route_prefix": profile.route_prefix,
        "authentication": _authentication_to_dict(profile.authentication),
        "ownership": profile.ownership.value,
        "capability_evidence": [
            _evidence_to_dict(item) for item in profile.capability_evidence
        ],
        "default_models": [
            {"purpose": item.purpose.value, "model": item.model}
            for item in profile.default_models
        ],
        "tls_policy_ref": profile.tls_policy_ref,
        "proxy_policy_ref": profile.proxy_policy_ref,
        "egress_policy_ref": profile.egress_policy_ref,
        "offline": profile.offline,
        "discovery_strategy": profile.discovery_strategy,
        "discovery_cache_ttl_seconds": profile.discovery_cache_ttl_seconds,
    }


def provider_profile_from_dict(data: Mapping[str, Any]) -> ProviderProfile:
    """Parse a forward-only provider profile and reject value-bearing extras."""
    mapping = _strict_mapping(
        data,
        allowed={
            "schema_version",
            "id",
            "revision",
            "display_name",
            "protocol",
            "dialect",
            "base_url",
            "route_prefix",
            "authentication",
            "ownership",
            "capability_evidence",
            "default_models",
            "tls_policy_ref",
            "proxy_policy_ref",
            "egress_policy_ref",
            "offline",
            "discovery_strategy",
            "discovery_cache_ttl_seconds",
        },
        field_name="provider profile",
    )
    if mapping.get("schema_version") != PROVIDER_PROFILE_SCHEMA_VERSION:
        raise ValueError("unsupported provider profile schema_version")
    return ProviderProfile(
        id=_required_text(mapping.get("id"), field_name="provider id"),
        revision=_required_text(
            mapping.get("revision"), field_name="provider revision"
        ),
        display_name=_required_text(
            mapping.get("display_name"), field_name="provider display_name"
        ),
        protocol=_enum_value(
            ProviderProtocol,
            mapping.get("protocol"),
            field_name="provider protocol",
        ),
        dialect=_required_text(mapping.get("dialect"), field_name="provider dialect"),
        base_url=_required_text(
            mapping.get("base_url"), field_name="provider base_url"
        ),
        route_prefix=_optional_text(mapping.get("route_prefix")),
        authentication=_authentication_from_dict(mapping.get("authentication")),
        ownership=_enum_value(
            ProviderOwnership,
            mapping.get("ownership"),
            field_name="provider ownership",
        ),
        capability_evidence=_evidence_from_list(
            mapping.get("capability_evidence"),
            field_name="provider capability_evidence",
        ),
        default_models=_model_defaults_from_list(mapping.get("default_models")),
        tls_policy_ref=_optional_text(mapping.get("tls_policy_ref")),
        proxy_policy_ref=_optional_text(mapping.get("proxy_policy_ref")),
        egress_policy_ref=_optional_text(mapping.get("egress_policy_ref")),
        offline=_required_bool(mapping.get("offline"), field_name="provider offline"),
        discovery_strategy=_required_text(
            mapping.get("discovery_strategy"),
            field_name="provider discovery_strategy",
        ),
        discovery_cache_ttl_seconds=_required_int(
            mapping.get("discovery_cache_ttl_seconds"),
            field_name="provider discovery_cache_ttl_seconds",
        ),
        schema_version=PROVIDER_PROFILE_SCHEMA_VERSION,
    )


def route_profile_to_dict(profile: RouteProfile) -> dict[str, Any]:
    """Serialize a strict provider-bound route profile."""
    return {
        "schema_version": profile.schema_version,
        "id": profile.id,
        "revision": profile.revision,
        "provider": {"id": profile.provider.id, "revision": profile.provider.revision},
        "protocol": profile.protocol.value,
        "dialect": profile.dialect,
        "effective_base_url": profile.effective_base_url,
        "purpose": profile.purpose.value,
        "model": profile.model,
        "authentication_ownership": profile.authentication_ownership.value,
        "capability_evidence": [
            _evidence_to_dict(item) for item in profile.capability_evidence
        ],
    }


def route_profile_from_dict(data: Mapping[str, Any]) -> RouteProfile:
    """Parse a forward-only route profile."""
    mapping = _strict_mapping(
        data,
        allowed={
            "schema_version",
            "id",
            "revision",
            "provider",
            "protocol",
            "dialect",
            "effective_base_url",
            "purpose",
            "model",
            "authentication_ownership",
            "capability_evidence",
        },
        field_name="route profile",
    )
    if mapping.get("schema_version") != ROUTE_PROFILE_SCHEMA_VERSION:
        raise ValueError("unsupported route profile schema_version")
    raw_provider = _strict_mapping(
        mapping.get("provider"),
        allowed={"id", "revision"},
        field_name="route provider",
    )
    return RouteProfile(
        id=_required_text(mapping.get("id"), field_name="route id"),
        revision=_required_text(mapping.get("revision"), field_name="route revision"),
        provider=ProviderRef(
            _required_text(raw_provider.get("id"), field_name="provider id"),
            _required_text(
                raw_provider.get("revision"), field_name="provider revision"
            ),
        ),
        protocol=_enum_value(
            ProviderProtocol,
            mapping.get("protocol"),
            field_name="route protocol",
        ),
        dialect=_required_text(mapping.get("dialect"), field_name="route dialect"),
        effective_base_url=_required_text(
            mapping.get("effective_base_url"),
            field_name="route effective_base_url",
        ),
        purpose=_enum_value(
            ModelPurpose,
            mapping.get("purpose"),
            field_name="route purpose",
        ),
        model=_required_text(mapping.get("model"), field_name="route model"),
        authentication_ownership=_enum_value(
            AuthenticationOwnership,
            mapping.get("authentication_ownership"),
            field_name="route authentication ownership",
        ),
        capability_evidence=_evidence_from_list(
            mapping.get("capability_evidence"),
            field_name="route capability_evidence",
        ),
        schema_version=ROUTE_PROFILE_SCHEMA_VERSION,
    )


def direct_chat_legacy_compatibility() -> AdapterProtocolCompatibility:
    """Return reviewed Direct Chat compatibility with legacy proxy routes."""
    return _legacy_compatibility(
        harness_id="direct-chat",
        protocol=ProviderProtocol.OPENAI_COMPATIBLE,
        transports=(ExecutionTransport.ONE_SHOT,),
        capabilities=("chat", "streaming", "tools"),
        native_auth=False,
    )


def codex_legacy_compatibility() -> AdapterProtocolCompatibility:
    """Return reviewed Codex compatibility with legacy proxy routes."""
    return _legacy_compatibility(
        harness_id="codex-cli",
        protocol=ProviderProtocol.OPENAI_COMPATIBLE,
        transports=(
            ExecutionTransport.NATIVE_STRUCTURED,
            ExecutionTransport.NATIVE_TERMINAL,
            ExecutionTransport.ONE_SHOT,
        ),
        capabilities=("chat", "streaming", "tools"),
        native_auth=False,
    )


def claude_legacy_compatibility() -> AdapterProtocolCompatibility:
    """Return bounded Claude compatibility without embedded structured claims."""
    return _legacy_compatibility(
        harness_id="claude-code",
        protocol=ProviderProtocol.ANTHROPIC_COMPATIBLE,
        transports=(
            ExecutionTransport.NATIVE_TERMINAL,
            ExecutionTransport.ONE_SHOT,
        ),
        capabilities=("chat", "streaming", "tools"),
        native_auth=False,
    )


def gemini_legacy_compatibility() -> AdapterProtocolCompatibility:
    """Return reviewed Gemini compatibility including ACP native auth evidence."""
    return _legacy_compatibility(
        harness_id="gemini-cli",
        protocol=ProviderProtocol.GEMINI_COMPATIBLE,
        transports=(
            ExecutionTransport.NATIVE_STRUCTURED,
            ExecutionTransport.NATIVE_TERMINAL,
            ExecutionTransport.ONE_SHOT,
        ),
        capabilities=("chat", "streaming", "tools"),
        native_auth=True,
    )


def _legacy_compatibility(
    *,
    harness_id: str,
    protocol: ProviderProtocol,
    transports: tuple[ExecutionTransport, ...],
    capabilities: tuple[str, ...],
    native_auth: bool,
) -> AdapterProtocolCompatibility:
    adapter_version = _adapter_version()
    semantic = f"{harness_id}:{adapter_version}:{protocol.value}:legacy-v1-v2"
    revision = hashlib.sha256(semantic.encode("utf-8")).hexdigest()
    return AdapterProtocolCompatibility(
        id=f"legacy-gpt2giga-{harness_id}",
        revision=revision,
        harness_id=harness_id,
        adapter_version=adapter_version,
        protocol=protocol,
        dialects=("gpt2giga-v1", "gpt2giga-v2"),
        transports=transports,
        capabilities=capabilities,
        native_auth=native_auth,
        evidence=(
            SnapshotEvidenceRef(
                id=f"legacy-{harness_id}-compatibility",
                revision=revision,
                status="supported",
                source="built-in-contract",
            ),
        ),
    )


_BUILTIN_COMPATIBILITY_FACTORIES = (
    direct_chat_legacy_compatibility,
    codex_legacy_compatibility,
    claude_legacy_compatibility,
    gemini_legacy_compatibility,
)
_LEGACY_PROTOCOLS = {
    "direct-chat": ProviderProtocol.OPENAI_COMPATIBLE,
    "codex-cli": ProviderProtocol.OPENAI_COMPATIBLE,
    "claude-code": ProviderProtocol.ANTHROPIC_COMPATIBLE,
    "gemini-cli": ProviderProtocol.GEMINI_COMPATIBLE,
}
_LEGACY_CAPABILITIES = {
    "direct-chat": ("chat", "streaming", "tools"),
    "codex-cli": ("chat", "streaming", "tools"),
    "claude-code": ("chat", "streaming", "tools"),
    "gemini-cli": ("chat", "streaming", "tools"),
}


def _validate_profile_route(
    provider: ProviderProfile,
    route: RouteProfile,
) -> None:
    if route.provider != provider.ref:
        raise RouteCompatibilityError(
            "provider_revision_mismatch",
            "route does not reference the selected provider revision",
        )
    if route.protocol is not provider.protocol:
        raise RouteCompatibilityError(
            "protocol_mismatch",
            "route protocol does not match its provider",
        )
    if route.dialect != provider.dialect:
        raise RouteCompatibilityError(
            "dialect_mismatch",
            "route dialect does not match its provider",
        )
    if route.effective_base_url != provider.effective_base_url:
        raise RouteCompatibilityError(
            "endpoint_mismatch",
            "route endpoint does not match its provider revision",
        )
    if route.authentication_ownership is not provider.authentication.ownership:
        raise RouteCompatibilityError(
            "authentication_mismatch",
            "route authentication ownership does not match its provider",
        )
    defaults = {item.purpose: item.model for item in provider.default_models}
    if route.purpose in defaults and defaults[route.purpose] != route.model:
        raise RouteCompatibilityError(
            "model_purpose_mismatch",
            "route model contradicts the provider purpose default",
        )


def _supported_capabilities(
    evidence: Iterable[SnapshotEvidenceRef],
) -> set[str]:
    return {item.id for item in evidence if item.status == "supported"}


def _normalize_model_defaults(
    defaults: Iterable[ModelPurposeDefault],
) -> tuple[ModelPurposeDefault, ...]:
    values = tuple(defaults)
    if any(not isinstance(item, ModelPurposeDefault) for item in values):
        raise ValueError("provider model defaults are invalid")
    normalized = tuple(sorted(values, key=lambda item: item.purpose.value))
    if len({item.purpose for item in normalized}) != len(normalized):
        raise ValueError("provider model defaults contain duplicate purposes")
    return normalized


def _normalize_evidence(
    evidence: Iterable[SnapshotEvidenceRef],
) -> tuple[SnapshotEvidenceRef, ...]:
    values = tuple(evidence)
    if any(not isinstance(item, SnapshotEvidenceRef) for item in values):
        raise ValueError("capability evidence is invalid")
    normalized = tuple(sorted(values, key=lambda item: (item.id, item.revision)))
    if len({item.id for item in normalized}) != len(normalized):
        raise ValueError("capability evidence contains duplicate ids")
    return normalized


def _normalize_identities(
    values: Iterable[str],
    *,
    field_name: str,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    normalized = tuple(sorted(set(values)))
    if not normalized and not allow_empty:
        raise ValueError(f"{field_name} is required")
    for value in normalized:
        _validate_identity(value, field_name=field_name)
    return normalized


def _canonical_base_url(value: str) -> str:
    _validate_text(value, field_name="base URL")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("base URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("base URL cannot contain credentials, query, or fragment")
    path = parsed.path.rstrip("/")
    if any(part == ".." for part in path.split("/")):
        raise ValueError("base URL path cannot traverse parents")
    netloc = parsed.netloc.lower()
    return urlunsplit((parsed.scheme.lower(), netloc, path, "", ""))


def _canonical_route_prefix(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if not text.startswith("/") or "?" in text or "#" in text:
        raise ValueError("route prefix must be an absolute URL path")
    normalized = "/" + text.strip("/")
    if any(part == ".." for part in normalized.split("/")):
        raise ValueError("route prefix cannot traverse parents")
    return normalized


def _authentication_to_dict(value: ProviderAuthentication) -> dict[str, Any]:
    return {
        "ownership": value.ownership.value,
        "secret_reference": (
            secret_reference_to_dict(value.secret_reference)
            if value.secret_reference is not None
            else None
        ),
    }


def _authentication_from_dict(value: Any) -> ProviderAuthentication:
    mapping = _strict_mapping(
        value,
        allowed={"ownership", "secret_reference"},
        field_name="provider authentication",
    )
    raw_reference = mapping.get("secret_reference")
    return ProviderAuthentication(
        ownership=_enum_value(
            AuthenticationOwnership,
            mapping.get("ownership"),
            field_name="authentication ownership",
        ),
        secret_reference=(
            secret_reference_from_dict(raw_reference)
            if isinstance(raw_reference, Mapping)
            else None
        ),
    )


def _evidence_to_dict(value: SnapshotEvidenceRef) -> dict[str, str]:
    return {
        "id": value.id,
        "revision": value.revision,
        "status": value.status,
        "source": value.source,
    }


def _evidence_from_list(
    value: Any, *, field_name: str
) -> tuple[SnapshotEvidenceRef, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    parsed: list[SnapshotEvidenceRef] = []
    for item in value:
        mapping = _strict_mapping(
            item,
            allowed={"id", "revision", "status", "source"},
            field_name=field_name,
        )
        parsed.append(
            SnapshotEvidenceRef(
                id=_required_text(mapping.get("id"), field_name="evidence id"),
                revision=_required_text(
                    mapping.get("revision"), field_name="evidence revision"
                ),
                status=_required_text(
                    mapping.get("status"), field_name="evidence status"
                ),
                source=_required_text(
                    mapping.get("source"), field_name="evidence source"
                ),
            )
        )
    return tuple(parsed)


def _model_defaults_from_list(value: Any) -> tuple[ModelPurposeDefault, ...]:
    if not isinstance(value, list):
        raise ValueError("provider default_models must be a list")
    parsed: list[ModelPurposeDefault] = []
    for item in value:
        mapping = _strict_mapping(
            item,
            allowed={"purpose", "model"},
            field_name="provider model default",
        )
        parsed.append(
            ModelPurposeDefault(
                purpose=_enum_value(
                    ModelPurpose,
                    mapping.get("purpose"),
                    field_name="model default purpose",
                ),
                model=_required_text(
                    mapping.get("model"), field_name="model default model"
                ),
            )
        )
    return tuple(parsed)


def _legacy_protocol(harness_id: str) -> ProviderProtocol:
    _validate_identity(harness_id, field_name="legacy harness id")
    try:
        return _LEGACY_PROTOCOLS[harness_id]
    except KeyError as exc:
        raise ValueError("legacy harness has no reviewed provider protocol") from exc


def _adapter_version() -> str:
    try:
        value = metadata.version("gigaloom")
    except metadata.PackageNotFoundError:
        return "source"
    return value.strip() or "source"


def _compatibility_identity(value: AdapterProtocolCompatibility) -> str:
    payload = {
        "id": value.id,
        "revision": value.revision,
        "harness_id": value.harness_id,
        "adapter_version": value.adapter_version,
        "protocol": value.protocol.value,
        "dialects": value.dialects,
        "transports": tuple(item.value for item in value.transports),
        "capabilities": value.capabilities,
        "native_auth": value.native_auth,
        "evidence": tuple(_evidence_to_dict(item) for item in value.evidence),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _select_entry_points(all_entry_points, group: str):
    if hasattr(all_entry_points, "select"):
        return all_entry_points.select(group=group)
    return all_entry_points.get(group, ())


def _entry_point_sort_key(entry_point) -> tuple[str, str]:
    return (
        str(getattr(entry_point, "name", "")),
        str(getattr(entry_point, "value", "")),
    )


def _entry_point_identity(entry_point, loaded) -> str:
    value = getattr(entry_point, "value", None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return _implementation_identity(loaded)


def _implementation_identity(implementation) -> str:
    module = getattr(implementation, "__module__", type(implementation).__module__)
    qualname = getattr(
        implementation,
        "__qualname__",
        type(implementation).__qualname__,
    )
    return f"{module}:{qualname}"


def _load_entry_point_compatibility(loaded) -> AdapterProtocolCompatibility:
    value = loaded() if callable(loaded) else loaded
    if not isinstance(value, AdapterProtocolCompatibility):
        raise TypeError("provider entry point did not create compatibility evidence")
    return value


def _strict_mapping(
    value: Any,
    *,
    allowed: set[str],
    field_name: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"unknown {field_name} fields: {sorted(unknown)}")
    return value


def _enum_value(enum_type, value: Any, *, field_name: str):
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} is invalid") from exc


def _required_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("optional text value is invalid")
    return value.strip() or None


def _required_bool(value: Any, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _required_int(value: Any, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _validate_identity(value: str, *, field_name: str) -> None:
    if not isinstance(value, str) or not _IDENTITY_RE.fullmatch(value):
        raise ValueError(f"{field_name} is invalid")


def _validate_text(value: str, *, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{field_name} is invalid")


def _validate_non_negative_int(value: int, *, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
