"""Durable provider registry and bounded provider health checks."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Callable, Iterable, Mapping, Protocol

from gpt2giga_harness.execution import ProviderRef
from gpt2giga_harness.provider_profiles import (
    ProviderOwnership,
    ProviderProfile,
    RouteProfile,
    provider_profile_from_dict,
    provider_profile_to_dict,
    route_profile_from_dict,
    route_profile_to_dict,
)
from gpt2giga_harness.sessions.locking import exclusive_file_lock


PROVIDER_REGISTRY_SCHEMA_VERSION = 1
PROVIDER_HEALTH_SCHEMA_VERSION = 1
MAX_PROVIDER_MODELS = 500
MAX_PROVIDER_MODEL_CHARS = 256
MAX_PROVIDER_REASON_CHARS = 128
MAX_PROVIDER_CHECK_TIMEOUT_SECONDS = 30.0

PROVIDER_SOURCE_PRECEDENCE = (
    ProviderOwnership.MANAGED_POLICY,
    ProviderOwnership.ENVIRONMENT,
    ProviderOwnership.PROJECT,
    ProviderOwnership.USER,
    ProviderOwnership.MIGRATED_LEGACY,
    ProviderOwnership.BUILT_IN,
)


class ProviderRegistryConflict(RuntimeError):
    """Raised when provider registry state changed before a mutation."""


class ProviderRegistryOwnershipError(RuntimeError):
    """Raised when a mutation crosses its configured source owner."""


@dataclass(frozen=True)
class ProviderRegistryEntry:
    """One persisted provider, its routes, and its optimistic revision."""

    profile: ProviderProfile
    routes: tuple[RouteProfile, ...]
    enabled: bool
    revision: int
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.profile, ProviderProfile):
            raise ValueError("provider registry profile is invalid")
        routes = tuple(self.routes)
        if len({item.id for item in routes}) != len(routes):
            raise ValueError("provider registry route ids must be unique")
        for route in routes:
            _validate_route_binding(self.profile, route)
        object.__setattr__(
            self, "routes", tuple(sorted(routes, key=lambda item: item.id))
        )
        if not isinstance(self.enabled, bool):
            raise ValueError("provider registry enabled must be a boolean")
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 1
        ):
            raise ValueError("provider registry revision must be positive")
        _parse_timestamp(self.created_at)
        _parse_timestamp(self.updated_at)


@dataclass(frozen=True)
class EffectiveProvider:
    """One effective provider plus lower-precedence sources it shadows."""

    entry: ProviderRegistryEntry
    source: ProviderOwnership
    shadowed_sources: tuple[ProviderOwnership, ...] = ()


class ProviderRegistryStore:
    """Atomically persist one provider ownership layer with stale-write checks."""

    def __init__(
        self,
        data_dir: str | Path,
        ownership: ProviderOwnership,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(ownership, ProviderOwnership):
            raise ValueError("provider registry ownership is invalid")
        self.ownership = ownership
        self.root = Path(data_dir).expanduser().resolve() / "providers"
        self.path = self.root / f"{ownership.value}.json"
        self.lock_path = self.root / f".{ownership.value}.lock"
        self._now = now or (lambda: datetime.now(timezone.utc))

    def list(self) -> tuple[ProviderRegistryEntry, ...]:
        """Return the complete source layer in deterministic order."""
        with exclusive_file_lock(self.lock_path):
            entries = self._read_unlocked()
        return tuple(sorted(entries.values(), key=lambda item: item.profile.id))

    def get(self, provider_id: str) -> ProviderRegistryEntry | None:
        """Return one provider entry when it exists in this source layer."""
        _validate_identity(provider_id, field_name="provider id")
        with exclusive_file_lock(self.lock_path):
            return self._read_unlocked().get(provider_id)

    def create(
        self,
        profile: ProviderProfile,
        *,
        routes: Iterable[RouteProfile] = (),
        enabled: bool = True,
    ) -> ProviderRegistryEntry:
        """Create a provider without replacing an existing source identity."""
        self._require_ownership(profile)
        timestamp = _format_timestamp(self._now())
        entry = ProviderRegistryEntry(
            profile=profile,
            routes=tuple(routes),
            enabled=enabled,
            revision=1,
            created_at=timestamp,
            updated_at=timestamp,
        )
        with exclusive_file_lock(self.lock_path):
            entries = self._read_unlocked()
            if profile.id in entries:
                raise ProviderRegistryConflict("provider already exists")
            entries[profile.id] = entry
            self._write_unlocked(entries)
        return entry

    def replace(
        self,
        profile: ProviderProfile,
        *,
        routes: Iterable[RouteProfile],
        enabled: bool,
        expected_revision: int,
    ) -> ProviderRegistryEntry:
        """Replace one provider only when its store revision is current."""
        self._require_ownership(profile)
        with exclusive_file_lock(self.lock_path):
            entries = self._read_unlocked()
            current = _require_current(entries, profile.id, expected_revision)
            normalized_routes = tuple(routes)
            _validate_replacement_revisions(current, profile, normalized_routes)
            updated = ProviderRegistryEntry(
                profile=profile,
                routes=normalized_routes,
                enabled=enabled,
                revision=current.revision + 1,
                created_at=current.created_at,
                updated_at=_format_timestamp(self._now()),
            )
            entries[profile.id] = updated
            self._write_unlocked(entries)
        return updated

    def set_enabled(
        self,
        provider_id: str,
        enabled: bool,
        *,
        expected_revision: int,
    ) -> ProviderRegistryEntry:
        """Enable or disable one provider with optimistic concurrency."""
        if not isinstance(enabled, bool):
            raise ValueError("provider enabled must be a boolean")
        with exclusive_file_lock(self.lock_path):
            entries = self._read_unlocked()
            current = _require_current(entries, provider_id, expected_revision)
            updated = replace(
                current,
                enabled=enabled,
                revision=current.revision + 1,
                updated_at=_format_timestamp(self._now()),
            )
            entries[provider_id] = updated
            self._write_unlocked(entries)
        return updated

    def delete(self, provider_id: str, *, expected_revision: int) -> None:
        """Delete one provider only when the caller observed its latest revision."""
        with exclusive_file_lock(self.lock_path):
            entries = self._read_unlocked()
            _require_current(entries, provider_id, expected_revision)
            del entries[provider_id]
            self._write_unlocked(entries)

    def clone(
        self,
        source_id: str,
        profile: ProviderProfile,
        *,
        routes: Iterable[RouteProfile],
        expected_source_revision: int,
        enabled: bool = True,
    ) -> ProviderRegistryEntry:
        """Clone reviewed provider data into a new, caller-supplied identity."""
        self._require_ownership(profile)
        if source_id == profile.id:
            raise ValueError("cloned provider id must differ from its source")
        timestamp = _format_timestamp(self._now())
        cloned = ProviderRegistryEntry(
            profile=profile,
            routes=tuple(routes),
            enabled=enabled,
            revision=1,
            created_at=timestamp,
            updated_at=timestamp,
        )
        with exclusive_file_lock(self.lock_path):
            entries = self._read_unlocked()
            _require_current(entries, source_id, expected_source_revision)
            if profile.id in entries:
                raise ProviderRegistryConflict("cloned provider already exists")
            entries[profile.id] = cloned
            self._write_unlocked(entries)
        return cloned

    def _require_ownership(self, profile: ProviderProfile) -> None:
        if profile.ownership is not self.ownership:
            raise ProviderRegistryOwnershipError(
                "provider ownership does not match registry layer"
            )

    def _read_unlocked(self) -> dict[str, ProviderRegistryEntry]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("provider registry is unreadable") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("provider registry must be an object")
        if set(payload) != {"schema_version", "ownership", "providers"}:
            raise ValueError("provider registry fields are invalid")
        if payload.get("schema_version") != PROVIDER_REGISTRY_SCHEMA_VERSION:
            raise ValueError("unsupported provider registry schema_version")
        if payload.get("ownership") != self.ownership.value:
            raise ProviderRegistryOwnershipError("provider registry owner changed")
        raw_entries = payload.get("providers")
        if not isinstance(raw_entries, list):
            raise ValueError("provider registry providers must be a list")
        entries: dict[str, ProviderRegistryEntry] = {}
        for raw_entry in raw_entries:
            entry = _entry_from_dict(raw_entry)
            self._require_ownership(entry.profile)
            if entry.profile.id in entries:
                raise ValueError("provider registry contains duplicate ids")
            entries[entry.profile.id] = entry
        return entries

    def _write_unlocked(self, entries: Mapping[str, ProviderRegistryEntry]) -> None:
        payload = {
            "schema_version": PROVIDER_REGISTRY_SCHEMA_VERSION,
            "ownership": self.ownership.value,
            "providers": [
                _entry_to_dict(entries[provider_id]) for provider_id in sorted(entries)
            ],
        }
        _atomic_private_json(self.path, payload)


class LayeredProviderRegistry:
    """Resolve provider ids across explicit ownership layers."""

    def __init__(
        self,
        sources: Mapping[ProviderOwnership, Iterable[ProviderRegistryEntry]],
    ) -> None:
        normalized: dict[ProviderOwnership, tuple[ProviderRegistryEntry, ...]] = {}
        for ownership, entries in sources.items():
            if not isinstance(ownership, ProviderOwnership):
                raise ValueError("provider source ownership is invalid")
            values = tuple(entries)
            if any(item.profile.ownership is not ownership for item in values):
                raise ProviderRegistryOwnershipError(
                    "provider source contains a foreign ownership entry"
                )
            if len({item.profile.id for item in values}) != len(values):
                raise ValueError("provider source contains duplicate ids")
            normalized[ownership] = values
        self._sources = normalized

    def list(self) -> tuple[EffectiveProvider, ...]:
        """Return effective providers using stable source precedence."""
        candidates: dict[
            str, list[tuple[ProviderOwnership, ProviderRegistryEntry]]
        ] = {}
        for ownership in PROVIDER_SOURCE_PRECEDENCE:
            for entry in self._sources.get(ownership, ()):
                candidates.setdefault(entry.profile.id, []).append((ownership, entry))
        effective = []
        for provider_id in sorted(candidates):
            values = candidates[provider_id]
            source, entry = values[0]
            effective.append(
                EffectiveProvider(
                    entry=entry,
                    source=source,
                    shadowed_sources=tuple(item[0] for item in values[1:]),
                )
            )
        return tuple(effective)

    def get(self, provider_id: str) -> EffectiveProvider | None:
        """Return one effective provider, including a disabled upper layer."""
        _validate_identity(provider_id, field_name="provider id")
        return next(
            (item for item in self.list() if item.entry.profile.id == provider_id),
            None,
        )


class ProviderHealthStatus(str, Enum):
    """Stable connection-health state for a provider revision."""

    READY = "ready"
    UNHEALTHY = "unhealthy"
    BLOCKED = "blocked"


class ProviderFailureKind(str, Enum):
    """Independent failure axis for a provider connection check."""

    NETWORK_POLICY = "network_policy"
    AUTHENTICATION = "authentication"
    COMPATIBILITY = "compatibility"
    PROVIDER_HEALTH = "provider_health"
    TRANSPORT = "transport"


class ProviderDiscoveryStatus(str, Enum):
    """Truthful state of the latest model-discovery attempt."""

    NOT_REQUESTED = "not_requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ProviderModelSource(str, Enum):
    """Evidence source for one model visible after a check."""

    DISCOVERED = "discovered"
    CONFIGURED_FALLBACK = "configured_fallback"


@dataclass(frozen=True, order=True)
class ProviderModelEvidence:
    """One bounded model name with explicit discovery provenance."""

    model: str
    source: ProviderModelSource

    def __post_init__(self) -> None:
        _validate_model(self.model)
        if not isinstance(self.source, ProviderModelSource):
            raise ValueError("provider model source is invalid")


@dataclass(frozen=True)
class ProviderHealthSnapshot:
    """Persistable, content-free connection and discovery evidence."""

    provider: ProviderRef
    status: ProviderHealthStatus
    checked_at: str
    duration_ms: int
    discovery_status: ProviderDiscoveryStatus
    models: tuple[ProviderModelEvidence, ...] = ()
    failure_kind: ProviderFailureKind | None = None
    reason_code: str | None = None
    discovery_reason_code: str | None = None
    cached: bool = False
    schema_version: int = PROVIDER_HEALTH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PROVIDER_HEALTH_SCHEMA_VERSION:
            raise ValueError("unsupported provider health schema_version")
        if not isinstance(self.provider, ProviderRef):
            raise ValueError("provider health reference is invalid")
        if not isinstance(self.status, ProviderHealthStatus):
            raise ValueError("provider health status is invalid")
        _parse_timestamp(self.checked_at)
        if (
            isinstance(self.duration_ms, bool)
            or not isinstance(self.duration_ms, int)
            or self.duration_ms < 0
        ):
            raise ValueError("provider health duration_ms must be non-negative")
        if not isinstance(self.discovery_status, ProviderDiscoveryStatus):
            raise ValueError("provider discovery status is invalid")
        models = _normalize_models(self.models)
        object.__setattr__(self, "models", models)
        if self.failure_kind is not None and not isinstance(
            self.failure_kind, ProviderFailureKind
        ):
            raise ValueError("provider health failure kind is invalid")
        if self.status is ProviderHealthStatus.READY:
            if self.failure_kind is not None or self.reason_code is not None:
                raise ValueError("ready provider health cannot retain a failure")
        elif self.failure_kind is None or self.reason_code is None:
            raise ValueError("failed provider health requires a typed reason")
        if self.status is ProviderHealthStatus.BLOCKED and (
            self.failure_kind is not ProviderFailureKind.NETWORK_POLICY
        ):
            raise ValueError("blocked provider health requires network policy denial")
        _validate_optional_reason(self.reason_code)
        _validate_optional_reason(self.discovery_reason_code)
        if self.discovery_status is ProviderDiscoveryStatus.FAILED:
            if self.discovery_reason_code is None:
                raise ValueError("failed discovery requires a reason code")
        elif self.discovery_reason_code is not None:
            raise ValueError("successful discovery cannot retain a failure reason")
        if not isinstance(self.cached, bool):
            raise ValueError("provider health cached must be a boolean")


@dataclass(frozen=True)
class ProviderProbeRequest:
    """Runtime-only connection request containing policy references, not values."""

    profile: ProviderProfile
    timeout_seconds: float
    discover_models: bool
    proxy_policy_ref: str | None
    tls_policy_ref: str | None
    egress_policy_ref: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.profile, ProviderProfile):
            raise ValueError("provider probe profile is invalid")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not 0 < self.timeout_seconds <= MAX_PROVIDER_CHECK_TIMEOUT_SECONDS
        ):
            raise ValueError("provider probe timeout is outside the bounded range")
        if not isinstance(self.discover_models, bool):
            raise ValueError("provider probe discovery flag must be a boolean")
        expected = (
            self.profile.proxy_policy_ref,
            self.profile.tls_policy_ref,
            self.profile.egress_policy_ref,
        )
        if (
            self.proxy_policy_ref,
            self.tls_policy_ref,
            self.egress_policy_ref,
        ) != expected:
            raise ValueError("provider probe policy references changed")


@dataclass(frozen=True)
class ProviderProbeResponse:
    """Successful backend connection result with optional model discovery."""

    models: tuple[str, ...] = ()
    discovery_succeeded: bool = True
    discovery_reason_code: str | None = None

    def __post_init__(self) -> None:
        models = _normalize_discovered_model_names(self.models)
        object.__setattr__(self, "models", models)
        if not isinstance(self.discovery_succeeded, bool):
            raise ValueError("provider discovery success must be a boolean")
        _validate_optional_reason(self.discovery_reason_code)
        if self.discovery_succeeded and self.discovery_reason_code is not None:
            raise ValueError("successful discovery cannot retain a failure reason")
        if not self.discovery_succeeded and self.discovery_reason_code is None:
            raise ValueError("failed discovery requires a reason code")


@dataclass(frozen=True)
class ProviderNetworkPolicyDecision:
    """Content-free admission result evaluated before provider traffic."""

    allowed: bool
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.allowed, bool):
            raise ValueError("network policy allowed must be a boolean")
        _validate_optional_reason(self.reason_code)
        if self.allowed == (self.reason_code is not None):
            raise ValueError("network policy decision reason is inconsistent")


class ProviderProbeBackend(Protocol):
    """Injected owner of provider-specific connection and discovery I/O."""

    def check(self, request: ProviderProbeRequest) -> ProviderProbeResponse:
        """Run one bounded provider connection check."""


class ProviderProbeFailure(RuntimeError):
    """Base provider check failure carrying only a stable reason code."""

    kind: ProviderFailureKind

    def __init__(self, reason_code: str) -> None:
        _validate_reason(reason_code)
        super().__init__(reason_code)
        self.reason_code = reason_code


class ProviderAuthenticationFailure(ProviderProbeFailure):
    """Provider rejected or could not resolve authentication."""

    kind = ProviderFailureKind.AUTHENTICATION


class ProviderCompatibilityFailure(ProviderProbeFailure):
    """Provider protocol or dialect is incompatible with the check backend."""

    kind = ProviderFailureKind.COMPATIBILITY


class ProviderHealthFailure(ProviderProbeFailure):
    """Provider responded with an unhealthy service state."""

    kind = ProviderFailureKind.PROVIDER_HEALTH


class ProviderTransportFailure(ProviderProbeFailure):
    """Bounded connection transport failed before a provider response."""

    kind = ProviderFailureKind.TRANSPORT


class ProviderHealthStore:
    """Persist the latest bounded health snapshot per provider identity."""

    def __init__(self, data_dir: str | Path) -> None:
        self.root = Path(data_dir).expanduser().resolve() / "providers" / "health"

    def load(self, provider_id: str) -> ProviderHealthSnapshot | None:
        """Load the latest strict health snapshot for one provider."""
        _validate_identity(provider_id, field_name="provider id")
        path = self._path(provider_id)
        with exclusive_file_lock(self._lock_path(provider_id)):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return None
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("provider health snapshot is unreadable") from exc
        snapshot = _health_from_dict(payload)
        if snapshot.provider.id != provider_id:
            raise ValueError("provider health identity mismatch")
        return snapshot

    def save(self, snapshot: ProviderHealthSnapshot) -> ProviderHealthSnapshot:
        """Atomically replace one provider's latest health evidence."""
        persisted = replace(snapshot, cached=False)
        with exclusive_file_lock(self._lock_path(snapshot.provider.id)):
            _atomic_private_json(
                self._path(snapshot.provider.id),
                _health_to_dict(persisted),
            )
        return persisted

    def _path(self, provider_id: str) -> Path:
        return self.root / f"{_hashed_key(provider_id)}.json"

    def _lock_path(self, provider_id: str) -> Path:
        return self.root / f".{_hashed_key(provider_id)}.lock"


