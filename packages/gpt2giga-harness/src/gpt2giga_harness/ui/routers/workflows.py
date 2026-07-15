"""Versioned workflow inventory and execution APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse, Response

from gpt2giga_harness.project import project_to_dict, resolve_project
from gpt2giga_harness.ui.async_execution import ConformantAPIRoute
from gpt2giga_harness.reviewed_evidence import reviewed_evidence_manifest
from gpt2giga_harness.promotions import (
    apply_run_promotion,
    preview_run_promotion,
    promotion_to_dict,
)
from gpt2giga_harness.authoring import AuthoringConflictError
from gpt2giga_harness.sessions.store import RunNotFoundError
from gpt2giga_harness.runtime.models import ApprovalStatus
from gpt2giga_harness.runtime.policy import (
    EnforcementLevel,
    PermissionAction,
    PolicyContext,
    PolicyDecision,
    PolicyResolution,
    REVIEWED_PROMOTION_MERGE_OWNER,
    approval_binding_digest,
    approval_request_to_dict,
)
from gpt2giga_harness.worktrees import (
    WorktreeConflictError,
    WorktreeError,
    review_run_diff,
)
from gpt2giga_harness.workflow_catalog import (
    duplicate_workflow,
    save_workflow,
    template_source,
    workflow_catalog_detail,
    workflow_source,
    workflow_templates,
)
from gpt2giga_harness.workflows import (
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


router = APIRouter(route_class=ConformantAPIRoute)


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


class WorkflowSaveRequest(BaseModel):
    """Validated workflow source or typed builder update."""

    model_config = ConfigDict(extra="forbid")

    workspace: str | None = None
    content: str = Field(min_length=1)
    expected_hash: str | None = None
    form: dict[str, Any] | None = None


class WorkflowDuplicateRequest(BaseModel):
    """Create an independent catalog entry."""

    model_config = ConfigDict(extra="forbid")

    workspace: str | None = None
    new_id: str = Field(min_length=2, max_length=64)


class WorkflowImportRequest(BaseModel):
    """Import YAML or instantiate a built-in template."""

    model_config = ConfigDict(extra="forbid")

    workspace: str | None = None
    content: str | None = None
    template_id: str | None = None


class WorkflowHandoffChoiceRequest(BaseModel):
    """Explicit patch selection state."""

    model_config = ConfigDict(extra="forbid")

    selected: bool = True


class WorkflowMergeApplyRequest(BaseModel):
    """Approval reference for applying a prepared merge queue."""

    model_config = ConfigDict(extra="forbid")

    approval_id: str | None = None


class RunPromotionPreviewRequest(BaseModel):
    """Requested run-derived project YAML candidate."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    target_id: str = Field(min_length=2, max_length=64)


class RunPromotionApplyRequest(RunPromotionPreviewRequest):
    """Reviewed promotion content plus optimistic-lock values."""

    content: str = Field(min_length=1)
    source_hash: str
    review_token: str


@router.post("/api/runs/{run_id}/promotions/preview")
def run_promotion_preview(
    run_id: str,
    request: Request,
    payload: RunPromotionPreviewRequest = Body(...),
) -> dict[str, Any]:
    """Infer and validate a portable candidate without writing project YAML."""
    try:
        runtime = request.app.state.harness_runtime_store
        reviewed_evidence = (
            reviewed_evidence_manifest(
                run_id,
                runtime.list_policy_audit_events(run_id=run_id),
            )
            if runtime is not None
            else None
        )
        draft = preview_run_promotion(
            request.app.state.harness_session_store,
            run_id,
            kind=payload.kind,
            target_id=payload.target_id,
            reviewed_evidence=reviewed_evidence,
        )
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"review_required": True, "promotion": promotion_to_dict(draft)}


