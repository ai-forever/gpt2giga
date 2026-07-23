"""Approval Center APIs for Harness-owned policy decisions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request

from gpt2giga_harness.application import (
    DurableRuntimeUnavailableError,
    SessionApplicationService,
)
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
from gpt2giga_harness.ui.routers.tui_actions import validate_run_action_binding


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
        binding = payload.get("run_binding")
        if isinstance(binding, dict):
            approval = _runtime_store(request).get_approval_request(approval_id)
            if not approval.run_id:
                raise ValueError("approval has no run binding")
            run = request.app.state.harness_session_store.get_run(approval.run_id)
            validate_run_action_binding(run, binding)
        decision = ApprovalDecision(str(payload.get("decision") or ""))
        expiry = payload.get("expires_in_seconds")
        project_expiry = float(expiry) if expiry is not None else None
        result = _session_service(request).decide_approval(
            approval_id,
            decision,
            project_expiry_seconds=project_expiry,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Approval not found") from exc
    except DurableRuntimeUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (InvalidStateTransitionError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "approval": approval_request_to_dict(result.approval),
        "job_status": result.job.status.value if result.job else None,
        "retry_action": result.retry_action,
    }


def _runtime_store(request: Request) -> RuntimeCoordinationStore:
    store = getattr(request.app.state, "harness_runtime_store", None)
    if not isinstance(store, RuntimeCoordinationStore):
        raise HTTPException(status_code=409, detail="Durable runtime is unavailable")
    return store


def _session_service(request: Request) -> SessionApplicationService:
    service = getattr(request.app.state, "harness_session_service", None)
    if not isinstance(service, SessionApplicationService):
        raise DurableRuntimeUnavailableError(
            "Session application service is unavailable"
        )
    return service
