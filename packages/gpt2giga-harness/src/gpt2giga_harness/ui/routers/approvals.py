"""Approval Center APIs for Harness-owned policy decisions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request

from gpt2giga_harness.ui.async_execution import ConformantAPIRoute
from gpt2giga_harness.runtime.models import ApprovalStatus
from gpt2giga_harness.runtime.policy import (
    ApprovalDecision,
    INTERACTIVE_PROFILE,
    REVIEW_EVERY_ACTION_PROFILE,
    UNATTENDED_PROFILE,
    approval_request_to_dict,
)
from gpt2giga_harness.runtime.store import (
    InvalidStateTransitionError,
    RuntimeCoordinationStore,
)
from gpt2giga_harness.sessions.models import HarnessStoredEvent
from gpt2giga_harness.sessions.store import new_id, utc_now


router = APIRouter(route_class=ConformantAPIRoute)


@router.get("/api/policy/profiles")
async def policy_profiles() -> dict[str, Any]:
    """Return built-in profile decisions without exposing mutable policy input."""
    profiles = (
        INTERACTIVE_PROFILE,
        REVIEW_EVERY_ACTION_PROFILE,
        UNATTENDED_PROFILE,
    )
    return {
        "profiles": [
            {
                "id": profile.id,
                "default": profile.default.value,
                "rules": {
                    action.value: decision.value
                    for action, decision in profile.rules.items()
                },
            }
            for profile in profiles
        ]
    }


@router.get("/api/approvals")
def approval_inbox(
    request: Request,
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
) -> dict[str, Any]:
    """Return approval requests newest first plus the pending attention count."""
    store = _runtime_store(request)
    try:
        parsed_status = ApprovalStatus(status) if status else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid approval status") from exc
    items = store.list_approval_requests(status=parsed_status, limit=limit)
    pending = store.list_approval_requests(status=ApprovalStatus.PENDING, limit=200)
    return {
        "approvals": [approval_request_to_dict(item) for item in items],
        "pending_count": len(pending),
    }


@router.post("/api/approvals/{approval_id}/decision")
def decide_approval(
    approval_id: str,
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Persist one user decision and requeue or cancel a gated pre-spawn job."""
    try:
        decision = ApprovalDecision(str(payload.get("decision") or ""))
        expiry = payload.get("expires_in_seconds")
        project_expiry = float(expiry) if expiry is not None else None
        decided = _runtime_store(request).decide_approval_request(
            approval_id,
            decision,
            project_expiry_seconds=project_expiry,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Approval not found") from exc
    except (InvalidStateTransitionError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _append_decision_event(request, decided)
    job = _runtime_store(request).get_job(decided.job_id) if decided.job_id else None
    session_store = getattr(request.app.state, "harness_session_store", None)
    if (
        job is not None
        and job.status.value == "canceled"
        and decided.run_id
        and session_store is not None
        and hasattr(session_store, "update_run")
    ):
        session_store.update_run(
            decided.run_id,
            status="canceled",
            error="approval denied",
            finished_at=utc_now(),
        )
    return {
        "approval": approval_request_to_dict(decided),
        "job_status": job.status.value if job else None,
        "retry_action": job is None and decision is not ApprovalDecision.DENY,
    }


def _runtime_store(request: Request) -> RuntimeCoordinationStore:
    store = getattr(request.app.state, "harness_runtime_store", None)
    if not isinstance(store, RuntimeCoordinationStore):
        raise HTTPException(status_code=409, detail="Durable runtime is unavailable")
    return store


def _append_decision_event(request: Request, approval: Any) -> None:
    session_store = getattr(request.app.state, "harness_session_store", None)
    if (
        session_store is None
        or not hasattr(session_store, "append_event")
        or not approval.session_id
    ):
        return
    session_store.append_event(
        HarnessStoredEvent(
            id=new_id("evt"),
            session_id=approval.session_id,
            run_id=approval.run_id,
            type="approval_decided",
            message=f"Approval {approval.status.value}: {approval.action.value}.",
            payload={
                "approval_id": approval.id,
                "action": approval.action.value,
                "decision": approval.decision.value if approval.decision else None,
                "enforcement": approval.enforcement.value,
            },
            created_at=utc_now(),
            trace_id=approval.job_id or approval.run_id,
            job_id=approval.job_id,
            span_kind="approval",
            span_status=approval.status.value,
        )
    )
