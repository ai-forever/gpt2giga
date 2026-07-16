"""Authenticated Scheduled Automation Center and Attention Inbox APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request

from gpt2giga_harness.attention import AttentionService
from gpt2giga_harness.project import resolve_project
from gpt2giga_harness.ui.async_execution import ConformantAPIRoute

router = APIRouter(route_class=ConformantAPIRoute)


@router.get("/api/automation")
def automation_center(
    request: Request, workspace: str | None = Query(default=None)
) -> dict[str, Any]:
    """Return schedules, calendar material, history, worker, and inbox state."""
    project = _project(request, workspace)
    schedule_service = request.app.state.harness_schedule_service
    if schedule_service is None:
        raise HTTPException(status_code=409, detail="Durable runtime is unavailable")
    overview = schedule_service.automation_overview(project)
    attention = _attention(request).list(project)
    return {**overview, "attention": attention}


@router.get("/api/attention")
def attention_inbox(
    request: Request, workspace: str | None = Query(default=None)
) -> dict[str, Any]:
    """Return the combined project Attention Inbox."""
    return _attention(request).list(_project(request, workspace))


@router.post("/api/attention/read")
def attention_read(
    request: Request, payload: dict[str, Any] = Body(...)
) -> dict[str, Any]:
    """Persist acknowledgement without deleting source audit metadata."""
    item_ids = tuple(str(item) for item in payload.get("item_ids") or ())
    if not item_ids or len(item_ids) > 200:
        raise HTTPException(status_code=400, detail="item_ids must contain 1-200 ids")
    _attention(request).mark_read(
        item_ids,
        read=bool(payload.get("read", True)),
    )
    return {"updated": len(item_ids), "read": bool(payload.get("read", True))}


def _attention(request: Request) -> AttentionService:
    return AttentionService(
        runtime_store=request.app.state.harness_runtime_store,
        schedule_service=request.app.state.harness_schedule_service,
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