class ProviderHealthService:
    """Apply network policy before bounded, provider-specific health I/O."""

    def __init__(
        self,
        backend: ProviderProbeBackend,
        store: ProviderHealthStore,
        *,
        network_policy: Callable[[ProviderProbeRequest], ProviderNetworkPolicyDecision]
        | None = None,
        now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self.backend = backend
        self.store = store
        self.network_policy = network_policy or _default_network_policy
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic or time.monotonic

    def check(
        self,
        entry: ProviderRegistryEntry,
        *,
        discover_models: bool = True,
        timeout_seconds: float = 10.0,
        force: bool = False,
    ) -> ProviderHealthSnapshot:
        """Check one enabled provider or reuse its revision-bound TTL cache."""
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < timeout_seconds <= MAX_PROVIDER_CHECK_TIMEOUT_SECONDS
        ):
            raise ValueError("provider check timeout is outside the bounded range")
        if not isinstance(discover_models, bool) or not isinstance(force, bool):
            raise ValueError("provider check flags must be booleans")
        profile = entry.profile
        request = ProviderProbeRequest(
            profile=profile,
            timeout_seconds=float(timeout_seconds),
            discover_models=discover_models,
            proxy_policy_ref=profile.proxy_policy_ref,
            tls_policy_ref=profile.tls_policy_ref,
            egress_policy_ref=profile.egress_policy_ref,
        )
        started = self._monotonic()
        if not entry.enabled:
            return self._save_failure(
                profile,
                started=started,
                kind=ProviderFailureKind.NETWORK_POLICY,
                reason_code="provider_disabled",
                discover_models=discover_models,
            )
        if profile.offline:
            return self._save_failure(
                profile,
                started=started,
                kind=ProviderFailureKind.NETWORK_POLICY,
                reason_code="offline_mode",
                discover_models=discover_models,
            )
        decision = self.network_policy(request)
        if not isinstance(decision, ProviderNetworkPolicyDecision):
            raise TypeError("network policy must return ProviderNetworkPolicyDecision")
        if not decision.allowed:
            return self._save_failure(
                profile,
                started=started,
                kind=ProviderFailureKind.NETWORK_POLICY,
                reason_code=decision.reason_code or "network_policy_denied",
                discover_models=discover_models,
            )
        cached = self.store.load(profile.id)
        if not force and self._cache_is_current(
            profile,
            cached,
            discover_models=discover_models,
        ):
            return replace(cached, cached=True)
        try:
            response = self.backend.check(request)
            if not isinstance(response, ProviderProbeResponse):
                raise TypeError("provider backend must return ProviderProbeResponse")
        except ProviderProbeFailure as exc:
            return self._save_failure(
                profile,
                started=started,
                kind=exc.kind,
                reason_code=exc.reason_code,
                discover_models=discover_models,
            )
        discovery_status = ProviderDiscoveryStatus.NOT_REQUESTED
        discovery_reason = None
        discovered: tuple[str, ...] = ()
        if discover_models:
            if response.discovery_succeeded:
                discovery_status = ProviderDiscoveryStatus.SUCCEEDED
                discovered = response.models
            else:
                discovery_status = ProviderDiscoveryStatus.FAILED
                discovery_reason = response.discovery_reason_code
        models = _merge_model_evidence(profile, discovered)
        snapshot = ProviderHealthSnapshot(
            provider=profile.ref,
            status=ProviderHealthStatus.READY,
            checked_at=_format_timestamp(self._now()),
            duration_ms=_duration_ms(started, self._monotonic()),
            discovery_status=discovery_status,
            discovery_reason_code=discovery_reason,
            models=models,
        )
        return self.store.save(snapshot)

    def _save_failure(
        self,
        profile: ProviderProfile,
        *,
        started: float,
        kind: ProviderFailureKind,
        reason_code: str,
        discover_models: bool,
    ) -> ProviderHealthSnapshot:
        discovery_status = (
            ProviderDiscoveryStatus.FAILED
            if discover_models
            else ProviderDiscoveryStatus.NOT_REQUESTED
        )
        snapshot = ProviderHealthSnapshot(
            provider=profile.ref,
            status=(
                ProviderHealthStatus.BLOCKED
                if kind is ProviderFailureKind.NETWORK_POLICY
                else ProviderHealthStatus.UNHEALTHY
            ),
            checked_at=_format_timestamp(self._now()),
            duration_ms=_duration_ms(started, self._monotonic()),
            discovery_status=discovery_status,
            models=_merge_model_evidence(profile, ()),
            failure_kind=kind,
            reason_code=reason_code,
            discovery_reason_code=(reason_code if discover_models else None),
        )
        return self.store.save(snapshot)

    def _cache_is_current(
        self,
        profile: ProviderProfile,
        snapshot: ProviderHealthSnapshot | None,
        *,
        discover_models: bool,
    ) -> bool:
        if snapshot is None or snapshot.provider != profile.ref:
            return False
        if (
            discover_models
            and snapshot.discovery_status is ProviderDiscoveryStatus.NOT_REQUESTED
        ):
            return False
        ttl = profile.discovery_cache_ttl_seconds
        if ttl <= 0:
            return False
        age = (self._now() - _parse_timestamp(snapshot.checked_at)).total_seconds()
        return 0 <= age <= ttl


