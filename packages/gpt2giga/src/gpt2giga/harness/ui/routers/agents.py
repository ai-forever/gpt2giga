"""Agent profile inventory, authoring, validation, and manual run APIs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool
import yaml

from gpt2giga.harness.agents import (
    agent_profile_to_dict,
    agent_run_payload,
    discover_agent_profiles,
    draft_agent_profile,
    load_agent_profile,
    parse_agent_profile,
)
from gpt2giga.harness.authoring import AuthoringConflictError, ProjectAuthoringService
from gpt2giga.harness.project import project_to_dict, resolve_project
from gpt2giga.harness.sessions.models import run_to_dict
from gpt2giga.harness.sessions.store import new_id, title_from_prompt


router = APIRouter()


@router.get("/api/agents")
async def agent_list(
    request: Request,
    workspace: str | None = Query(default=None),
) -> dict[str, Any]:
    """List valid profiles and independent validation errors."""
    project = _project(request, workspace)
    profiles, errors = discover_agent_profiles(project.root)
    return {
        "project": project_to_dict(project),
        "agents": [agent_profile_to_dict(profile) for profile in profiles],
        "errors": [error.__dict__ for error in errors],
    }


@router.get("/api/agents/{agent_id}")
async def agent_detail(
    agent_id: str,
    request: Request,
    workspace: str | None = Query(default=None),
) -> dict[str, Any]:
    """Return one validated profile and its source YAML."""
    project = _project(request, workspace)
    try:
        profile = load_agent_profile(project.root, agent_id)
        source = (
            (project_root := Path(project.root).resolve())
            .joinpath(profile.source_path or "")
            .read_text(encoding="utf-8")
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent profile not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "profile": agent_profile_to_dict(profile),
        "source": source,
        "project_root": str(project_root),
    }


@router.post("/api/agents/validate")
async def agent_validate(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Validate AgentProfile YAML without reading or writing a project file."""
    try:
        profile = parse_agent_profile(str(payload.get("content") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"valid": True, "profile": agent_profile_to_dict(profile)}


@router.post("/api/agents/{agent_id}/draft")
async def agent_draft(
    agent_id: str,
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Return a validated redacted diff and source ETag without writing."""
    project = _project(request, payload.get("workspace"))
    try:
        draft = draft_agent_profile(
            project.root,
            agent_id,
            str(payload.get("content") or ""),
            expected_hash=_optional_text(payload.get("expected_hash")),
        )
    except AuthoringConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "profile": agent_profile_to_dict(draft.value),
        "relative_path": draft.relative_path,
        "source_hash": draft.source_hash,
        "redacted_diff": draft.redacted_diff,
    }


@router.post("/api/agents/{agent_id}/apply")
async def agent_apply(
    agent_id: str,
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Validate and atomically apply after the explicit ETag check."""
    project = _project(request, payload.get("workspace"))
    try:
        draft = draft_agent_profile(
            project.root,
            agent_id,
            str(payload.get("content") or ""),
            expected_hash=_optional_text(payload.get("expected_hash")),
        )
        new_hash = ProjectAuthoringService(project.root).apply(draft)
    except AuthoringConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "applied": True,
        "source_hash": new_hash,
        "profile": agent_profile_to_dict(draft.value),
    }


@router.post("/api/agents/{agent_id}/duplicate")
async def agent_duplicate(
    agent_id: str,
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Preview a duplicate under a new safe id; applying stays explicit."""
    project = _project(request, payload.get("workspace"))
    new_id_value = str(payload.get("new_id") or "").strip()
    try:
        source_profile = load_agent_profile(project.root, agent_id)
        source = (
            Path(project.root)
            .resolve()
            .joinpath(source_profile.source_path or "")
            .read_text(encoding="utf-8")
        )
        data = yaml.safe_load(source)
        data["id"] = new_id_value
        data["title"] = str(payload.get("title") or f"{source_profile.title} Copy")
        content = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
        draft = draft_agent_profile(project.root, new_id_value, content)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent profile not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "content": content,
        "source_hash": draft.source_hash,
        "redacted_diff": draft.redacted_diff,
        "profile": agent_profile_to_dict(draft.value),
    }


@router.post("/api/agents/{agent_id}/run")
async def agent_run(
    agent_id: str,
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """Queue one authenticated manual run with an immutable profile snapshot."""
    project = _project(request, payload.get("workspace"))
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")
    try:
        profile = load_agent_profile(project.root, agent_id)
        registry = request.app.state.harness_registry
        registry.get(profile.harness_id)
        run_payload = agent_run_payload(profile, prompt, workspace=project.root)
        runner = request.app.state.harness_session_runner
        session = runner.create_session(
            title=title_from_prompt(prompt),
            workspace=project.root,
            default_harness_id=profile.harness_id,
            default_model=profile.model,
            default_api_mode=profile.api_mode,
            default_mode=profile.mode,
        )
        dispatcher = request.app.state.harness_job_dispatcher
        if dispatcher is None:
            raise RuntimeError("Durable runtime is required for agent runs")
        submission = await run_in_threadpool(
            dispatcher.submit,
            session.id,
            run_payload,
            idempotency_key=str(
                payload.get("idempotency_key") or f"agent_{new_id('submit')}"
            ),
            origin="manual",
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Agent profile or harness not found"
        ) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "session": {"id": session.id, "title": session.title},
        "run": run_to_dict(submission.queued.run),
        "profile": agent_profile_to_dict(profile),
        "stream_url": f"/api/runs/{submission.queued.run.id}/events/stream",
    }


def _project(request: Request, workspace: Any):
    try:
        return resolve_project(
            _optional_text(workspace),
            data_dir=request.app.state.harness_config.data_dir,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
