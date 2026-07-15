"""Eval Lab inventory, compatibility matrices, baselines, and cancellation."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request

from gpt2giga_harness.ui.async_execution import ConformantAPIRoute
from gpt2giga_harness.agents import discover_agent_profiles
from gpt2giga_harness.evals import (
    EvalRunNotFoundError,
    compare_eval_run_to_baseline,
    discover_eval_specs,
    eval_compatibility_matrix,
    eval_run_to_dict,
    eval_spec_load_error_to_dict,
    eval_spec_to_dict,
    load_eval_spec,
    protocol_conformance_matrix,
)
from gpt2giga_harness.project import project_to_dict, resolve_project
from gpt2giga_harness.types import spec_capability_values
from gpt2giga_harness.workflows import discover_workflows


router = APIRouter(route_class=ConformantAPIRoute)


@router.get("/api/evaluate")
def evaluate_inventory(
    request: Request, workspace: str | None = Query(default=None)
) -> dict[str, Any]:
    """Return separate protocol and quality lab projections."""
    project = _project(request, workspace)
    specs, errors = discover_eval_specs(project.root)
    agents, agent_errors = discover_agent_profiles(project.root)
    workflows, workflow_errors = discover_workflows(project.root)
    eval_store = request.app.state.harness_eval_store
    runs = eval_store.list_runs(project, limit=50)
    enriched_runs = []
    for eval_run in runs:
        payload = eval_run_to_dict(eval_run)
        payload["baseline_delta"] = compare_eval_run_to_baseline(
            eval_run, eval_store.get_baseline(project, eval_run.spec_name)
        )
        enriched_runs.append(payload)
    return {
        "project": project_to_dict(project),
        "protocol_matrix": protocol_conformance_matrix(
            request.app.state.harness_registry
        ),
        "quality_specs": [
            {
                **eval_spec_to_dict(spec),
                "matrix": eval_compatibility_matrix(
                    spec, request.app.state.harness_registry
                ),
                "dimensions": _quality_dimensions(
                    spec,
                    agents,
                    workflows,
                    request.app.state.harness_registry,
                ),
                "baseline": eval_store.get_baseline(project, spec.name),
            }
            for spec in specs
        ],
        "errors": [
            *[eval_spec_load_error_to_dict(error) for error in errors],
            *[{"path": item.path, "message": item.error} for item in agent_errors],
            *[{"path": item.path, "message": item.error} for item in workflow_errors],
        ],
        "runs": enriched_runs,
        "trends": _trend_rows(enriched_runs),
    }


@router.get("/api/evaluate/{eval_name}/matrix")
def evaluate_matrix(
    eval_name: str,
    request: Request,
    workspace: str | None = Query(default=None),
) -> dict[str, Any]:
    """Return the filtered matrix without queuing invalid combinations."""
    project = _project(request, workspace)
    try:
        spec = load_eval_spec(project.root, eval_name)
        cells = eval_compatibility_matrix(spec, request.app.state.harness_registry)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"spec": eval_spec_to_dict(spec), "cells": cells}


@router.post("/api/evaluate/runs/{eval_run_id}/baseline")
def pin_eval_baseline(
    eval_run_id: str,
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Pin a completed scorecard with git and config hashes."""
    project = _project(request, payload.get("workspace"))
    eval_store = request.app.state.harness_eval_store
    try:
        eval_run = eval_store.get(project, eval_run_id)
    except EvalRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Eval run not found") from exc
    if eval_run.status not in {"passed", "failed"}:
        raise HTTPException(
            status_code=409, detail="Only completed evals can be pinned"
        )
    return {"baseline": eval_store.pin_baseline(project, eval_run)}


@router.post("/api/evaluate/runs/{eval_run_id}/cancel")
def cancel_eval_run(
    eval_run_id: str,
    request: Request,
) -> dict[str, Any]:
    """Request cancellation for every non-terminal durable matrix cell."""
    eval_store = request.app.state.harness_eval_store
    runtime_store = request.app.state.harness_runtime_store
    if runtime_store is None:
        raise HTTPException(status_code=409, detail="Durable runtime is unavailable")
    try:
        eval_run = eval_store.get_any(eval_run_id)
    except EvalRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Eval run not found") from exc
    canceled: list[str] = []
    for result in eval_run.results:
        if (
            result.status not in {"queued", "running", "retry_wait"}
            or not result.run_id
        ):
            continue
        job = runtime_store.find_job_for_run(result.run_id)
        if job is None:
            continue
        runtime_store.request_cancel(job.id)
        canceled.append(job.id)
    return {"eval_run_id": eval_run.id, "cancel_requested": canceled}


def _project(request: Request, workspace: Any):
    try:
        return resolve_project(
            _optional_text(workspace),
            data_dir=request.app.state.harness_config.data_dir,
            load_config_name=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _trend_rows(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": item["id"],
            "spec_name": item["spec_name"],
            "created_at": item["created_at"],
            "status": item["status"],
            "score": item.get("summary", {}).get("score", 0.0),
            "metrics": item.get("summary", {}).get("metrics", {}),
            "flakes": item.get("summary", {}).get("flakes", 0),
        }
        for item in reversed(runs)
    ]


def _quality_dimensions(spec, agents, workflows, registry) -> dict[str, Any]:
    required = {
        case.required_capability.value
        for case in spec.cases
        if case.required_capability is not None
    }
    compatible_agents = []
    tool_profiles: set[str] = set()
    for agent in agents:
        try:
            capabilities = set(
                spec_capability_values(registry.get(agent.harness_id).spec())
            )
        except KeyError:
            continue
        if not required.issubset(capabilities):
            continue
        compatible_agents.append(
            {
                "id": agent.id,
                "harness_id": agent.harness_id,
                "model": agent.model,
                "tool_ids": list(agent.tool_ids),
                "source_hash": agent.source_hash,
            }
        )
        tool_profiles.update(agent.tool_ids)
    workflow_versions = [
        {
            "id": workflow.id,
            "version": workflow.version,
            "source_hash": workflow.source_hash,
        }
        for workflow in workflows
        if any(step.eval_id == spec.name for step in workflow.steps)
    ]
    return {
        "harness_ids": sorted(
            {item["harness_id"] for item in eval_compatibility_matrix(spec, registry)}
        ),
        "agents": compatible_agents,
        "models": sorted(
            {item for item in [spec.model, *(agent.model for agent in agents)] if item}
        ),
        "api_routes": [spec.api_mode.value],
        "tool_profile_ids": sorted(tool_profiles),
        "workflow_versions": workflow_versions,
    }


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