def _default_network_policy(
    request: ProviderProbeRequest,
) -> ProviderNetworkPolicyDecision:
    if request.profile.offline:
        return ProviderNetworkPolicyDecision(False, "offline_mode")
    if request.egress_policy_ref is not None:
        return ProviderNetworkPolicyDecision(False, "egress_policy_unresolved")
    return ProviderNetworkPolicyDecision(True)


def _entry_to_dict(entry: ProviderRegistryEntry) -> dict[str, Any]:
    return {
        "profile": provider_profile_to_dict(entry.profile),
        "routes": [route_profile_to_dict(item) for item in entry.routes],
        "enabled": entry.enabled,
        "revision": entry.revision,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
    }


def _entry_from_dict(data: Any) -> ProviderRegistryEntry:
    if not isinstance(data, Mapping):
        raise ValueError("provider registry entry must be an object")
    allowed = {
        "profile",
        "routes",
        "enabled",
        "revision",
        "created_at",
        "updated_at",
    }
    if set(data) != allowed:
        raise ValueError("provider registry entry fields are invalid")
    raw_routes = data.get("routes")
    if not isinstance(raw_routes, list):
        raise ValueError("provider registry routes must be a list")
    enabled = data.get("enabled")
    revision = data.get("revision")
    if not isinstance(enabled, bool):
        raise ValueError("provider registry enabled must be a boolean")
    if isinstance(revision, bool) or not isinstance(revision, int):
        raise ValueError("provider registry revision must be an integer")
    return ProviderRegistryEntry(
        profile=provider_profile_from_dict(_mapping(data.get("profile"))),
        routes=tuple(route_profile_from_dict(_mapping(item)) for item in raw_routes),
        enabled=enabled,
        revision=revision,
        created_at=_required_text(data.get("created_at"), "created_at"),
        updated_at=_required_text(data.get("updated_at"), "updated_at"),
    )


