"""Content-addressed links to immutable reviewed-promotion evidence."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

from gpt2giga_harness.runtime.policy import (
    PolicyAuditEvent,
    PolicyAuditPhase,
    REVIEWED_PROMOTION_APPLY_OWNER,
    REVIEWED_PROMOTION_BRANCH_OWNER,
    REVIEWED_PROMOTION_MERGE_OWNER,
)

REVIEWED_EVIDENCE_SCHEMA_VERSION = 1
_REVIEWED_PROMOTION_OWNERS = frozenset(
    {
        REVIEWED_PROMOTION_APPLY_OWNER,
        REVIEWED_PROMOTION_BRANCH_OWNER,
        REVIEWED_PROMOTION_MERGE_OWNER,
    }
)


def reviewed_evidence_manifest(
    run_id: str,
    events: Iterable[PolicyAuditEvent],
) -> dict[str, Any] | None:
    """Build one safe immutable-evidence link for a source run."""
    source_run_id = _required_text(run_id, "run_id")
    grouped: dict[str, list[PolicyAuditEvent]] = {}
    for event in events:
        if (
            event.run_id == source_run_id
            and event.enforcement_owner in _REVIEWED_PROMOTION_OWNERS
        ):
            grouped.setdefault(event.operation_id, []).append(event)

    operations: list[dict[str, Any]] = []
    for operation_id in sorted(grouped):
        chain = sorted(grouped[operation_id], key=lambda item: item.sequence)
        _validate_chain(chain, source_run_id=source_run_id)
        if chain[-1].phase is not PolicyAuditPhase.ENFORCEMENT:
            continue
        head = chain[-1]
        if not head.approval_binding_sha256:
            raise ValueError(
                "enforced reviewed evidence has no approval binding digest"
            )
        operations.append(
            {
                "operation_id": operation_id,
                "action": head.action.value,
                "enforcement_owner": head.enforcement_owner,
                "approval_binding_sha256": head.approval_binding_sha256,
                "audit_head_sha256": head.event_sha256,
                "event_count": len(chain),
            }
        )

    if not operations:
        return None
    manifest: dict[str, Any] = {
        "schema_version": REVIEWED_EVIDENCE_SCHEMA_VERSION,
        "source_run_id": source_run_id,
        "operations": operations,
    }
    manifest["manifest_sha256"] = _mapping_hash(manifest)
    return manifest


def reviewed_evidence_index(
    events: Iterable[PolicyAuditEvent],
) -> list[dict[str, Any]]:
    """Build stable manifests for every run with enforced reviewed evidence."""
    materialized = tuple(events)
    run_ids = sorted(
        {
            event.run_id
            for event in materialized
            if event.run_id and event.enforcement_owner in _REVIEWED_PROMOTION_OWNERS
        }
    )
    return [
        manifest
        for run_id in run_ids
        if (manifest := reviewed_evidence_manifest(run_id, materialized)) is not None
    ]


def _validate_chain(
    chain: list[PolicyAuditEvent],
    *,
    source_run_id: str,
) -> None:
    if not chain:
        raise ValueError("reviewed evidence chain is empty")
    first = chain[0]
    expected_phases = (
        PolicyAuditPhase.RESOLUTION,
        PolicyAuditPhase.DECISION,
        PolicyAuditPhase.ENFORCEMENT,
    )
    if len(chain) > len(expected_phases):
        raise ValueError("reviewed evidence chain has unexpected extra events")
    if tuple(event.phase for event in chain) != expected_phases[: len(chain)]:
        raise ValueError("reviewed evidence chain has an invalid phase order")
    for sequence, event in enumerate(chain, start=1):
        if event.sequence != sequence:
            raise ValueError("reviewed evidence chain has a sequence gap")
        if event.operation_id != first.operation_id:
            raise ValueError("reviewed evidence operation changed within its chain")
        if event.approval_request_id != first.approval_request_id:
            raise ValueError("reviewed evidence approval changed within its chain")
        if event.action is not first.action:
            raise ValueError("reviewed evidence action changed within its chain")
        if event.enforcement_owner != first.enforcement_owner:
            raise ValueError("reviewed evidence owner changed within its chain")
        if event.approval_binding_sha256 != first.approval_binding_sha256:
            raise ValueError("reviewed evidence binding changed within its chain")
        if event.run_id != source_run_id:
            raise ValueError("reviewed evidence source run changed within its chain")
        expected_previous = chain[sequence - 2].event_sha256 if sequence > 1 else None
        if event.previous_event_sha256 != expected_previous:
            raise ValueError("reviewed evidence hash chain is discontinuous")
        if event.event_sha256 != _event_hash(event):
            raise ValueError("reviewed evidence event hash is invalid")


def _event_hash(event: PolicyAuditEvent) -> str:
    payload = {
        "action": event.action.value,
        "approval_binding_sha256": event.approval_binding_sha256,
        "approval_grant_id": event.approval_grant_id,
        "approval_request_id": event.approval_request_id,
        "created_at": event.created_at,
        "decision": event.decision,
        "enforcement": event.enforcement.value,
        "enforcement_owner": event.enforcement_owner,
        "evidence": dict(event.evidence),
        "id": event.id,
        "job_id": event.job_id,
        "operation_id": event.operation_id,
        "phase": event.phase.value,
        "policy_source": event.policy_source,
        "previous_event_sha256": event.previous_event_sha256,
        "project_id": event.project_id,
        "run_id": event.run_id,
        "sequence": event.sequence,
        "session_id": event.session_id,
    }
    return _mapping_hash(payload)


def _mapping_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _required_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text
