"""Versioned workflow inventory and execution APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from gpt2giga.harness.project import project_to_dict, resolve_project
from gpt2giga.harness.runtime.models import ApprovalStatus
from gpt2giga.harness.runtime.policy import (
    EnforcementLevel,
    PermissionAction,
    PolicyContext,
    PolicyDecision,
    PolicyResolution,
    approval_request_to_dict,
)
from gpt2giga.harness.worktrees import WorktreeConflictError, WorktreeError
from gpt2giga.harness.workflows import (
    WorkflowCoordinator,
    WorkflowHandoffManager,
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


class WorkflowHandoffChoiceRequest(BaseModel):
    """Explicit patch selection state."""

    model_config = ConfigDict(extra="forbid")

    selected: bool = True


class WorkflowMergeApplyRequest(BaseModel):
    """Approval reference for applying a prepared merge queue."""

    model_config = ConfigDict(extra="forbid")

    approval_id: str | None = None


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


@router.get("/api/workflow-runs/{run_id}/handoffs")
async def workflow_handoff_status(run_id: str, request: Request) -> dict[str, Any]:
    """Return typed edit candidates, selections, and overlap conflicts."""
    try:
        return _handoffs(request, run_id).status(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow run not found") from exc


@router.post("/api/workflow-runs/{run_id}/handoffs/{step_id}/choose")
async def workflow_handoff_choose(
    run_id: str,
    step_id: str,
    request: Request,
    payload: WorkflowHandoffChoiceRequest = Body(
        default_factory=WorkflowHandoffChoiceRequest
    ),
) -> dict[str, Any]:
    """Explicitly choose or unchoose one isolated child patch."""
    try:
        return await run_in_threadpool(
            _handoffs(request, run_id).choose,
            run_id,
            step_id,
            selected=payload.selected,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow run not found") from exc
    except WorktreeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/workflow-runs/{run_id}/handoffs/{step_id}/discard")
async def workflow_handoff_discard(
    run_id: str, step_id: str, request: Request
) -> dict[str, Any]:
    """Discard one retained child worktree without applying it."""
    try:
        return await run_in_threadpool(
            _handoffs(request, run_id).discard, run_id, step_id
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow run not found") from exc
    except WorktreeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/workflow-runs/{run_id}/merge-queue")
async def workflow_merge_prepare(run_id: str, request: Request) -> dict[str, Any]:
    """Prepare a non-overlapping combined patch in another isolated worktree."""
    try:
        return await run_in_threadpool(_handoffs(request, run_id).prepare_merge, run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow run not found") from exc
    except WorktreeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WorktreeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/workflow-runs/{run_id}/merge-queue/apply", response_model=None)
async def workflow_merge_apply(
    run_id: str,
    request: Request,
    payload: WorkflowMergeApplyRequest = Body(
        default_factory=WorkflowMergeApplyRequest
    ),
) -> dict[str, Any] | JSONResponse:
    """Apply a prepared merge only after an auditable git.apply approval."""
    manager = _handoffs(request, run_id)
    runtime = _runtime_store(request)
    try:
        run = manager.repository.get_run(run_id)
        if _merge_queue(run).get("status") != "prepared":
            raise WorktreeError("Merge queue is not prepared.")
        if not payload.approval_id:
            approval = runtime.create_approval_request(
                PolicyResolution(
                    action=PermissionAction.GIT_APPLY,
                    decision=PolicyDecision.ASK,
                    enforcement=EnforcementLevel.ENFORCED_BY_HARNESS,
                    policy_source=f"workflow:{run.workflow_id}:merge-queue",
                ),
                PolicyContext(
                    project_id=run.project_id,
                    session_id=run.session_id,
                    run_id=run.id,
                    reason="Apply the reviewed workflow merge queue to the source checkout.",
                    preview={
                        "workflow_run_id": run.id,
                        "source_run_ids": list(
                            _merge_queue(run).get("source_run_ids") or ()
                        ),
                        "changed_files": list(
                            _merge_queue(run).get("changed_files") or ()
                        ),
                    },
                ),
            )
            return JSONResponse(
                status_code=202,
                content={
                    "approval_required": True,
                    "approval": approval_request_to_dict(approval),
                },
            )
        approval = runtime.get_approval_request(payload.approval_id)
        if (
            approval.status is not ApprovalStatus.APPROVED
            or approval.action is not PermissionAction.GIT_APPLY
            or approval.run_id != run.id
        ):
            raise WorktreeError("A matching approved git.apply request is required.")
        return await run_in_threadpool(manager.apply_merge, run_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Workflow run or approval not found"
        ) from exc
    except WorktreeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WorktreeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


def _handoffs(request: Request, run_id: str) -> WorkflowHandoffManager:
    repository = WorkflowRepository(_runtime_store(request))
    current = repository.get_run(run_id)
    project = resolve_project(
        current.project_root,
        data_dir=request.app.state.harness_config.data_dir,
    )
    return WorkflowHandoffManager(_coordinator(request, project))


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


def _merge_queue(run: Any) -> dict[str, Any]:
    value = run.outputs.get("_merge_queue")
    return dict(value) if isinstance(value, dict) else {}