def _health_to_dict(snapshot: ProviderHealthSnapshot) -> dict[str, Any]:
    return {
        "schema_version": snapshot.schema_version,
        "provider": {
            "id": snapshot.provider.id,
            "revision": snapshot.provider.revision,
        },
        "status": snapshot.status.value,
        "checked_at": snapshot.checked_at,
        "duration_ms": snapshot.duration_ms,
        "discovery_status": snapshot.discovery_status.value,
        "models": [
            {"model": item.model, "source": item.source.value}
            for item in snapshot.models
        ],
        "failure_kind": (
            snapshot.failure_kind.value if snapshot.failure_kind is not None else None
        ),
        "reason_code": snapshot.reason_code,
        "discovery_reason_code": snapshot.discovery_reason_code,
    }


def _health_from_dict(data: Any) -> ProviderHealthSnapshot:
    if not isinstance(data, Mapping):
        raise ValueError("provider health snapshot must be an object")
    allowed = {
        "schema_version",
        "provider",
        "status",
        "checked_at",
        "duration_ms",
        "discovery_status",
        "models",
        "failure_kind",
        "reason_code",
        "discovery_reason_code",
    }
    if set(data) != allowed:
        raise ValueError("provider health snapshot fields are invalid")
    raw_provider = _mapping(data.get("provider"))
    if set(raw_provider) != {"id", "revision"}:
        raise ValueError("provider health reference fields are invalid")
    raw_models = data.get("models")
    if not isinstance(raw_models, list):
        raise ValueError("provider health models must be a list")
    models = []
    for raw_model in raw_models:
        model = _mapping(raw_model)
        if set(model) != {"model", "source"}:
            raise ValueError("provider health model fields are invalid")
        models.append(
            ProviderModelEvidence(
                _required_text(model.get("model"), "model"),
                ProviderModelSource(_required_text(model.get("source"), "source")),
            )
        )
    raw_failure = data.get("failure_kind")
    return ProviderHealthSnapshot(
        provider=ProviderRef(
            _required_text(raw_provider.get("id"), "provider id"),
            _required_text(raw_provider.get("revision"), "provider revision"),
        ),
        status=ProviderHealthStatus(_required_text(data.get("status"), "status")),
        checked_at=_required_text(data.get("checked_at"), "checked_at"),
        duration_ms=_required_int(data.get("duration_ms"), "duration_ms"),
        discovery_status=ProviderDiscoveryStatus(
            _required_text(data.get("discovery_status"), "discovery_status")
        ),
        models=tuple(models),
        failure_kind=(
            ProviderFailureKind(raw_failure) if isinstance(raw_failure, str) else None
        ),
        reason_code=_optional_text(data.get("reason_code")),
        discovery_reason_code=_optional_text(data.get("discovery_reason_code")),
        schema_version=_required_int(data.get("schema_version"), "schema_version"),
    )