@router.post("/api/runs/{run_id}/promotions/apply")
def run_promotion_apply(
    run_id: str,
    request: Request,
    payload: RunPromotionApplyRequest = Body(...),
) -> dict[str, Any]:
    """Write an explicitly reviewed candidate after token and ETag checks."""
    try:
        new_hash, draft = apply_run_promotion(
            request.app.state.harness_session_store,
            run_id,
            kind=payload.kind,
            target_id=payload.target_id,
            content=payload.content,
            source_hash=payload.source_hash,
            review_token=payload.review_token,
        )
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    except AuthoringConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "applied": True,
        "kind": payload.kind,
        "target_id": payload.target_id,
        "relative_path": draft.relative_path,
        "source_hash": new_hash,
    }


@router.get("/api/workflows")
def workflow_list(
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
        "templates": list(workflow_templates()),
    }


@router.post("/api/workflows/import", status_code=201)
def workflow_import(
    request: Request, payload: WorkflowImportRequest = Body(...)
) -> dict[str, Any]:
    """Import validated YAML or instantiate a built-in template."""
    project = _project(request, payload.workspace)
    if bool(payload.content) == bool(payload.template_id):
        raise HTTPException(
            status_code=400, detail="Provide exactly one of content or template_id"
        )
    try:
        content = payload.content or template_source(payload.template_id or "")
        definition = save_workflow(project.root, content)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Workflow template not found"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return workflow_catalog_detail(project.root, definition.id)


@router.post("/api/workflows/validate")
def workflow_validate(
    payload: WorkflowValidateRequest = Body(...),
) -> dict[str, Any]:
    """Validate workflow YAML and return the canonical dry-run plan."""
    try:
        definition = parse_workflow_definition(payload.content, allow_unknown=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "valid": True,
        "workflow": workflow_definition_to_dict(definition),
        "plan": workflow_plan(definition),
    }


@router.get("/api/workflows/{workflow_id}")
def workflow_detail(
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
        **workflow_catalog_detail(project.root, definition.id),
        "runs": [
            workflow_run_to_dict(item)
            for item in WorkflowRepository(_runtime_store(request)).list_runs(
                workflow_id=definition.id, project_id=project.id
            )
        ],
    }


