"""Fail-closed provider-account continuity for admitted Harness sessions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from gpt2giga_harness.provider_authentication_broker import (
    ProviderAccountSnapshot,
    ProviderSessionBinding,
    provider_session_binding_to_dict,
)
from gpt2giga_harness.sessions.models import HarnessSession

PROVIDER_ACCOUNT_BINDING_KEY = "provider_account_binding"
NATIVE_PROVIDER_IDS = frozenset({"codex-cli", "claude-code", "gemini-cli"})
_IDENTITY_FIELDS = (
    "provider_id",
    "account_identity",
    "home_identity",
    "source_identity",
)


class ProviderAccountBindingProvider(Protocol):
    """Observe one broker-owned account without exposing credentials."""

    def session_binding(self, provider_id: str) -> ProviderSessionBinding | None:
        """Return a current ready binding, or None."""

    def status(self, provider_id: str) -> ProviderAccountSnapshot:
        """Return the current typed provider-account status."""


class ProviderAccountSessionError(ValueError):
    """Reject execution when provider-account continuity cannot be proven."""

    def __init__(
        self,
        code: str,
        *,
        provider_id: str,
        status: str,
        current: Mapping[str, Any] | None = None,
        candidate: Mapping[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.provider_id = provider_id
        self.status = status
        self.current = _public_binding(current)
        self.candidate = _public_binding(candidate)
        super().__init__(
            "Provider account identity changed or is unavailable; "
            "start a new session or inspect an evidence-only handoff."
        )

    def to_detail(self) -> dict[str, Any]:
        """Return content-free conflict evidence for API and UI recovery."""
        return {
            "code": self.code,
            "provider_id": self.provider_id,
            "status": self.status,
            "execution_authorized": False,
            "current": self.current,
            "candidate": self.candidate,
            "allowed_actions": ["new_session", "evidence_only_handoff"],
            "message": str(self),
        }


def prepare_provider_account_binding(
    session: HarnessSession,
    *,
    provider_id: str,
    native_session_id: str | None,
    provider: ProviderAccountBindingProvider | None,
) -> dict[str, Any] | None:
    """Bind a ready account or reject drift before run/message side effects."""
    current = _mapping(session.metadata.get(PROVIDER_ACCOUNT_BINDING_KEY))
    if current and provider_id not in NATIVE_PROVIDER_IDS:
        raise ProviderAccountSessionError(
            "provider_account_route_changed",
            provider_id=provider_id,
            status="different_provider_route",
            current=current,
        )
    if provider_id not in NATIVE_PROVIDER_IDS or provider is None:
        return None

    candidate_binding = provider.session_binding(provider_id)
    candidate = (
        provider_session_binding_to_dict(candidate_binding)
        if candidate_binding is not None
        else None
    )
    if candidate is None:
        snapshot = provider.status(provider_id)
        if current or native_session_id is not None:
            raise ProviderAccountSessionError(
                "provider_account_identity_unavailable",
                provider_id=provider_id,
                status=snapshot.status.value,
                current=current,
            )
        return None

    if current:
        mismatched = [
            field
            for field in _IDENTITY_FIELDS
            if current.get(field) != candidate[field]
        ]
        if mismatched:
            raise ProviderAccountSessionError(
                "provider_account_identity_drift",
                provider_id=provider_id,
                status="ready",
                current=current,
                candidate=candidate,
            )
        return dict(current)
    return candidate


def _public_binding(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not value:
        return None
    return {
        key: value.get(key)
        for key in (
            "schema_version",
            "provider_id",
            "account_identity",
            "home_identity",
            "source_identity",
            "identity_evidence",
            "authentication_method",
            "quota",
            "monetary_cost",
        )
        if key in value
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


__all__ = [
    "NATIVE_PROVIDER_IDS",
    "PROVIDER_ACCOUNT_BINDING_KEY",
    "ProviderAccountBindingProvider",
    "ProviderAccountSessionError",
    "prepare_provider_account_binding",
]
