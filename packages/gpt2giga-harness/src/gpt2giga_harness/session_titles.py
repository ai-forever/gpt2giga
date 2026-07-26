"""Versioned, native-first session title arbitration."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Mapping, Protocol
from uuid import uuid4

from gpt2giga_harness.product_capabilities import TitleProvenance


SESSION_TITLE_STATE_KEY = "title_state"
SESSION_TITLE_STATE_SCHEMA_VERSION = 1
_CAS_ATTEMPTS = 8


class _SessionStore(Protocol):
    def get_session(self, session_id: str) -> Any:
        """Return one session."""

    def update_session_if_revision(
        self,
        session_id: str,
        expected_updated_at: str,
        **patch: Any,
    ) -> Any | None:
        """Atomically patch one session revision."""


@dataclass(frozen=True)
class SessionTitleClaim:
    """One first-turn fallback generation claim."""

    session_id: str
    run_id: str
    claim_id: str
    model: str | None
    timeout_seconds: float


@dataclass(frozen=True)
class SessionTitleGeneration:
    """Bounded result of optional fallback title generation."""

    title: str
    status: str
    duration_ms: float
    usage: Mapping[str, int]
    failure_kind: str | None = None


def new_session_metadata(
    metadata: Mapping[str, Any] | None,
    *,
    explicit_title: bool,
    provenance: TitleProvenance | None = None,
    source: str | None = None,
    source_id: str | None = None,
) -> dict[str, Any]:
    """Initialize title state for a newly created session."""
    payload = dict(metadata or {})
    if _state_mapping(payload.get(SESSION_TITLE_STATE_KEY)) is not None:
        return payload
    resolved = provenance or (
        TitleProvenance.MANUAL if explicit_title else TitleProvenance.UNTITLED
    )
    payload[SESSION_TITLE_STATE_KEY] = _settled_state(
        resolved,
        source=source or ("explicit_create" if explicit_title else "new_session"),
        source_id=source_id,
    )
    return payload


def manual_title_metadata(
    metadata: Mapping[str, Any],
    *,
    source: str = "manual_update",
) -> dict[str, Any]:
    """Mark an explicit title patch as manual authority."""
    payload = dict(metadata)
    payload[SESSION_TITLE_STATE_KEY] = _settled_state(
        TitleProvenance.MANUAL,
        source=source,
    )
    return payload


def merge_title_metadata(
    current: Mapping[str, Any],
    incoming: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep the newest title state across unrelated stale metadata patches."""
    payload = dict(incoming)
    current_state = _state_mapping(current.get(SESSION_TITLE_STATE_KEY))
    incoming_state = _state_mapping(incoming.get(SESSION_TITLE_STATE_KEY))
    if current_state is None:
        return payload
    if incoming_state is None or _state_order(current_state) > _state_order(
        incoming_state
    ):
        payload[SESSION_TITLE_STATE_KEY] = current_state
    return payload


def provider_native_title_metadata(
    metadata: Mapping[str, Any] | None,
    *,
    provider: str,
    source_id: str | None,
) -> dict[str, Any]:
    """Bind an imported native title without exposing provider content."""
    payload = dict(metadata or {})
    payload[SESSION_TITLE_STATE_KEY] = _settled_state(
        TitleProvenance.PROVIDER_NATIVE,
        source=provider,
        source_id=source_id,
    )
    return payload


def title_diagnostics(session: Any) -> dict[str, Any]:
    """Return content-free title provenance and generation diagnostics."""
    state = _title_state(session)
    diagnostics = {
        key: value
        for key, value in state.items()
        if key
        in {
            "schema_version",
            "provenance",
            "status",
            "source",
            "source_id",
            "bound_run_id",
            "model",
            "timeout_seconds",
            "duration_ms",
            "usage",
            "cost",
            "failure_kind",
        }
        and value is not None
    }
    return diagnostics


def claim_fallback_title(
    store: _SessionStore,
    session_id: str,
    *,
    run_id: str,
    model: str | None,
    timeout_seconds: float,
) -> SessionTitleClaim | None:
    """Claim the first accepted turn exactly once for fallback generation."""
    claim = SessionTitleClaim(
        session_id=session_id,
        run_id=run_id,
        claim_id=uuid4().hex,
        model=model,
        timeout_seconds=timeout_seconds,
    )
    for _ in range(_CAS_ATTEMPTS):
        session = store.get_session(session_id)
        state = _title_state(session)
        if (
            state["provenance"] != TitleProvenance.UNTITLED.value
            or state["status"] != "idle"
        ):
            return None
        next_state = {
            "schema_version": SESSION_TITLE_STATE_SCHEMA_VERSION,
            "provenance": TitleProvenance.UNTITLED.value,
            "status": "pending",
            "source": "bounded_fallback",
            "bound_run_id": run_id,
            "claim_id": claim.claim_id,
            "model": model,
            "timeout_seconds": timeout_seconds,
            "cost": {"knowledge": "unknown"},
            "updated_at": _now(),
        }
        updated = store.update_session_if_revision(
            session_id,
            session.updated_at,
            metadata=_metadata_with_state(session.metadata, next_state),
        )
        if updated is not None:
            return claim
    return None