def _validate_route_binding(profile: ProviderProfile, route: RouteProfile) -> None:
    if not isinstance(route, RouteProfile):
        raise ValueError("provider registry route is invalid")
    if route.provider != profile.ref:
        raise ValueError("provider registry route has a stale provider reference")
    if route.protocol is not profile.protocol or route.dialect != profile.dialect:
        raise ValueError("provider registry route protocol does not match provider")
    if route.effective_base_url != profile.effective_base_url:
        raise ValueError("provider registry route endpoint does not match provider")
    if route.authentication_ownership is not profile.authentication.ownership:
        raise ValueError(
            "provider registry route authentication does not match provider"
        )


def _require_current(
    entries: Mapping[str, ProviderRegistryEntry],
    provider_id: str,
    expected_revision: int,
) -> ProviderRegistryEntry:
    _validate_identity(provider_id, field_name="provider id")
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
        raise ValueError("expected provider revision must be an integer")
    current = entries.get(provider_id)
    if current is None:
        raise ProviderRegistryConflict("provider does not exist")
    if current.revision != expected_revision:
        raise ProviderRegistryConflict("provider registry revision changed")
    return current


def _validate_replacement_revisions(
    current: ProviderRegistryEntry,
    profile: ProviderProfile,
    routes: tuple[RouteProfile, ...],
) -> None:
    current_profile = provider_profile_to_dict(current.profile)
    incoming_profile = provider_profile_to_dict(profile)
    current_profile.pop("revision")
    incoming_profile.pop("revision")
    if (
        current_profile != incoming_profile
        and current.profile.revision == profile.revision
    ):
        raise ProviderRegistryConflict(
            "changed provider content requires a new profile revision"
        )
    current_routes = {item.id: item for item in current.routes}
    for route in routes:
        prior = current_routes.get(route.id)
        if prior is None:
            continue
        prior_payload = route_profile_to_dict(prior)
        incoming_payload = route_profile_to_dict(route)
        prior_payload.pop("revision")
        incoming_payload.pop("revision")
        if prior_payload != incoming_payload and prior.revision == route.revision:
            raise ProviderRegistryConflict(
                "changed route content requires a new route revision"
            )


