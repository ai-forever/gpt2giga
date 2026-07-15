"""Durable Runs Center and stable run deep-link APIs."""

from __future__ import annotations

import base64
from datetime import datetime
import json
from typing import Any, Mapping

from fastapi import APIRouter, HTTPException, Query, Request

from gpt2giga_harness.runtime.models import (
    JobAttempt,
    JobAttemptStatus,
    JobStatus,
    RuntimeJob,
    attempt_to_dict,
    job_to_dict,
)
from gpt2giga_harness.runtime.policy import approval_request_to_dict
from gpt2giga_harness.runtime.store import (
    InvalidStateTransitionError,
    RuntimeCoordinationStore,
)
from gpt2giga_harness.sessions.models import (
    HarnessRun,
    HarnessStoredEvent,
    bundle_to_dict,
)
from gpt2giga_harness.sessions.store import (
    HarnessSessionStore,
    RunNotFoundError,
    SessionNotFoundError,
)
from gpt2giga_harness.ui.routers.schemas import RunBundleResponse


router = APIRouter()

_STATUS_GROUPS: dict[str, tuple[JobStatus, ...]] = {
    "queued": (JobStatus.QUEUED, JobStatus.RETRY_WAIT),
    "running": (JobStatus.RUNNING,),
    "blocked": (JobStatus.WAITING_INPUT,),
    "approval-needed": (JobStatus.WAITING_APPROVAL,),
    "approval_needed": (JobStatus.WAITING_APPROVAL,),
    "failed": (JobStatus.FAILED,),
    "canceled": (JobStatus.CANCELED,),
    "completed": (JobStatus.SUCCEEDED,),
    "succeeded": (JobStatus.SUCCEEDED,),
}
_HIDDEN_REASONING_MARKERS = ("reasoning", "chain_of_thought", "thinking", "thought")
_SAFE_RETRY_CLASSES = {"read_only", "safe_retry", "deterministic"}