def complete_fallback_title(
    store: _SessionStore,
    claim: SessionTitleClaim,
    generation: SessionTitleGeneration,
) -> Any | None:
    """Settle one claimed fallback without overwriting manual/native authority."""
    for _ in range(_CAS_ATTEMPTS):
        session = store.get_session(claim.session_id)
        state = _title_state(session)
        if (
            state["provenance"] != TitleProvenance.UNTITLED.value
            or state["status"] != "pending"
            or state.get("bound_run_id") != claim.run_id
            or state.get("claim_id") != claim.claim_id
        ):
            return None
        next_state = {
            "schema_version": SESSION_TITLE_STATE_SCHEMA_VERSION,
            "provenance": TitleProvenance.FALLBACK.value,
            "status": generation.status,
            "source": "bounded_fallback",
            "bound_run_id": claim.run_id,
            "model": claim.model,
            "timeout_seconds": claim.timeout_seconds,
            "duration_ms": round(max(generation.duration_ms, 0.0), 3),
            "usage": _bounded_usage(generation.usage),
            "cost": {"knowledge": "unknown"},
            "failure_kind": generation.failure_kind,
            "updated_at": _now(),
        }
        updated = store.update_session_if_revision(
            claim.session_id,
            session.updated_at,
            title=generation.title,
            metadata=_metadata_with_state(session.metadata, next_state),
        )
        if updated is not None:
            return updated
    return None


def apply_provider_native_title(
    store: _SessionStore,
    session_id: str,
    *,
    title: str,
    run_id: str,
    provider: str,
    source_id: str | None,
) -> Any | None:
    """Promote a bound native title over untitled/fallback state exactly once."""
    normalized = " ".join(str(title).split()).strip()[:512]
    if not normalized:
        return None
    for _ in range(_CAS_ATTEMPTS):
        session = store.get_session(session_id)
        state = _title_state(session)
        provenance = state["provenance"]
        if provenance == TitleProvenance.PROVIDER_NATIVE.value:
            return None
        if provenance not in {
            TitleProvenance.UNTITLED.value,
            TitleProvenance.FALLBACK.value,
        }:
            return None
        bound_run_id = state.get("bound_run_id")
        if bound_run_id is not None and bound_run_id != run_id:
            return None
        next_state = {
            "schema_version": SESSION_TITLE_STATE_SCHEMA_VERSION,
            "provenance": TitleProvenance.PROVIDER_NATIVE.value,
            "status": "settled",
            "source": provider,
            "source_id": source_id,
            "bound_run_id": run_id,
            "updated_at": _now(),
        }
        updated = store.update_session_if_revision(
            session_id,
            session.updated_at,
            title=normalized,
            metadata=_metadata_with_state(session.metadata, next_state),
        )
        if updated is not None:
            return updated
    return None


def _title_state(session: Any) -> dict[str, Any]:
    state = _state_mapping(session.metadata.get(SESSION_TITLE_STATE_KEY))
    if state is not None:
        return state
    return {
        "schema_version": SESSION_TITLE_STATE_SCHEMA_VERSION,
        "provenance": TitleProvenance.LEGACY.value,
        "status": "settled",
        "source": "legacy_session",
    }


def _settled_state(
    provenance: TitleProvenance,
    *,
    source: str,
    source_id: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SESSION_TITLE_STATE_SCHEMA_VERSION,
        "provenance": provenance.value,
        "status": ("idle" if provenance is TitleProvenance.UNTITLED else "settled"),
        "source": source,
        "source_id": source_id,
        "updated_at": _now(),
    }


def _state_mapping(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    if value.get("schema_version") != SESSION_TITLE_STATE_SCHEMA_VERSION:
        return None
    try:
        TitleProvenance(str(value.get("provenance")))
    except ValueError:
        return None
    return dict(value)


def _metadata_with_state(
    metadata: Mapping[str, Any],
    state: Mapping[str, Any],
) -> dict[str, Any]:
    payload = dict(metadata)
    payload[SESSION_TITLE_STATE_KEY] = dict(state)
    return payload


def _bounded_usage(usage: Mapping[str, int]) -> dict[str, int]:
    return {
        key: int(value)
        for key, value in usage.items()
        if key in {"input_tokens", "output_tokens", "total_tokens"}
        and isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 0
    }


def _state_order(state: Mapping[str, Any]) -> int:
    try:
        return int(str(state.get("updated_at") or "0"))
    except ValueError:
        return 0


def _now() -> str:
    return str(time.time_ns())
