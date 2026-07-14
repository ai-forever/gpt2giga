"""Project identity and canonicalization helpers for native discovery."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Mapping

from gpt2giga_harness.native.models import NativeSessionRef, NativeSessionStatus
from gpt2giga_harness.project import project_id_for_root


def normalize_native_workspace(value: Any) -> str | None:
    """Normalize a workspace recorded by an external CLI without requiring it."""
    if value is None or not str(value).strip():
        return None
    try:
        return str(Path(str(value)).expanduser().resolve())
    except (OSError, ValueError):
        return None


def native_workspace_metadata(
    workspace: str | None,
    *,
    evidence: str | None,
) -> dict[str, Any]:
    """Describe whether project identity came from structured history evidence."""
    normalized = normalize_native_workspace(workspace)
    if normalized is None:
        return {
            "workspace_known": False,
            "workspace_reason": "not_recorded",
        }
    return {
        "project_id": project_id_for_root(normalized),
        "workspace_known": True,
        "workspace_evidence": evidence or "structured_history",
    }


def canonicalize_native_refs(
    refs: Iterable[NativeSessionRef],
) -> tuple[NativeSessionRef, ...]:
    """Merge duplicate sources for one native session into one stable reference."""
    canonical: dict[tuple[str, str], NativeSessionRef] = {}
    anonymous: list[NativeSessionRef] = []
    for ref in refs:
        identity = native_ref_identity(ref)
        if identity is None:
            anonymous.append(ref)
            continue
        existing = canonical.get(identity)
        canonical[identity] = (
            ref if existing is None else merge_native_refs(existing, ref)
        )
    values = [*canonical.values(), *anonymous]
    values.sort(
        key=lambda ref: (
            _ref_quality(ref),
            ref.updated_at or ref.created_at or "",
            ref.id,
        )
    )
    values.reverse()
    return tuple(values)


def native_ref_identity(ref: NativeSessionRef) -> tuple[str, str] | None:
    """Return the cross-source identity used to reconcile one native session."""
    if not ref.native_session_id:
        return None
    return ref.harness_id, ref.native_session_id


def merge_native_refs(
    first: NativeSessionRef,
    second: NativeSessionRef,
) -> NativeSessionRef:
    """Preserve the richest safe source while retaining reconciliation evidence."""
    preferred, other = (
        (second, first)
        if _ref_quality(second) >= _ref_quality(first)
        else (first, second)
    )
    metadata = {**dict(other.metadata), **dict(preferred.metadata)}
    source_kinds = {
        str(value)
        for value in (
            first.metadata.get("source_kind"),
            second.metadata.get("source_kind"),
        )
        if value is not None and str(value).strip()
    }
    sources = {source for source in (first.source, second.source) if source}
    if len(source_kinds) > 1:
        metadata["source_kinds"] = tuple(sorted(source_kinds))
    if len(sources) > 1:
        metadata["reconciled_sources"] = tuple(sorted(sources))
    return replace(
        preferred,
        title=preferred.title or other.title,
        workspace=preferred.workspace or other.workspace,
        created_at=preferred.created_at or other.created_at,
        updated_at=max(
            (value for value in (first.updated_at, second.updated_at) if value),
            default=None,
        ),
        message_count=(
            preferred.message_count
            if preferred.message_count is not None
            else other.message_count
        ),
        can_preview=first.can_preview or second.can_preview,
        can_import=first.can_import or second.can_import,
        can_resume=first.can_resume or second.can_resume,
        resume_reason=None
        if first.can_resume or second.can_resume
        else preferred.resume_reason or other.resume_reason,
        metadata=metadata,
        execution_snapshot=preferred.execution_snapshot or other.execution_snapshot,
    )


def _ref_quality(ref: NativeSessionRef) -> tuple[int, int, int, int]:
    status_rank = {
        NativeSessionStatus.MANAGED_NATIVE: 4,
        NativeSessionStatus.LINKED: 3,
        NativeSessionStatus.IMPORTED: 2,
        NativeSessionStatus.EXTERNAL_NATIVE: 1,
        NativeSessionStatus.READONLY: 0,
    }
    return (
        status_rank.get(ref.status, 0),
        int(ref.can_import),
        int(ref.can_preview),
        int(ref.execution_snapshot is not None),
    )


def metadata_mapping(value: Any) -> Mapping[str, Any]:
    """Return a mapping for defensive structured-history inspection."""
    return value if isinstance(value, Mapping) else {}
