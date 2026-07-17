"""Backend-owned secret references and explicit resolution boundaries."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
import re
import time
from typing import Any, Mapping, Protocol, runtime_checkable


SECRET_REFERENCE_SCHEMA_VERSION = 1
MAX_SECRET_CACHE_TTL_SECONDS = 300
_REDACTED = "<redacted>"
_ENVIRONMENT_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,255}\Z")
_SAFE_BACKEND_ID_RE = re.compile(r"[^a-z0-9._-]+")


class SecretReferenceKind(str, Enum):
    """Supported secret source classes."""

    ENVIRONMENT = "environment"
    KEYCHAIN = "keychain"
    TEST = "test"


class SecretResolutionErrorCode(str, Enum):
    """Stable failure reason safe to expose through diagnostics."""

    UNAVAILABLE = "unavailable"
    MISSING = "missing"
    DENIED = "denied"
    EXPIRED = "expired"


class SecretResolutionState(str, Enum):
    """Content-free lifecycle state for one resolution attempt."""

    AVAILABLE = "available"
    RESOLVED = "resolved"
    UNAVAILABLE = "unavailable"
    MISSING = "missing"
    DENIED = "denied"
    EXPIRED = "expired"


@dataclass(frozen=True)
class SecretReference:
    """Versioned, persistable pointer to a secret, never its value."""

    kind: SecretReferenceKind
    name: str
    service: str | None = None
    account: str | None = None
    expires_at: str | None = None
    cache_ttl_seconds: int = 0
    schema_version: int = SECRET_REFERENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SecretReferenceKind):
            raise ValueError("secret reference kind is invalid")
        if self.schema_version != SECRET_REFERENCE_SCHEMA_VERSION:
            raise ValueError("unsupported secret reference schema_version")
        _validate_reference_text(self.name, field="name")
        if self.kind in {SecretReferenceKind.ENVIRONMENT, SecretReferenceKind.TEST}:
            if not _ENVIRONMENT_NAME_RE.fullmatch(self.name):
                raise ValueError(
                    f"{self.kind.value} reference name must be an environment-style name"
                )
            if self.service is not None or self.account is not None:
                raise ValueError(
                    f"{self.kind.value} references do not accept service/account"
                )
        if self.kind is SecretReferenceKind.KEYCHAIN:
            if not self.service:
                raise ValueError("keychain references require service")
            _validate_reference_text(self.service, field="service")
            if self.account is not None:
                _validate_reference_text(self.account, field="account")
        if self.expires_at is not None:
            _parse_timestamp(self.expires_at)
        if isinstance(self.cache_ttl_seconds, bool) or not isinstance(
            self.cache_ttl_seconds, int
        ):
            raise ValueError("cache_ttl_seconds must be an integer")
        if not 0 <= self.cache_ttl_seconds <= MAX_SECRET_CACHE_TTL_SECONDS:
            raise ValueError(
                "cache_ttl_seconds must be between 0 and "
                f"{MAX_SECRET_CACHE_TTL_SECONDS}"
            )

    @property
    def expired(self) -> bool:
        """Return whether the reference expiry is in the past."""
        if self.expires_at is None:
            return False
        return _parse_timestamp(self.expires_at) <= datetime.now(timezone.utc)

    @property
    def identity(self) -> str:
        """Return a content-free stable identity for cache and evidence keys."""
        encoded = json.dumps(
            secret_reference_to_dict(self),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class SecretSourceProvenance:
    """Safe source evidence without source values or operating-system paths."""

    backend_id: str
    kind: SecretReferenceKind
    revision: str | None = None

    def __post_init__(self) -> None:
        backend_id = _safe_backend_id(self.backend_id)
        if not backend_id:
            raise ValueError("secret backend_id must not be empty")
        object.__setattr__(self, "backend_id", backend_id)
        if self.revision is not None:
            _validate_reference_text(self.revision, field="revision", max_length=128)


@dataclass(frozen=True)
class SecretResolutionEvidence:
    """Bounded lifecycle evidence safe for logs, APIs, stores, and traces."""

    reference_id: str
    kind: SecretReferenceKind
    state: SecretResolutionState
    checked_at: str
    backend_id: str | None = None
    source_revision: str | None = None
    cache_hit: bool = False
    cache_expires_at: str | None = None
    reference_expires_at: str | None = None

    @property
    def provenance(self) -> SecretSourceProvenance | None:
        """Return structured source provenance when a backend was selected."""
        if self.backend_id is None:
            return None
        return SecretSourceProvenance(
            backend_id=self.backend_id,
            kind=self.kind,
            revision=self.source_revision,
        )

    def __gpt2giga_redacted__(self) -> dict[str, Any]:
        """Return the safe public evidence projection."""
        return secret_resolution_evidence_to_dict(self)


class SecretResolutionError(RuntimeError):
    """Report a reference failure without including a resolved value."""

    def __init__(
        self,
        code: SecretResolutionErrorCode,
        reference: SecretReference,
        message: str | None = None,
        *,
        evidence: SecretResolutionEvidence | None = None,
    ) -> None:
        super().__init__(message or _safe_error_message(code))
        self.code = code
        self.reference = reference
        self.evidence = evidence

    def __gpt2giga_redacted__(self) -> dict[str, Any]:
        """Return a stable content-free error projection."""
        return {
            "code": self.code.value,
            "message": _safe_error_message(self.code),
            "evidence": (
                secret_resolution_evidence_to_dict(self.evidence)
                if self.evidence is not None
                else None
            ),
        }


class ResolvedSecret:
    """Opaque resolved value requiring an exact owning boundary to reveal."""

    __slots__ = ("_evidence", "_owner", "_reference", "_value")

    def __init__(
        self,
        reference: SecretReference,
        value: str,
        *,
        owner: str,
        evidence: SecretResolutionEvidence | None = None,
    ) -> None:
        if not value:
            raise ValueError("resolved secret must not be empty")
        _validate_owner(owner)
        self._reference = reference
        self._value = value
        self._owner = owner
        self._evidence = evidence or _resolution_evidence(
            reference,
            state=SecretResolutionState.RESOLVED,
            backend_id="custom",
        )

    @property
    def reference(self) -> SecretReference:
        """Return the safe source reference."""
        return self._reference

    @property
    def evidence(self) -> SecretResolutionEvidence:
        """Return content-free resolution provenance."""
        return self._evidence

    def reveal_for(self, owner: str) -> str:
        """Reveal only when the exact owning execution boundary is named."""
        if owner != self._owner:
            raise ValueError("secret reveal boundary does not match its owner")
        return self._value

    def __gpt2giga_redacted__(self) -> str:
        """Return the stable value used by shared persistence redaction."""
        return _REDACTED

    def __repr__(self) -> str:
        return (
            "ResolvedSecret("
            f"reference_id={self._reference.identity!r}, value={_REDACTED!r})"
        )

    def __str__(self) -> str:
        return _REDACTED

    def _with_evidence(self, evidence: SecretResolutionEvidence) -> ResolvedSecret:
        return ResolvedSecret(
            self._reference,
            self._value,
            owner=self._owner,
            evidence=evidence,
        )


@runtime_checkable
class SecretResolver(Protocol):
    """Resolve supported references at the final owning execution boundary."""

    def supports(self, kind: SecretReferenceKind) -> bool:
        raise NotImplementedError

    def resolve(self, reference: SecretReference, *, owner: str) -> ResolvedSecret:
        raise NotImplementedError


@runtime_checkable
class KeychainSecretReader(Protocol):
    """Optional injected OS-keychain adapter; never installed implicitly."""

    def read(self, reference: SecretReference) -> str | None:
        raise NotImplementedError


class EnvironmentSecretResolver:
    """Resolve allowlisted environment variables without copying the environment."""

    backend_id = "environment"

    def __init__(
        self,
        environment: Mapping[str, str] | None = None,
        *,
        allowed_names: frozenset[str] | None = None,
    ) -> None:
        self._environment = os.environ if environment is None else environment
        self._allowed_names = allowed_names

    def supports(self, kind: SecretReferenceKind) -> bool:
        return kind is SecretReferenceKind.ENVIRONMENT

    def resolve(self, reference: SecretReference, *, owner: str) -> ResolvedSecret:
        _validate_resolution_request(reference, owner=owner)
        if not self.supports(reference.kind):
            raise _resolution_error(
                SecretResolutionErrorCode.UNAVAILABLE,
                reference,
                backend_id=self.backend_id,
                message=(
                    f"no installed resolver for {reference.kind.value} references"
                ),
            )
        if (
            self._allowed_names is not None
            and reference.name not in self._allowed_names
        ):
            raise _resolution_error(
                SecretResolutionErrorCode.DENIED,
                reference,
                backend_id=self.backend_id,
                message=f"environment reference is not allowed: {reference.name}",
            )
        value = self._environment.get(reference.name)
        if not value:
            raise _resolution_error(
                SecretResolutionErrorCode.MISSING,
                reference,
                backend_id=self.backend_id,
                message=f"environment reference is missing: {reference.name}",
            )
        evidence = _resolution_evidence(
            reference,
            state=SecretResolutionState.RESOLVED,
            backend_id=self.backend_id,
        )
        return ResolvedSecret(reference, value, owner=owner, evidence=evidence)


class MemorySecretResolver:
    """Hermetic test-only backend isolated from environment and persisted settings."""

    backend_id = "test-memory"

    def __init__(self, values: Mapping[str, str] | None = None) -> None:
        self._values = dict(values or {})
        self._revision = 0

    def supports(self, kind: SecretReferenceKind) -> bool:
        return kind is SecretReferenceKind.TEST

    def set(self, name: str, value: str) -> None:
        """Rotate one test value without exposing it through evidence."""
        if not _ENVIRONMENT_NAME_RE.fullmatch(name):
            raise ValueError("test secret name must be an environment-style name")
        if not value:
            raise ValueError("test secret value must not be empty")
        self._values[name] = value
        self._revision += 1

    def delete(self, name: str) -> None:
        """Remove one test value and advance its safe source revision."""
        self._values.pop(name, None)
        self._revision += 1

    def resolve(self, reference: SecretReference, *, owner: str) -> ResolvedSecret:
        _validate_resolution_request(reference, owner=owner)
        if not self.supports(reference.kind):
            raise _resolution_error(
                SecretResolutionErrorCode.UNAVAILABLE,
                reference,
                backend_id=self.backend_id,
            )
        value = self._values.get(reference.name)
        if not value:
            raise _resolution_error(
                SecretResolutionErrorCode.MISSING,
                reference,
                backend_id=self.backend_id,
                source_revision=str(self._revision),
            )
        evidence = _resolution_evidence(
            reference,
            state=SecretResolutionState.RESOLVED,
            backend_id=self.backend_id,
            source_revision=str(self._revision),
        )
        return ResolvedSecret(reference, value, owner=owner, evidence=evidence)


class KeychainSecretResolver:
    """Resolve keychain references only through an explicitly injected reader."""

    backend_id = "keychain"

    def __init__(self, reader: KeychainSecretReader | None = None) -> None:
        self._reader = reader

    def supports(self, kind: SecretReferenceKind) -> bool:
        return kind is SecretReferenceKind.KEYCHAIN and self._reader is not None

    def resolve(self, reference: SecretReference, *, owner: str) -> ResolvedSecret:
        _validate_resolution_request(reference, owner=owner)
        if not self.supports(reference.kind):
            raise _resolution_error(
                SecretResolutionErrorCode.UNAVAILABLE,
                reference,
                backend_id=self.backend_id,
            )
        assert self._reader is not None
        try:
            value = self._reader.read(reference)
        except PermissionError:
            raise _resolution_error(
                SecretResolutionErrorCode.DENIED,
                reference,
                backend_id=self.backend_id,
            ) from None
        except OSError:
            raise _resolution_error(
                SecretResolutionErrorCode.UNAVAILABLE,
                reference,
                backend_id=self.backend_id,
            ) from None
        if not value:
            raise _resolution_error(
                SecretResolutionErrorCode.MISSING,
                reference,
                backend_id=self.backend_id,
            )
        evidence = _resolution_evidence(
            reference,
            state=SecretResolutionState.RESOLVED,
            backend_id=self.backend_id,
        )
        return ResolvedSecret(reference, value, owner=owner, evidence=evidence)


class CompositeSecretResolver:
    """Route references only to explicitly installed concrete resolvers."""

    def __init__(self, resolvers: tuple[SecretResolver, ...] = ()) -> None:
        self._resolvers = resolvers

    def supports(self, kind: SecretReferenceKind) -> bool:
        return any(resolver.supports(kind) for resolver in self._resolvers)

    def resolve(self, reference: SecretReference, *, owner: str) -> ResolvedSecret:
        _validate_resolution_request(reference, owner=owner)
        for resolver in self._resolvers:
            if resolver.supports(reference.kind):
                return resolver.resolve(reference, owner=owner)
        raise _resolution_error(
            SecretResolutionErrorCode.UNAVAILABLE,
            reference,
            backend_id=None,
            message=f"no installed resolver for {reference.kind.value} references",
        )


@dataclass(frozen=True)
class _CacheEntry:
    secret: ResolvedSecret
    expires_at: float


class SecretResolutionService:
    """Resolve, cache, inspect, and rotate references without persisting values."""

    def __init__(
        self,
        resolver: SecretResolver,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._resolver = resolver
        self._monotonic = monotonic
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._cache: dict[tuple[str, str], _CacheEntry] = {}

    def supports(self, kind: SecretReferenceKind) -> bool:
        return self._resolver.supports(kind)

    def inspect(self, reference: SecretReference) -> SecretResolutionEvidence:
        """Inspect availability without reading a secret value."""
        if reference.expired:
            state = SecretResolutionState.EXPIRED
        elif self.supports(reference.kind):
            state = SecretResolutionState.AVAILABLE
        else:
            state = SecretResolutionState.UNAVAILABLE
        return _resolution_evidence(
            reference,
            state=state,
            backend_id=None,
            now=self._now(),
        )

    def resolve(self, reference: SecretReference, *, owner: str) -> ResolvedSecret:
        _validate_resolution_request(reference, owner=owner)
        key = (reference.identity, owner)
        cached = self._cache.get(key)
        monotonic_now = self._monotonic()
        if cached is not None and cached.expires_at > monotonic_now:
            evidence = replace(
                cached.secret.evidence,
                checked_at=_format_timestamp(self._now()),
                cache_hit=True,
            )
            return cached.secret._with_evidence(evidence)
        self._cache.pop(key, None)
        try:
            resolved = self._resolver.resolve(reference, owner=owner)
        except SecretResolutionError as exc:
            backend_id = exc.evidence.backend_id if exc.evidence is not None else None
            source_revision = (
                exc.evidence.source_revision if exc.evidence is not None else None
            )
            raise _resolution_error(
                exc.code,
                reference,
                backend_id=backend_id,
                source_revision=source_revision,
                now=self._now(),
            ) from None
        ttl = reference.cache_ttl_seconds
        if ttl:
            cache_expires = self._now().timestamp() + ttl
            evidence = replace(
                resolved.evidence,
                checked_at=_format_timestamp(self._now()),
                cache_expires_at=_format_timestamp(
                    datetime.fromtimestamp(cache_expires, timezone.utc)
                ),
            )
            resolved = resolved._with_evidence(evidence)
            self._cache[key] = _CacheEntry(
                secret=resolved,
                expires_at=monotonic_now + ttl,
            )
        return resolved

    def invalidate(
        self,
        reference: SecretReference | None = None,
        *,
        owner: str | None = None,
    ) -> int:
        """Invalidate cached values for explicit rotation or ownership teardown."""
        if owner is not None:
            _validate_owner(owner)
        reference_id = reference.identity if reference is not None else None
        selected = [
            key
            for key in self._cache
            if (reference_id is None or key[0] == reference_id)
            and (owner is None or key[1] == owner)
        ]
        for key in selected:
            self._cache.pop(key, None)
        return len(selected)

    def rotate(
        self,
        reference: SecretReference,
        *,
        owner: str | None = None,
    ) -> int:
        """Mark a reference rotated by invalidating every selected cached value."""
        return self.invalidate(reference, owner=owner)


def secret_reference_to_dict(reference: SecretReference) -> dict[str, Any]:
    """Serialize a reference without resolving it or exposing a value."""
    return {
        "schema_version": reference.schema_version,
        "kind": reference.kind.value,
        "name": reference.name,
        "service": reference.service,
        "account": reference.account,
        "expires_at": reference.expires_at,
        "cache_ttl_seconds": reference.cache_ttl_seconds,
    }


def secret_reference_from_dict(value: Mapping[str, Any]) -> SecretReference:
    """Parse versioned or legacy reference metadata and reject unknown fields."""
    reference_data = value.get("secret_ref", value)
    if not isinstance(reference_data, Mapping):
        raise ValueError("secret_ref must be an object")
    allowed = {
        "schema_version",
        "kind",
        "name",
        "service",
        "account",
        "expires_at",
        "cache_ttl_seconds",
    }
    unknown = sorted(str(key) for key in set(reference_data) - allowed)
    if unknown:
        raise ValueError(f"unknown secret reference fields: {', '.join(unknown)}")
    schema_version = reference_data.get(
        "schema_version", SECRET_REFERENCE_SCHEMA_VERSION
    )
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise ValueError("secret reference schema_version must be an integer")
    kind = reference_data.get("kind", SecretReferenceKind.ENVIRONMENT.value)
    name = reference_data.get("name")
    if not isinstance(kind, str) or not isinstance(name, str):
        raise ValueError("secret reference kind and name must be text")
    cache_ttl = reference_data.get("cache_ttl_seconds", 0)
    if isinstance(cache_ttl, bool) or not isinstance(cache_ttl, int):
        raise ValueError("cache_ttl_seconds must be an integer")
    return SecretReference(
        kind=SecretReferenceKind(kind),
        name=name,
        service=_optional_text_field(reference_data, "service"),
        account=_optional_text_field(reference_data, "account"),
        expires_at=_optional_text_field(reference_data, "expires_at"),
        cache_ttl_seconds=cache_ttl,
        schema_version=schema_version,
    )


def secret_resolution_evidence_to_dict(
    evidence: SecretResolutionEvidence,
) -> dict[str, Any]:
    """Serialize content-free lifecycle evidence."""
    return {
        "reference_id": evidence.reference_id,
        "kind": evidence.kind.value,
        "state": evidence.state.value,
        "checked_at": evidence.checked_at,
        "backend_id": evidence.backend_id,
        "source_revision": evidence.source_revision,
        "cache_hit": evidence.cache_hit,
        "cache_expires_at": evidence.cache_expires_at,
        "reference_expires_at": evidence.reference_expires_at,
    }


def _validate_resolution_request(reference: SecretReference, *, owner: str) -> None:
    _validate_owner(owner)
    if reference.expired:
        raise _resolution_error(
            SecretResolutionErrorCode.EXPIRED,
            reference,
            backend_id=None,
            message=f"secret reference has expired: {reference.name}",
        )


def _resolution_error(
    code: SecretResolutionErrorCode,
    reference: SecretReference,
    *,
    backend_id: str | None,
    source_revision: str | None = None,
    now: datetime | None = None,
    message: str | None = None,
) -> SecretResolutionError:
    state = SecretResolutionState(code.value)
    evidence = _resolution_evidence(
        reference,
        state=state,
        backend_id=backend_id,
        source_revision=source_revision,
        now=now,
    )
    return SecretResolutionError(code, reference, message, evidence=evidence)


def _resolution_evidence(
    reference: SecretReference,
    *,
    state: SecretResolutionState,
    backend_id: str | None,
    source_revision: str | None = None,
    now: datetime | None = None,
) -> SecretResolutionEvidence:
    return SecretResolutionEvidence(
        reference_id=reference.identity,
        kind=reference.kind,
        state=state,
        checked_at=_format_timestamp(now or datetime.now(timezone.utc)),
        backend_id=_safe_backend_id(backend_id) if backend_id else None,
        source_revision=source_revision,
        reference_expires_at=reference.expires_at,
    )


def _safe_error_message(code: SecretResolutionErrorCode) -> str:
    return {
        SecretResolutionErrorCode.UNAVAILABLE: "secret source is unavailable",
        SecretResolutionErrorCode.MISSING: "secret reference is missing",
        SecretResolutionErrorCode.DENIED: "secret resolution is denied",
        SecretResolutionErrorCode.EXPIRED: "secret reference has expired",
    }[code]


def _validate_reference_text(
    value: str,
    *,
    field: str,
    max_length: int = 256,
) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"secret reference {field} must not be empty")
    if len(value) > max_length or any(ord(character) < 32 for character in value):
        raise ValueError(
            f"secret reference {field} must be printable and at most {max_length} characters"
        )


def _validate_owner(owner: str) -> None:
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError("secret resolution requires an owning boundary")
    if len(owner) > 256 or any(ord(character) < 32 for character in owner):
        raise ValueError("secret resolution owner must be printable and bounded")


def _optional_text_field(value: Mapping[str, Any], field: str) -> str | None:
    item = value.get(field)
    if item is None:
        return None
    if not isinstance(item, str):
        raise ValueError(f"secret reference {field} must be text")
    return item


def _safe_backend_id(value: str) -> str:
    normalized = _SAFE_BACKEND_ID_RE.sub("-", str(value).strip().lower())
    return normalized.strip("-")[:64]


def _parse_timestamp(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("expires_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("expires_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