@router.put("/api/workflows/{workflow_id}")
def workflow_save(
    workflow_id: str,
    request: Request,
    payload: WorkflowSaveRequest = Body(...),
) -> dict[str, Any]:
    """Atomically save a validated YAML or typed builder revision."""
    project = _project(request, payload.workspace)
    try:
        workflow_source(project.root, workflow_id)
        definition = save_workflow(
            project.root,
            payload.content,
            expected_hash=payload.expected_hash,
            expected_id=workflow_id,
            form=payload.form,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return workflow_catalog_detail(project.root, definition.id)


@router.post("/api/workflows/{workflow_id}/duplicate", status_code=201)
def workflow_duplicate(
    workflow_id: str,
    request: Request,
    payload: WorkflowDuplicateRequest = Body(...),
) -> dict[str, Any]:
    """Duplicate one definition into an independent editable entry."""
    project = _project(request, payload.workspace)
    try:
        definition = duplicate_workflow(project.root, workflow_id, payload.new_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return workflow_catalog_detail(project.root, definition.id)


@router.get("/api/workflows/{workflow_id}/export")
def workflow_export(
    workflow_id: str,
    request: Request,
    workspace: str | None = Query(default=None),
) -> Response:
    """Export the exact project YAML as a portable attachment."""
    project = _project(request, workspace)
    try:
        content = workflow_source(project.root, workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow not found") from exc
    return Response(
        content=content,
        media_type="application/yaml",
        headers={
            "Content-Disposition": f'attachment; filename="{workflow_id}.yaml"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/api/workflows/{workflow_id}/run")
def workflow_run(
    workflow_id: str,
    request: Request,
    payload: WorkflowRunRequest = Body(...),
) -> dict[str, Any]:
    """Start a durable workflow run from an immutable definition snapshot."""
    project = _project(request, payload.workspace)
    try:
        definition = load_workflow(project.root, workflow_id)
        coordinator = _coordinator(request, project)
        run = coordinator.start(
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
def workflow_run_status(run_id: str, request: Request) -> dict[str, Any]:
    """Advance and return one durable workflow run."""
    repository = WorkflowRepository(_runtime_store(request))
    try:
        current = repository.get_run(run_id)
        project = resolve_project(
            current.project_root,
            data_dir=request.app.state.harness_config.data_dir,
        )
        coordinator = _coordinator(request, project)
        run = coordinator.advance(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow run not found") from exc
    return {"run": workflow_run_to_dict(run, coordinator.repository.list_steps(run_id))}


@router.post("/api/workflow-runs/{run_id}/cancel")
def workflow_run_cancel(run_id: str, request: Request) -> dict[str, Any]:
    """Cancel a workflow and propagate cancellation to active children."""
    repository = WorkflowRepository(_runtime_store(request))
    try:
        current = repository.get_run(run_id)
        project = resolve_project(
            current.project_root,
            data_dir=request.app.state.harness_config.data_dir,
        )
        coordinator = _coordinator(request, project)
        run = coordinator.cancel(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow run not found") from exc
    return {"run": workflow_run_to_dict(run, coordinator.repository.list_steps(run_id))}


@router.get("/api/workflow-runs/{run_id}/handoffs")
def workflow_handoff_status(run_id: str, request: Request) -> dict[str, Any]:
    """Return typed edit candidates, selections, and overlap conflicts."""
    try:
        return _handoffs(request, run_id).status(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow run not found") from exc


@router.post("/api/workflow-runs/{run_id}/handoffs/{step_id}/choose")
def workflow_handoff_choose(
    run_id: str,
    step_id: str,
    request: Request,
    payload: WorkflowHandoffChoiceRequest = Body(
        default_factory=WorkflowHandoffChoiceRequest
    ),
) -> dict[str, Any]:
    """Explicitly choose or unchoose one isolated child patch."""
    try:
        return _handoffs(request, run_id).choose(
            run_id,
            step_id,
            selected=payload.selected,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow run not found") from exc
    except WorktreeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/workflow-runs/{run_id}/handoffs/{step_id}/discard")
def workflow_handoff_discard(
    run_id: str, step_id: str, request: Request
) -> dict[str, Any]:
    """Discard one retained child worktree without applying it."""
    try:
        return _handoffs(request, run_id).discard(run_id, step_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow run not found") from exc
    except WorktreeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/workflow-runs/{run_id}/merge-queue")
def workflow_merge_prepare(run_id: str, request: Request) -> dict[str, Any]:
    """Prepare a non-overlapping combined patch in another isolated worktree."""
    try:
        return _handoffs(request, run_id).prepare_merge(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow run not found") from exc
    except WorktreeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WorktreeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/workflow-runs/{run_id}/merge-queue/apply", response_model=None)
def workflow_merge_apply(
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
        queue = _merge_queue(run)
        if queue.get("status") != "prepared":
            raise WorktreeError("Merge queue is not prepared.")
        execution = queue.get("workspace_execution")
        if not isinstance(execution, dict):
            raise WorktreeError("Merge queue has no reviewed workspace execution.")
        review = review_run_diff({"workspace_execution": execution})
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
                        **review.to_preview(),
                        "workflow_run_id": run.id,
                        "source_run_ids": list(queue.get("source_run_ids") or ()),
                    },
                    approval_binding=review.approval_binding,
                    enforcement_owner=REVIEWED_PROMOTION_MERGE_OWNER,
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
            or approval.preview.get("approval_binding_sha256")
            != approval_binding_digest(review.approval_binding)
        ):
            raise WorktreeError("A matching approved git.apply request is required.")
        consumed = runtime.consume_matching_approval_grant(
            action=PermissionAction.GIT_APPLY,
            project_id=run.project_id,
            run_id=run.id,
            job_id=None,
            approval_binding=review.approval_binding,
            enforcement_owner=REVIEWED_PROMOTION_MERGE_OWNER,
        )
        if not consumed:
            raise WorktreeError("The reviewed git.apply approval is unavailable.")
        return manager.apply_merge(run_id, review=review)
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
