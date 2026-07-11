"""Typed secret references and resolvers with explicit reveal boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import os
from typing import Any, Mapping, Protocol, runtime_checkable

_REDACTED = "<redacted>"


class SecretReferenceKind(str, Enum):
    """Supported secret storage backends."""

    ENVIRONMENT = "environment"
    KEYCHAIN = "keychain"


class SecretResolutionErrorCode(str, Enum):
    """Stable failure reason safe to expose through diagnostics."""

    UNAVAILABLE = "unavailable"
    MISSING = "missing"
    DENIED = "denied"
    EXPIRED = "expired"


class SecretResolutionError(RuntimeError):
    """Report a reference failure without including a resolved value."""

    def __init__(
        self,
        code: SecretResolutionErrorCode,
        reference: "SecretReference",
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.reference = reference


@dataclass(frozen=True)
class SecretReference:
    """Persistable pointer to a secret, never the secret value itself."""

    kind: SecretReferenceKind
    name: str
    service: str | None = None
    account: str | None = None
    expires_at: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("secret reference name must not be empty")
        if self.kind is SecretReferenceKind.ENVIRONMENT and (
            self.service is not None or self.account is not None
        ):
            raise ValueError("environment references do not accept service/account")
        if self.kind is SecretReferenceKind.KEYCHAIN and not self.service:
            raise ValueError("keychain references require service")
        if self.expires_at is not None:
            _parse_timestamp(self.expires_at)

    @property
    def expired(self) -> bool:
        """Return whether the reference expiry is in the past."""
        if self.expires_at is None:
            return False
        return _parse_timestamp(self.expires_at) <= datetime.now(timezone.utc)


class ResolvedSecret:
    """Opaque resolved value that requires an explicit owning boundary to reveal."""

    __slots__ = ("_owner", "_reference", "_value")

    def __init__(self, reference: SecretReference, value: str, *, owner: str) -> None:
        if not value:
            raise ValueError("resolved secret must not be empty")
        if not owner.strip():
            raise ValueError("resolved secret requires an owning boundary")
        self._reference = reference
        self._value = value
        self._owner = owner

    @property
    def reference(self) -> SecretReference:
        """Return the safe source reference."""
        return self._reference

    def reveal_for(self, owner: str) -> str:
        """Reveal only when an owning subprocess/request boundary is named."""
        if owner != self._owner:
            raise ValueError("secret reveal boundary does not match its owner")
        return self._value

    def __gpt2giga_redacted__(self) -> str:
        """Return the stable value used by shared persistence redaction."""
        return _REDACTED

    def __repr__(self) -> str:
        return f"ResolvedSecret(reference={self._reference!r}, value={_REDACTED!r})"

    def __str__(self) -> str:
        return _REDACTED


@runtime_checkable
class SecretResolver(Protocol):
    """Resolve supported references at the final owning boundary."""

    def supports(self, kind: SecretReferenceKind) -> bool: ...

    def resolve(self, reference: SecretReference, *, owner: str) -> ResolvedSecret: ...


class EnvironmentSecretResolver:
    """Resolve allowlisted environment variables without copying the environment."""

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
            raise SecretResolutionError(
                SecretResolutionErrorCode.UNAVAILABLE,
                reference,
                f"no installed resolver for {reference.kind.value} references",
            )
        if (
            self._allowed_names is not None
            and reference.name not in self._allowed_names
        ):
            raise SecretResolutionError(
                SecretResolutionErrorCode.DENIED,
                reference,
                f"environment reference is not allowed: {reference.name}",
            )
        value = self._environment.get(reference.name)
        if not value:
            raise SecretResolutionError(
                SecretResolutionErrorCode.MISSING,
                reference,
                f"environment reference is missing: {reference.name}",
            )
        return ResolvedSecret(reference, value, owner=owner)


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
        raise SecretResolutionError(
            SecretResolutionErrorCode.UNAVAILABLE,
            reference,
            f"no installed resolver for {reference.kind.value} references",
        )


def secret_reference_to_dict(reference: SecretReference) -> dict[str, Any]:
    """Serialize a reference without resolving it or exposing a value."""
    return {
        "kind": reference.kind.value,
        "name": reference.name,
        "service": reference.service,
        "account": reference.account,
        "expires_at": reference.expires_at,
    }


def _validate_resolution_request(reference: SecretReference, *, owner: str) -> None:
    if not owner.strip():
        raise ValueError("secret resolution requires an owning boundary")
    if reference.expired:
        raise SecretResolutionError(
            SecretResolutionErrorCode.EXPIRED,
            reference,
            f"secret reference has expired: {reference.name}",
        )


def _parse_timestamp(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("expires_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("expires_at must include a timezone")
    return parsed.astimezone(timezone.utc)
