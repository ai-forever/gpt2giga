"""Versioned workflow inventory and execution APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from gpt2giga.harness.project import project_to_dict, resolve_project
from gpt2giga.harness.workflows import (
    WorkflowCoordinator,
    WorkflowRepository,
    discover_workflows,
    load_workflow,
    parse_workflow_definition,
    workflow_definition_to_dict,
    workflow_plan,
    workflow_run_to_dict,
)


router = APIRouter()


class WorkflowValidateRequest(BaseModel):
    """Untrusted YAML validation request."""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1)


class WorkflowRunRequest(BaseModel):
    """One manual workflow submission."""

    model_config = ConfigDict(extra="forbid")

    workspace: str | None = None
    prompt: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)


@router.get("/api/workflows")
async def workflow_list(
    request: Request, workspace: str | None = Query(default=None)
) -> dict[str, Any]:
    """List valid definitions and independent validation failures."""
    project = _project(request, workspace)
    definitions, errors = discover_workflows(project.root)
    repository = WorkflowRepository(_runtime_store(request))
    return {
        "project": project_to_dict(project),
        "workflows": [workflow_definition_to_dict(item) for item in definitions],
        "errors": [{"path": item.path, "error": item.error} for item in errors],
        "runs": [
            workflow_run_to_dict(item)
            for item in repository.list_runs(project_id=project.id)
        ],
    }


@router.post("/api/workflows/validate")
async def workflow_validate(
    payload: WorkflowValidateRequest = Body(...),
) -> dict[str, Any]:
    """Validate workflow YAML and return the canonical dry-run plan."""
    try:
        definition = parse_workflow_definition(payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "valid": True,
        "workflow": workflow_definition_to_dict(definition),
        "plan": workflow_plan(definition),
    }


@router.get("/api/workflows/{workflow_id}")
async def workflow_detail(
    workflow_id: str,
    request: Request,
    workspace: str | None = Query(default=None),
) -> dict[str, Any]:
    """Return one definition and its deterministic execution plan."""
    project = _project(request, workspace)
    try:
        definition = load_workflow(project.root, workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow not found") from exc
    return {
        "workflow": workflow_definition_to_dict(definition),
        "plan": workflow_plan(definition),
    }


@router.post("/api/workflows/{workflow_id}/run")
async def workflow_run(
    workflow_id: str,
    request: Request,
    payload: WorkflowRunRequest = Body(...),
) -> dict[str, Any]:
    """Start a durable workflow run from an immutable definition snapshot."""
    project = _project(request, payload.workspace)
    try:
        definition = load_workflow(project.root, workflow_id)
        coordinator = _coordinator(request, project)
        run = await run_in_threadpool(
            coordinator.start,
            definition,
            inputs=dict(payload.inputs),
            prompt=_optional_text(payload.prompt),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    steps = coordinator.repository.list_steps(run.id)
    return {"run": workflow_run_to_dict(run, steps)}


@router.get("/api/workflow-runs/{run_id}")
async def workflow_run_status(run_id: str, request: Request) -> dict[str, Any]:
    """Advance and return one durable workflow run."""
    repository = WorkflowRepository(_runtime_store(request))
    try:
        current = repository.get_run(run_id)
        project = resolve_project(
            current.project_root,
            data_dir=request.app.state.harness_config.data_dir,
        )
        coordinator = _coordinator(request, project)
        run = await run_in_threadpool(coordinator.advance, run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow run not found") from exc
    return {"run": workflow_run_to_dict(run, coordinator.repository.list_steps(run_id))}


@router.post("/api/workflow-runs/{run_id}/cancel")
async def workflow_run_cancel(run_id: str, request: Request) -> dict[str, Any]:
    """Cancel a workflow and propagate cancellation to active children."""
    repository = WorkflowRepository(_runtime_store(request))
    try:
        current = repository.get_run(run_id)
        project = resolve_project(
            current.project_root,
            data_dir=request.app.state.harness_config.data_dir,
        )
        coordinator = _coordinator(request, project)
        run = await run_in_threadpool(coordinator.cancel, run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow run not found") from exc
    return {"run": workflow_run_to_dict(run, coordinator.repository.list_steps(run_id))}


def _runtime_store(request: Request):
    store = request.app.state.harness_runtime_store
    if store is None:
        raise HTTPException(status_code=409, detail="Durable runtime is unavailable")
    return store


def _coordinator(request: Request, project):
    dispatcher = request.app.state.harness_job_dispatcher
    if dispatcher is None:
        raise HTTPException(status_code=409, detail="Durable runtime is unavailable")
    return WorkflowCoordinator(
        project=project,
        runtime_store=_runtime_store(request),
        runner=request.app.state.harness_session_runner,
        dispatcher=dispatcher,
    )


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
