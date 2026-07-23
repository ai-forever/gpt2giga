"""Exact-generation interactive actions shared by terminal clients."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from fastapi import APIRouter, Body, HTTPException, Request

from gpt2giga_harness.sessions.models import HarnessRun
from gpt2giga_harness.sessions.store import RunNotFoundError
from gpt2giga_harness.structured_sessions import StructuredTurnInput
from gpt2giga_harness.ui.async_execution import ConformantAPIRoute
from gpt2giga_harness.ui.routers.cockpit import run_snapshot_revision


router = APIRouter(route_class=ConformantAPIRoute)


@router.post("/api/runs/{run_id}/steer")
def steer_run(
    run_id: str,
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Steer only the exact locally owned structured turn generation."""
    run = _bound_run(request, run_id, payload)
    content = _required_content(payload.get("content"), "steer content")
    idempotency_key = _required_identity(
        payload.get("idempotency_key"), "idempotency key"
    )
    harness = request.app.state.harness_registry.get(run.harness_id)
    config = request.app.state.harness_config
    supervisors = getattr(harness, "_app_server_supervisors", {})
    supervisor = getattr(harness, "app_server_supervisor", None) or supervisors.get(
        config.data_dir
    )
    if supervisor is None:
        raise HTTPException(
            status_code=409,
            detail="Active structured owner is unavailable; resnapshot required",
        )
    try:
        supervisor.steer_turn(
            run.session_id,
            StructuredTurnInput(idempotency_key, content),
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "accepted": True,
        "run_id": run.id,
        "generation": _run_generation(run),
        "idempotency_key": idempotency_key,
    }


@router.post("/api/runs/{run_id}/input")
def answer_run_input(
    run_id: str,
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Fail closed until the active provider advertises a retained input bridge."""
    run = _bound_run(request, run_id, payload)
    _required_identity(payload.get("input_id"), "input request")
    _required_content(payload.get("answer"), "input answer")
    raise HTTPException(
        status_code=409,
        detail=(
            f"Harness {run.harness_id} does not expose an owned interactive input "
            "bridge for this run"
        ),
    )


def validate_run_action_binding(run: HarnessRun, payload: Mapping[str, Any]) -> None:
    """Reject mutations whose presented run identity is no longer current."""
    if payload.get("run_id") not in {None, run.id}:
        raise HTTPException(status_code=409, detail="Run identity changed")
    if payload.get("session_id") not in {None, run.session_id}:
        raise HTTPException(status_code=409, detail="Session identity changed")
    revision = payload.get("revision")
    if revision is not None and revision != run_snapshot_revision(run):
        raise HTTPException(status_code=409, detail="Run revision changed")
    generation = payload.get("generation")
    if generation is not None and generation != _run_generation(run):
        raise HTTPException(status_code=409, detail="Run generation changed")


def _bound_run(request: Request, run_id: str, payload: Mapping[str, Any]) -> HarnessRun:
    try:
        run = request.app.state.harness_session_store.get_run(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    validate_run_action_binding(run, payload)
    return run


def _run_generation(run: HarnessRun) -> int:
    metadata = run.metadata if isinstance(run.metadata, Mapping) else {}
    link = metadata.get("structured_session_link")
    link = link if isinstance(link, Mapping) else {}
    revision = link.get("revision")
    if isinstance(revision, int) and not isinstance(revision, bool) and revision > 0:
        return revision
    runtime = metadata.get("runtime")
    runtime = runtime if isinstance(runtime, Mapping) else {}
    attempt = runtime.get("attempt_number")
    if isinstance(attempt, int) and not isinstance(attempt, bool) and attempt > 0:
        return attempt
    link_hash = link.get("link_hash")
    if isinstance(link_hash, str) and link_hash:
        return max(
            int(hashlib.sha256(link_hash.encode()).hexdigest()[:8], 16),
            1,
        )
    return 1


def _required_identity(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if (
        not text
        or len(text) > 256
        or not all(character.isalnum() or character in "._:@+~-" for character in text)
    ):
        raise HTTPException(status_code=400, detail=f"{field_name} is invalid")
    return text


def _required_content(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=400, detail=f"{field_name} is required")
    if len(value) > 32_768:
        raise HTTPException(status_code=413, detail=f"{field_name} is too large")
    return value