@router.get("/api/runs")
async def list_runs_center(
    request: Request,
    status: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    harness_id: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    """Return a lightweight newest-first durable run page."""
    runtime_store = _runtime_store(request)
    if runtime_store is None:
        return {"runs": [], "next_cursor": None, "workers": []}
    try:
        statuses = _parse_status_filter(status)
        decoded_cursor = _decode_cursor(cursor) if cursor else None
        jobs, has_more = runtime_store.list_jobs_page(
            statuses=statuses,
            project_id=project_id,
            harness_id=harness_id,
            cursor=decoded_cursor,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session_store = _session_store(request)
    items = [_job_summary(runtime_store, session_store, job) for job in jobs]
    next_cursor = (
        _encode_cursor(jobs[-1].created_at, jobs[-1].id) if has_more and jobs else None
    )
    return {
        "runs": items,
        "next_cursor": next_cursor,
        "workers": [_worker_summary(worker) for worker in runtime_store.list_workers()],
    }


@router.get("/api/runs/{run_id}/trace")
async def run_trace(
    run_id: str,
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
) -> dict[str, Any]:
    """Return a bounded trace page without heavy event payloads."""
    session_store = _session_store(request)
    runtime_store = _runtime_store(request)
    try:
        run = session_store.get_run(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    job = runtime_store.find_job_for_run(run_id) if runtime_store else None
    attempts = runtime_store.list_attempts(job.id) if runtime_store and job else ()
    events = _job_events(session_store, run, attempts)
    if cursor:
        try:
            created_at, event_id = _decode_cursor(cursor)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        events = tuple(
            event
            for event in events
            if (event.created_at, event.id) < (created_at, event_id)
        )
    root_count = min(len(attempts), min(20, max(0, limit - 1)))
    visible_attempts = attempts[-root_count:] if root_count else ()
    event_limit = limit - len(visible_attempts)
    page = events[: event_limit + 1]
    has_more = len(page) > event_limit
    page = page[:event_limit]
    attempt_by_run = {attempt.run_id: attempt for attempt in attempts}
    nodes = [_attempt_trace_node(attempt) for attempt in visible_attempts]
    nodes.extend(
        _event_trace_node(event, attempt_by_run.get(event.run_id))
        for event in reversed(page)
    )
    return {
        "run_id": run_id,
        "job": job_to_dict(job) if job else None,
        "attempts": [attempt_to_dict(attempt) for attempt in attempts],
        "nodes": nodes,
        "next_cursor": (
            _encode_cursor(page[-1].created_at, page[-1].id)
            if has_more and page
            else None
        ),
        "live": bool(
            job
            and job.status
            not in {
                JobStatus.SUCCEEDED,
                JobStatus.FAILED,
                JobStatus.CANCELED,
            }
        ),
    }


@router.get("/api/runs/{run_id}/summary")
async def run_center_summary(run_id: str, request: Request) -> dict[str, Any]:
    """Resolve one durable run to its lightweight Runs Center summary."""
    session_store = _session_store(request)
    runtime_store = _runtime_store(request)
    try:
        session_store.get_run(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    job = runtime_store.find_job_for_run(run_id) if runtime_store else None
    if job is None or runtime_store is None:
        raise HTTPException(status_code=404, detail="Durable run not found")
    return {"run": _job_summary(runtime_store, session_store, job)}


@router.get("/api/runs/{run_id}/events/{event_id}")
async def run_event_payload(
    run_id: str,
    event_id: str,
    request: Request,
) -> dict[str, Any]:
    """Lazily fetch one redacted event payload for trace inspection."""
    session_store = _session_store(request)
    runtime_store = _runtime_store(request)
    try:
        run = session_store.get_run(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    job = runtime_store.find_job_for_run(run_id) if runtime_store else None
    attempts = runtime_store.list_attempts(job.id) if runtime_store and job else ()
    event = next(
        (
            item
            for item in _job_events(session_store, run, attempts, include_hidden=True)
            if item.id == event_id
        ),
        None,
    )
    if event is None:
        raise HTTPException(status_code=404, detail="Trace event not found")
    if _is_hidden_reasoning(event):
        return {"event_id": event.id, "hidden": True, "payload": {}}
    return {
        "event_id": event.id,
        "hidden": False,
        "payload": _strip_hidden_reasoning(event.payload),
    }


@router.post("/api/runs/{run_id}/retry")
async def retry_run(run_id: str, request: Request) -> dict[str, Any]:
    """Requeue the owning logical job when its latest attempt is retry-safe."""
    runtime_store = _runtime_store(request)
    if runtime_store is None:
        raise HTTPException(status_code=409, detail="Durable runtime is unavailable")
    try:
        _session_store(request).get_run(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    job = runtime_store.find_job_for_run(run_id)
    if job is None:
        raise HTTPException(status_code=409, detail="Run is not owned by a durable job")
    try:
        retried = runtime_store.retry_safe_job(job.id)
    except InvalidStateTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"job": job_to_dict(retried), "queued": True}


@router.get("/api/runs/{run_id}", response_model=RunBundleResponse)
async def run_bundle(run_id: str, request: Request) -> dict[str, Any]:
    """Resolve one run id to its complete persisted session bundle."""
    store = _session_store(request)
    try:
        run = store.get_run(run_id)
        payload = bundle_to_dict(store.get_session_bundle(run.session_id))
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    payload["selected_run_id"] = run.id
    return payload


def _runtime_store(request: Request) -> RuntimeCoordinationStore | None:
    return request.app.state.harness_runtime_store


def _session_store(request: Request) -> HarnessSessionStore:
    return request.app.state.harness_session_store


def _parse_status_filter(value: str | None) -> tuple[JobStatus, ...]:
    if not value:
        return ()
    parsed: list[JobStatus] = []
    for item in value.split(","):
        normalized = item.strip().lower()
        if not normalized:
            continue
        statuses = _STATUS_GROUPS.get(normalized)
        if statuses is None:
            raise ValueError(f"unknown run status filter: {item.strip()}")
        parsed.extend(status for status in statuses if status not in parsed)
    return tuple(parsed)


def _job_summary(
    runtime_store: RuntimeCoordinationStore,
    session_store: HarnessSessionStore,
    job: RuntimeJob,
) -> dict[str, Any]:
    attempts = runtime_store.list_attempts(job.id)
    attempt = attempts[-1] if attempts else None
    run_id = attempt.run_id if attempt is not None else job.initial_run_id
    run: HarnessRun | None = None
    session_title: str | None = None
    try:
        run = session_store.get_run(run_id)
        session_title = session_store.get_session(job.session_id).title
    except (RunNotFoundError, SessionNotFoundError):
        # Durable jobs may outlive pruned session history; summary data stays partial.
        pass
    status_group = _status_group(job.status)
    can_retry = bool(
        job.status is JobStatus.FAILED
        and attempt is not None
        and attempt.status in {JobAttemptStatus.FAILED, JobAttemptStatus.INTERRUPTED}
        and attempt.idempotency_class in _SAFE_RETRY_CLASSES
    )
    run_payload = _lightweight_run_summary(run) if run is not None else None
    artifacts = _artifact_summary(run)
    workflow = _workflow_team_summary(runtime_store, job)
    approvals = runtime_store.list_run_approval_requests(
        run_id=run_id,
        job_id=job.id,
    )
    return {
        "job": job_to_dict(job),
        "run": run_payload,
        "run_id": run_id,
        "session_id": job.session_id,
        "session_title": session_title or "Unavailable session",
        "status_group": status_group,
        "attempt_count": len(attempts),
        "retry_count": max(0, len(attempts) - 1),
        "worker_id": attempt.lease_owner if attempt else None,
        "duration_ms": _duration_ms(
            (attempt.started_at if attempt else None)
            or (run.started_at if run else None),
            (attempt.finished_at if attempt else None)
            or (run.finished_at if run else None),
        ),
        "metrics": _selected_metrics(run),
        "artifacts": artifacts,
        "artifact_inventory": _artifact_inventory(artifacts, workflow),
        "ownership": _ownership_summary(job, attempt),
        "approvals": [_approval_summary(item) for item in approvals],
        "workflow": workflow,
        "actions": {
            "open_task": f"/work/{job.session_id}",
            "open_run": f"/runs/{run_id}",
            "trace": f"/api/runs/{run_id}/trace",
            "cancel": f"/api/runs/{run_id}/cancel"
            if status_group in {"queued", "running", "blocked", "approval-needed"}
            else None,
            "retry": f"/api/runs/{run_id}/retry" if can_retry else None,
            "open_worktree": f"/api/runs/{run_id}/open-worktree"
            if artifacts["worktree"]
            else None,
            "inspect_artifact": f"/api/runs/{run_id}/pr"
            if artifacts["pr"]
            else (f"/api/runs/{run_id}/diff" if artifacts["diff"] else None),
        },
    }


def _workflow_team_summary(
    runtime_store: RuntimeCoordinationStore, job: RuntimeJob
) -> dict[str, Any] | None:
    if not job.workflow_id:
        return None
    from gpt2giga_harness.workflows import WorkflowRepository

    repository = WorkflowRepository(runtime_store)
    try:
        workflow = repository.get_run(job.workflow_id)
        steps = repository.list_steps(workflow.id)
    except KeyError:
        return None
    items: list[dict[str, Any]] = []
    active_steps: list[str] = []
    for step in steps:
        snapshot = dict(step.snapshot)
        outputs = dict(step.outputs)
        agent = outputs.get("agent")
        agent = dict(agent) if isinstance(agent, Mapping) else {}
        child_run_id = str(outputs.get("run_id") or "") or None
        if step.status in {"queued", "running", "waiting_approval"}:
            active_steps.append(step.step_id)
        items.append(
            {
                "id": step.step_id,
                "title": str(snapshot.get("title") or step.step_id),
                "kind": step.kind.value,
                "status": step.status,
                "depends_on": list(snapshot.get("depends_on") or ()),
                "agent": agent or None,
                "job_id": step.job_id,
                "run_id": child_run_id,
                "artifact_count": len(step.artifact_refs),
                "artifact_types": sorted(
                    {
                        str(item.get("type") or "")
                        for item in step.artifact_refs
                        if item.get("type")
                    }
                ),
                "summary_available": bool(outputs.get("summary")),
                "handoff_selected": bool(outputs.get("handoff_selected")),
                "actions": {
                    "open_task": f"/work/{workflow.session_id}",
                    "open_run": f"/runs/{child_run_id}" if child_run_id else None,
                    "choose": (
                        f"/api/workflow-runs/{workflow.id}/handoffs/{step.step_id}/choose"
                        if child_run_id
                        and any(
                            item.get("type") in {"patch", "diff"}
                            for item in step.artifact_refs
                        )
                        else None
                    ),
                    "apply": (
                        f"/api/runs/{child_run_id}/apply"
                        if child_run_id
                        and any(
                            item.get("type") == "patch" for item in step.artifact_refs
                        )
                        else None
                    ),
                    "discard": (
                        f"/api/workflow-runs/{workflow.id}/handoffs/{step.step_id}/discard"
                        if child_run_id
                        and any(
                            item.get("type") == "patch" for item in step.artifact_refs
                        )
                        else None
                    ),
                },
            }
        )
    completed = sum(
        item["status"] in {"succeeded", "failed", "canceled", "skipped"}
        for item in items
    )
    return {
        "id": workflow.id,
        "definition_id": workflow.workflow_id,
        "definition_hash": workflow.definition_hash,
        "status": workflow.status.value,
        "session_id": workflow.session_id,
        "max_concurrency": workflow.max_concurrency,
        "active_steps": active_steps,
        "completed_steps": completed,
        "total_steps": len(items),
        "steps": items,
    }


def _status_group(status: JobStatus) -> str:
    if status in {JobStatus.QUEUED, JobStatus.RETRY_WAIT}:
        return "queued"
    if status is JobStatus.RUNNING:
        return "running"
    if status is JobStatus.WAITING_INPUT:
        return "blocked"
    if status is JobStatus.WAITING_APPROVAL:
        return "approval-needed"
    if status is JobStatus.SUCCEEDED:
        return "completed"
    return status.value


def _artifact_summary(run: HarnessRun | None) -> dict[str, bool]:
    metadata = dict(run.metadata) if run is not None else {}
    execution = metadata.get("workspace_execution")
    execution = dict(execution) if isinstance(execution, Mapping) else {}
    pr_artifact = metadata.get("pr_artifact")
    return {
        "worktree": bool(execution.get("worktree_path")),
        "diff": bool(execution.get("patch") or metadata.get("diff")),
        "pr": isinstance(pr_artifact, Mapping),
    }


def _artifact_inventory(
    artifacts: Mapping[str, bool], workflow: Mapping[str, Any] | None
) -> list[dict[str, Any]]:
    """Return artifact presence and lineage without paths or captured content."""
    inventory = [
        {"type": artifact_type, "source": "run"}
        for artifact_type in ("worktree", "diff", "pr")
        if artifacts.get(artifact_type)
    ]
    if workflow:
        for step in workflow.get("steps", ()):
            if not isinstance(step, Mapping):
                continue
            for artifact_type in step.get("artifact_types", ()):
                item = {
                    "type": str(artifact_type),
                    "source": "workflow_step",
                    "step_id": str(step.get("id") or ""),
                }
                if item not in inventory:
                    inventory.append(item)
    return inventory


def _ownership_summary(job: RuntimeJob, attempt: JobAttempt | None) -> dict[str, Any]:
    """Project the current durable owner without process or task payloads."""
    return {
        "job_id": job.id,
        "job_status": job.status.value,
        "attempt_id": attempt.id if attempt else None,
        "attempt_number": attempt.attempt_number if attempt else None,
        "attempt_status": attempt.status.value if attempt else None,
        "worker_id": attempt.lease_owner if attempt else None,
        "heartbeat_at": attempt.heartbeat_at if attempt else None,
        "leased_until": attempt.leased_until if attempt else None,
    }


def _approval_summary(approval: Any) -> dict[str, Any]:
    """Return approval identity and state without its contextual preview."""
    payload = approval_request_to_dict(approval)
    return {
        key: payload[key]
        for key in (
            "id",
            "action",
            "status",
            "enforcement",
            "policy_source",
            "enforcement_owner",
            "decision",
            "expires_at",
            "decided_at",
            "created_at",
        )
    }


def _lightweight_run_summary(run: HarnessRun) -> dict[str, Any]:
    """Serialize list-safe run metadata without prompts, commands, or payloads."""
    return {
        "id": run.id,
        "session_id": run.session_id,
        "harness_id": run.harness_id,
        "status": run.status.value,
        "model": run.model,
        "api_mode": run.api_mode.value,
        "capability": run.capability.value,
        "mode": run.mode,
        "invocation_mode": run.invocation_mode.value,
        "workspace": run.workspace,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }


def _selected_metrics(run: HarnessRun | None) -> dict[str, Any]:
    if run is None:
        return {}
    metadata = dict(run.metadata)
    usage = metadata.get("usage")
    metrics: dict[str, Any] = {}
    if isinstance(usage, Mapping):
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            if key in usage and isinstance(usage[key], (int, float)):
                metrics[key] = usage[key]
    for key in ("score", "passed", "cost"):
        if key in metadata and isinstance(metadata[key], (bool, int, float)):
            metrics[key] = metadata[key]
    return metrics


def _worker_summary(worker: Any) -> dict[str, Any]:
    return {
        "id": worker.id,
        "status": worker.status,
        "heartbeat_at": worker.heartbeat_at,
    }


def _job_events(
    session_store: HarnessSessionStore,
    run: HarnessRun,
    attempts: tuple[JobAttempt, ...],
    *,
    include_hidden: bool = False,
) -> tuple[HarnessStoredEvent, ...]:
    run_ids = {run.id, *(attempt.run_id for attempt in attempts)}
    events: list[HarnessStoredEvent] = []
    for run_id in run_ids:
        try:
            events.extend(session_store.list_events(run.session_id, run_id=run_id))
        except SessionNotFoundError:
            continue
    if not include_hidden:
        events = [event for event in events if not _is_hidden_reasoning(event)]
    events.sort(key=lambda event: (event.created_at, event.id), reverse=True)
    return tuple(events)


def _attempt_trace_node(attempt: JobAttempt) -> dict[str, Any]:
    return {
        "id": f"attempt:{attempt.id}",
        "parent_id": None,
        "depth": 0,
        "attempt_id": attempt.id,
        "run_id": attempt.run_id,
        "kind": "agent",
        "status": attempt.status.value,
        "title": f"Attempt {attempt.attempt_number}",
        "created_at": attempt.created_at,
        "started_at": attempt.started_at,
        "finished_at": attempt.finished_at,
        "duration_ms": _duration_ms(attempt.started_at, attempt.finished_at),
        "worker_id": attempt.lease_owner,
        "has_payload": False,
    }


def _event_trace_node(
    event: HarnessStoredEvent,
    attempt: JobAttempt | None,
) -> dict[str, Any]:
    return {
        "id": f"event:{event.id}",
        "parent_id": (
            f"span:{event.parent_span_id}"
            if event.parent_span_id
            else (f"attempt:{attempt.id}" if attempt else None)
        ),
        "depth": 2 if event.parent_span_id else 1,
        "span_id": event.span_id,
        "event_id": event.id,
        "attempt_id": event.attempt_id,
        "run_id": event.run_id,
        "kind": event.span_kind or _infer_span_kind(event.type),
        "status": event.span_status or _infer_span_status(event.type),
        "title": event.message or event.type.replace("_", " ").title(),
        "event_type": event.type,
        "created_at": event.created_at,
        "sequence": event.sequence,
        "has_payload": bool(event.payload),
    }


def _infer_span_kind(event_type: str) -> str:
    normalized = event_type.lower()
    for marker, kind in (
        ("command", "command"),
        ("tool", "tool"),
        ("mcp", "mcp"),
        ("file", "file"),
        ("approval", "approval"),
        ("test", "test"),
        ("eval", "eval"),
        ("artifact", "artifact"),
    ):
        if marker in normalized:
            return kind
    return "event"


def _infer_span_status(event_type: str) -> str | None:
    normalized = event_type.lower()
    if "error" in normalized or "failed" in normalized:
        return "failed"
    if "cancel" in normalized:
        return "canceled"
    if "finished" in normalized or "completed" in normalized:
        return "succeeded"
    if "started" in normalized:
        return "running"
    return None


def _is_hidden_reasoning(event: HarnessStoredEvent) -> bool:
    haystack = f"{event.type} {event.span_kind or ''}".lower()
    return any(marker in haystack for marker in _HIDDEN_REASONING_MARKERS)


def _strip_hidden_reasoning(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _strip_hidden_reasoning(item)
            for key, item in value.items()
            if not any(
                marker in str(key).lower() for marker in _HIDDEN_REASONING_MARKERS
            )
        }
    if isinstance(value, (list, tuple)):
        return [_strip_hidden_reasoning(item) for item in value]
    return value


def _duration_ms(start: str | None, finish: str | None) -> int | None:
    if not start:
        return None
    try:
        started = datetime.fromisoformat(start.replace("Z", "+00:00"))
        ended = (
            datetime.fromisoformat(finish.replace("Z", "+00:00"))
            if finish
            else datetime.now(tz=started.tzinfo)
        )
    except ValueError:
        return None
    return max(0, int((ended - started).total_seconds() * 1000))


def _encode_cursor(created_at: str, item_id: str) -> str:
    raw = json.dumps([created_at, item_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(value: str) -> tuple[str, str]:
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded).decode())
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid cursor") from exc
    if (
        not isinstance(decoded, list)
        or len(decoded) != 2
        or not all(isinstance(item, str) and item for item in decoded)
    ):
        raise ValueError("invalid cursor")
    return decoded[0], decoded[1]
