"""Authenticated schedule CRUD and worker-trigger APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from starlette.responses import JSONResponse

from gpt2giga_harness.project import resolve_project
from gpt2giga_harness.ui.async_execution import ConformantAPIRoute
from gpt2giga_harness.runtime.policy import (
    EnforcementLevel,
    INTERACTIVE_PROFILE,
    PermissionAction,
    PolicyContext,
    PolicyDecision,
    SCHEDULE_CREATE_OWNER,
    SCHEDULE_ENABLE_OWNER,
    SCHEDULE_RUN_NOW_OWNER,
    approval_request_to_dict,
)
from gpt2giga_harness.schedules import (
    ScheduleConflictError,
    ScheduleError,
    build_schedule_definition,
    next_occurrences,
    schedule_definition_to_dict,
)

router = APIRouter(route_class=ConformantAPIRoute)


@router.get("/api/schedules")
def schedule_list(
    request: Request, workspace: str | None = Query(default=None)
) -> dict[str, Any]:
    """List project definitions with mutable state and recent history."""
    project = _project(request, workspace)
    return {"schedules": list(_service(request).list(project))}


@router.post("/api/schedules/preview")
def schedule_preview(
    request: Request, payload: dict[str, Any] = Body(...)
) -> dict[str, Any]:
    """Validate a draft and preview upcoming UTC instants without writing."""
    project = _project(request, payload.get("workspace"))
    try:
        definition = build_schedule_definition(project, payload)
    except (KeyError, ScheduleError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "definition": schedule_definition_to_dict(definition),
        "occurrences": list(next_occurrences(definition)),
        "dry_run": True,
    }


@router.post("/api/schedules", status_code=201)
def schedule_create(request: Request, payload: dict[str, Any] = Body(...)) -> Any:
    """Create or replace one disabled definition and invalidate its test grant."""
    project = _project(request, payload.get("workspace"))
    try:
        draft = build_schedule_definition(project, payload)
        gated = _authorize(
            request,
            PermissionAction.SCHEDULE_CREATE,
            project_id=project.id,
            reason="Create or materially update a project schedule.",
            preview={
                "schedule_id": draft.id,
                "schedule_hash": draft.source_hash,
                "target": f"{draft.target_kind}:{draft.target_id}",
            },
        )
        if gated is not None:
            return gated
        return _service(request).upsert(project, payload)
    except (KeyError, ScheduleError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/schedules/{schedule_id}")
def schedule_detail(
    schedule_id: str,
    request: Request,
    workspace: str | None = Query(default=None),
) -> dict[str, Any]:
    """Return one definition, state, preview, and bounded occurrence history."""
    try:
        return _service(request).detail(_project(request, workspace), schedule_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc
    except ScheduleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/api/schedules/{schedule_id}")
def schedule_update(
    schedule_id: str, request: Request, payload: dict[str, Any] = Body(...)
) -> Any:
    """Materially edit a definition, pausing it and invalidating Test now."""
    if payload.get("id") not in {None, schedule_id}:
        raise HTTPException(status_code=409, detail="schedule id cannot be renamed")
    project = _project(request, payload.get("workspace"))
    try:
        expected_hash = payload.get("expected_hash")
        if expected_hash is not None:
            current = _service(request).detail(project, schedule_id)
            if current["definition"]["source_hash"] != expected_hash:
                raise HTTPException(
                    status_code=409,
                    detail="Schedule changed since it was loaded",
                )
        draft_payload = {**payload, "id": schedule_id}
        draft_payload.pop("expected_hash", None)
        draft = build_schedule_definition(project, draft_payload)
        gated = _authorize(
            request,
            PermissionAction.SCHEDULE_CREATE,
            project_id=project.id,
            reason="Create or materially update a project schedule.",
            preview={
                "schedule_id": draft.id,
                "schedule_hash": draft.source_hash,
                "target": f"{draft.target_kind}:{draft.target_id}",
            },
        )
        if gated is not None:
            return gated
        return _service(request).upsert(
            project,
            draft_payload,
            expected_hash=expected_hash,
        )
    except ScheduleConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (KeyError, ScheduleError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/schedules/{schedule_id}")
def schedule_delete(
    schedule_id: str,
    request: Request,
    workspace: str | None = Query(default=None),
    expected_hash: str | None = Query(default=None),
    confirm_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Delete the shareable definition while retaining SQLite audit history."""
    project = _project(request, workspace)
    service = _service(request)
    try:
        if expected_hash is not None or confirm_id is not None:
            detail = service.detail(project, schedule_id)
            if detail["definition"]["source_hash"] != expected_hash:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Schedule changed since the delete preview; reload before deleting"
                    ),
                )
            if confirm_id != schedule_id:
                raise HTTPException(
                    status_code=400,
                    detail="confirm_id must exactly match the schedule id",
                )
        return service.archive(
            project,
            schedule_id,
            expected_hash=expected_hash,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc
    except ScheduleConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/schedules/{schedule_id}/delete-preview")
def schedule_delete_preview(
    schedule_id: str,
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Preview the exact schedule revision and retained occurrence history."""
    try:
        detail = _service(request).detail(
            _project(request, payload.get("workspace")), schedule_id
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc
    state = detail.get("state") or {}
    dependents = [
        {
            "kind": "occurrence",
            "id": item["id"],
            "status": item["status"],
        }
        for item in detail.get("occurrences") or ()
    ]
    return {
        "kind": "schedule",
        "id": schedule_id,
        "source_hash": detail["definition"]["source_hash"],
        "dependents": dependents,
        "active_dependents": [
            item
            for item in dependents
            if item["status"] not in {"succeeded", "failed", "canceled"}
        ],
        "state": {
            "status": state.get("status"),
            "enabled": bool(state.get("enabled")),
        },
        "confirmation_required": True,
    }


@router.post("/api/schedules/{schedule_id}/test-now")
def schedule_test_now(
    schedule_id: str,
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Run the exact target through a safe backend dry run and grant its hash."""
    return _action(request, schedule_id, payload, "test_now")


@router.post("/api/schedules/{schedule_id}/enable")
def schedule_enable(
    schedule_id: str,
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Enable only an exactly tested hash while a local worker is online."""
    return _action(request, schedule_id, payload, "enable")


@router.post("/api/schedules/{schedule_id}/pause")
def schedule_pause(
    schedule_id: str,
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Pause future triggers without deleting history."""
    return _action(request, schedule_id, payload, "pause")


@router.post("/api/schedules/{schedule_id}/resume")
def schedule_resume(
    schedule_id: str,
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Resume through the same worker and tested-hash gate as enable."""
    return _action(request, schedule_id, payload, "enable")


@router.post("/api/schedules/{schedule_id}/run-now")
def schedule_run_now(
    schedule_id: str,
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Queue one explicit occurrence through normal unattended policy."""
    return _action(request, schedule_id, payload, "run_now")


def _action(
    request: Request, schedule_id: str, payload: dict[str, Any], method: str
) -> Any:
    try:
        project = _project(request, payload.get("workspace"))
        action = {
            "enable": PermissionAction.SCHEDULE_ENABLE,
            "run_now": PermissionAction.SCHEDULE_RUN_NOW,
        }.get(method)
        if action is not None:
            detail = _service(request).detail(project, schedule_id)
            definition = detail["definition"]
            state = detail.get("state") or {}
            if state.get("tested_hash") != definition["source_hash"]:
                raise ScheduleError(
                    "Test now must succeed for this exact schedule hash first"
                )
            if method == "enable" and not detail["worker"]["online"]:
                raise ScheduleError(
                    "A local durable worker must be online before enable"
                )
            gated = _authorize(
                request,
                action,
                project_id=project.id,
                reason=f"{method.replace('_', ' ').title()} a project schedule.",
                preview={
                    "schedule_id": schedule_id,
                    "schedule_hash": definition["source_hash"],
                    "target": (
                        f"{definition['target']['kind']}:{definition['target']['id']}"
                    ),
                },
            )
            if gated is not None:
                return gated
        kwargs = (
            {"idempotency_key": _idempotency_key(payload.get("idempotency_key"))}
            if method in {"test_now", "run_now"}
            and payload.get("idempotency_key") is not None
            else {}
        )
        return getattr(_service(request), method)(project, schedule_id, **kwargs)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc
    except ScheduleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _service(request: Request):
    service = request.app.state.harness_schedule_service
    if service is None:
        raise HTTPException(status_code=409, detail="Durable runtime is unavailable")
    return service


def _authorize(
    request: Request,
    action: PermissionAction,
    *,
    project_id: str,
    reason: str,
    preview: dict[str, Any],
) -> JSONResponse | None:
    owner = {
        PermissionAction.SCHEDULE_CREATE: SCHEDULE_CREATE_OWNER,
        PermissionAction.SCHEDULE_ENABLE: SCHEDULE_ENABLE_OWNER,
        PermissionAction.SCHEDULE_RUN_NOW: SCHEDULE_RUN_NOW_OWNER,
    }[action]
    context = PolicyContext(
        project_id=project_id,
        reason=reason,
        preview=preview,
        enforcement_owner=owner,
    )
    resolution = request.app.state.harness_policy_engine.resolve(
        action,
        profile=INTERACTIVE_PROFILE,
        context=context,
        enforcement=EnforcementLevel.ENFORCED_BY_HARNESS,
    )
    if resolution.decision is PolicyDecision.ALLOW:
        return None
    if resolution.decision is PolicyDecision.DENY:
        raise HTTPException(status_code=403, detail=f"{action.value} denied by policy")
    approval = request.app.state.harness_runtime_store.create_approval_request(
        resolution, context
    )
    return JSONResponse(
        status_code=202,
        content={
            "approval_required": True,
            "approval": approval_request_to_dict(approval),
            "retry_action": True,
        },
    )


def _project(request: Request, workspace: Any):
    try:
        return resolve_project(
            str(workspace) if workspace else None,
            data_dir=request.app.state.harness_config.data_dir,
            load_config_name=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _idempotency_key(value: Any) -> str:
    key = str(value or "").strip()
    if not key:
        raise ScheduleError("idempotency key is required")
    if len(key) > 200:
        raise ScheduleError("idempotency key must be at most 200 characters")
    return key
