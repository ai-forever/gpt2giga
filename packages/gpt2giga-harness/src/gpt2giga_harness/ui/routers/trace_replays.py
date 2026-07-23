"""Trace-to-Replay preview, execution, and retained comparison routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request

from gpt2giga_harness.sessions.store import RunNotFoundError, SessionNotFoundError
from gpt2giga_harness.trace_replay import (
    TraceReplayConflictError,
    TraceReplayService,
)
from gpt2giga_harness.ui.async_execution import ConformantAPIRoute


router = APIRouter(route_class=ConformantAPIRoute)


@router.post("/api/runs/{run_id}/trace-replays/preview")
def preview_trace_replay(
    run_id: str,
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Preview one exact one-axis replay without starting execution."""
    try:
        return _service(request).preview(run_id, payload)
    except (RunNotFoundError, SessionNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    except TraceReplayConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/runs/{run_id}/trace-replays")
def start_trace_replay(
    run_id: str,
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Start one reviewed manifest through the existing execution authority."""
    try:
        return _service(request).start(run_id, payload)
    except (RunNotFoundError, SessionNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    except TraceReplayConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/runs/{run_id}/trace-replay")
def get_trace_replay(run_id: str, request: Request) -> dict[str, Any]:
    """Return a bounded retained source/destination comparison."""
    try:
        return _service(request).projection(run_id)
    except (RunNotFoundError, SessionNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Trace replay not found") from exc
    except (TraceReplayConflictError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _service(request: Request) -> TraceReplayService:
    return request.app.state.harness_trace_replay_service
