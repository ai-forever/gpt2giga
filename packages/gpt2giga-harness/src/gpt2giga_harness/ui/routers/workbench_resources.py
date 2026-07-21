"""Bounded Workbench tasks, processes, usage, preferences, and inventory API."""

from __future__ import annotations

from typing import Any, Mapping

from fastapi import APIRouter, Body, HTTPException, Query, Request

from gpt2giga_harness.runtime.store import (
    JobNotFoundError,
    NativeProcessRecordNotFoundError,
)
from gpt2giga_harness.ui.async_execution import ConformantAPIRoute
from gpt2giga_harness.workbench_resources import (
    WorkbenchResourceError,
    preference_snapshot_to_dict,
    process_binding,
    resource_snapshot_to_dict,
    task_binding,
)


router = APIRouter(route_class=ConformantAPIRoute)


@router.get("/api/workbench/resources")
def workbench_resources(
    request: Request,
    session_id: str | None = Query(default=None, max_length=256),
) -> dict[str, Any]:
    """Return one bounded provider-neutral operational snapshot."""
    try:
        snapshot = request.app.state.harness_workbench_resources.snapshot(session_id)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return resource_snapshot_to_dict(snapshot)


@router.post("/api/workbench/tasks/{task_id}/cancel")
def cancel_workbench_task(
    task_id: str,
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Request cancellation only for the exact presented child and owner lease."""
    binding = _binding(payload, task_id)
    try:
        task = request.app.state.harness_workbench_resources.cancel_task(binding)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    except WorkbenchResourceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"task": task.__dict__, "binding": task_binding(task)}


@router.post("/api/workbench/processes/{process_id}/stop")
def stop_workbench_process(
    process_id: str,
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Stop a process only while its presented owner and lease remain exact."""
    binding = _binding(payload, process_id)
    service = request.app.state.harness_workbench_resources
    try:
        process = service.validate_process(binding)
        request.app.state.harness_native_process_manager.stop(process.id)
        refreshed = service.snapshot(process.session_id)
        stopped = next(item for item in refreshed.processes if item.id == process.id)
    except NativeProcessRecordNotFoundError as exc:
        raise HTTPException(status_code=404, detail="process not found") from exc
    except WorkbenchResourceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"process": stopped.__dict__, "binding": process_binding(stopped)}


@router.put("/api/workbench/preferences")
def save_workbench_preferences(
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Persist private Workbench-only preferences with optimistic concurrency."""
    expected_revision = str(payload.get("expected_revision") or "").strip()
    values = payload.get("values")
    if not expected_revision or not isinstance(values, Mapping):
        raise HTTPException(status_code=400, detail="preference binding is invalid")
    try:
        snapshot = request.app.state.harness_workbench_resources.save_preferences(
            values, expected_revision=expected_revision
        )
    except WorkbenchResourceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"preferences": preference_snapshot_to_dict(snapshot)}


def _binding(payload: Mapping[str, Any], identity: str) -> Mapping[str, Any]:
    binding = payload.get("binding", payload)
    if not isinstance(binding, Mapping) or binding.get("id") != identity:
        raise HTTPException(status_code=409, detail="resource identity changed")
    return binding