def _merge_model_evidence(
    profile: ProviderProfile,
    discovered: Iterable[str],
) -> tuple[ProviderModelEvidence, ...]:
    discovered_names = _normalize_discovered_model_names(discovered)
    result = [
        ProviderModelEvidence(item, ProviderModelSource.DISCOVERED)
        for item in discovered_names
    ]
    seen = set(discovered_names)
    for default in profile.default_models:
        if default.model not in seen:
            result.append(
                ProviderModelEvidence(
                    default.model,
                    ProviderModelSource.CONFIGURED_FALLBACK,
                )
            )
            seen.add(default.model)
    return _normalize_models(result)


def _normalize_models(
    models: Iterable[ProviderModelEvidence],
) -> tuple[ProviderModelEvidence, ...]:
    values = tuple(models)
    if len(values) > MAX_PROVIDER_MODELS:
        raise ValueError("provider model evidence exceeds the bounded limit")
    if any(not isinstance(item, ProviderModelEvidence) for item in values):
        raise ValueError("provider model evidence is invalid")
    if len({item.model for item in values}) != len(values):
        raise ValueError("provider model evidence contains duplicate names")
    return tuple(sorted(values, key=lambda item: (item.model, item.source.value)))


def _normalize_discovered_model_names(models: Iterable[str]) -> tuple[str, ...]:
    values = tuple(models)
    if len(values) > MAX_PROVIDER_MODELS:
        raise ValueError("provider discovery exceeds the bounded model limit")
    normalized = []
    seen = set()
    for item in values:
        _validate_model(item)
        if item not in seen:
            normalized.append(item)
            seen.add(item)
    return tuple(sorted(normalized))


def _validate_model(model: str) -> None:
    if not isinstance(model, str) or not model.strip():
        raise ValueError("provider model must be non-empty")
    if len(model) > MAX_PROVIDER_MODEL_CHARS or any(ord(char) < 32 for char in model):
        raise ValueError("provider model is invalid")


def _validate_identity(value: str, *, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 256
        or any(not (char.isalnum() or char in "._:/@+~-") for char in value)
    ):
        raise ValueError(f"{field_name} is invalid")


def _validate_reason(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_PROVIDER_REASON_CHARS
        or any(not (char.isalnum() or char in "._:-") for char in value)
    ):
        raise ValueError("provider reason code is invalid")


def _validate_optional_reason(value: str | None) -> None:
    if value is not None:
        _validate_reason(value)


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("provider persisted value must be an object")
    return value


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"provider {field_name} must be non-empty")
    return value


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("provider persisted text is invalid")
    return value


def _required_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"provider {field_name} must be an integer")
    return value


def _format_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("provider timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("provider timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("provider timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _duration_ms(started: float, finished: float) -> int:
    return max(0, int((finished - started) * 1000))


def _hashed_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _atomic_private_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw_path)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)
