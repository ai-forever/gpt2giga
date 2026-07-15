"""Versioned workflow definitions and durable execution coordination."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from string import Template
from typing import Any, Mapping, Sequence
from uuid import uuid4

import yaml

from gpt2giga_harness.agents import (
    agent_run_payload,
    apply_agent_run_overrides,
    load_agent_profile,
)
from gpt2giga_harness.arena import FilesystemHarnessArenaStore, queue_arena
from gpt2giga_harness.evals import (
    FilesystemHarnessEvalStore,
    load_eval_spec,
    queue_eval,
)
from gpt2giga_harness.project import HarnessProject
from gpt2giga_harness.runtime.models import ApprovalStatus, JobStatus, WorkflowStatus
from gpt2giga_harness.runtime.policy import (
    EnforcementLevel,
    PermissionAction,
    PolicyContext,
    PolicyDecision,
    PolicyResolution,
)
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore
from gpt2giga_harness.runtime.worker import DurableJobDispatcher
from gpt2giga_harness.session_runner import HarnessSessionRunner
from gpt2giga_harness.sessions.locking import exclusive_file_lock
from gpt2giga_harness.sessions.redaction import redact_for_storage
from gpt2giga_harness.sessions.store import title_from_prompt, utc_now
from gpt2giga_harness.safe_paths import resolve_operator_path, resolve_path_within
from gpt2giga_harness.worktrees import (
    RunDiffReview,
    WorktreeError,
    apply_run_diff,
    detect_overlapping_run_diffs,
    discard_run_worktree,
    prepare_run_diff_merge,
)


WORKFLOW_DIRECTORY = Path(".giga") / "workflows"
WORKFLOW_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
MAX_WORKFLOW_STEPS = 64
MAX_FAN_OUT = 16
MAX_HANDOFF_SUMMARY_CHARS = 8_000
MAX_HANDOFF_ARTIFACTS = 16
MAX_HANDOFF_PATCH_PREVIEW_CHARS = 6_000
HANDOFF_ARTIFACT_TYPES = frozenset(
    {
        "plan",
        "selected_files",
        "patch",
        "diff",
        "test_report",
        "review_findings",
        "pr_draft",
    }
)
TERMINAL_STEP_STATUSES = frozenset({"succeeded", "failed", "canceled", "skipped"})


class WorkflowStepKind(str, Enum):
    """Supported nodes in the canonical workflow IR."""

    AGENT = "agent"
    ARENA = "arena"
    EVAL = "eval"
    APPROVAL = "approval"
    TRANSFORM = "transform"
    JOIN = "join"


@dataclass(frozen=True)
class WorkflowBudgets:
    """Workflow-wide execution bounds."""

    max_concurrency: int = 1
    max_steps: int = MAX_WORKFLOW_STEPS
    timeout_seconds: int | None = None


@dataclass(frozen=True)
class WorkflowStep:
    """One immutable workflow step snapshot."""

    id: str
    kind: WorkflowStepKind
    title: str
    depends_on: tuple[str, ...] = ()
    condition: str = "on_success"
    agent_id: str | None = None
    prompt: str | None = None
    eval_id: str | None = None
    harness_ids: tuple[str, ...] = ()
    action: str | None = None
    transform: str | None = None
    select: tuple[str, ...] = ()
    artifact_types: tuple[str, ...] = ()
    retries: int = 0
    timeout_seconds: int | None = None
    max_fan_out: int = 1
    inputs: Mapping[str, Any] = field(default_factory=dict)
    output: str | None = None


@dataclass(frozen=True)
class WorkflowDefinition:
    """Validated versioned project workflow definition."""

    id: str
    title: str
    description: str
    schema_version: int
    version: str
    steps: tuple[WorkflowStep, ...]
    budgets: WorkflowBudgets
    inputs: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)
    source_path: str | None = None
    source_hash: str | None = None


@dataclass(frozen=True)
class WorkflowLoadError:
    """One invalid project workflow discovered independently."""

    path: str
    error: str


@dataclass(frozen=True)
class WorkflowRun:
    """Durable workflow coordination record."""

    id: str
    workflow_id: str
    definition_hash: str
    schema_version: int
    status: WorkflowStatus
    project_id: str
    project_root: str
    session_id: str
    definition: Mapping[str, Any]
    inputs: Mapping[str, Any]
    outputs: Mapping[str, Any]
    max_concurrency: int
    created_at: str
    updated_at: str
    cancel_requested_at: str | None = None
    error_summary: str | None = None
    finished_at: str | None = None


@dataclass(frozen=True)
class StepAttempt:
    """One durable attempt for a workflow step."""

    id: str
    workflow_run_id: str
    step_id: str
    attempt_number: int
    kind: WorkflowStepKind
    status: str
    snapshot: Mapping[str, Any]
    inputs: Mapping[str, Any]
    outputs: Mapping[str, Any]
    artifact_refs: tuple[Mapping[str, Any], ...]
    created_at: str
    updated_at: str
    job_id: str | None = None
    error_summary: str | None = None
    finished_at: str | None = None


def parse_workflow_definition(
    content: str, *, source_path: str | None = None, allow_unknown: bool = False
) -> WorkflowDefinition:
    """Parse one strict, bounded workflow YAML document."""
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ValueError("Invalid workflow YAML") from exc
    if not isinstance(data, Mapping):
        raise ValueError("Workflow must be a YAML mapping")
    allowed = {
        "id",
        "title",
        "description",
        "schema_version",
        "version",
        "inputs",
        "provenance",
        "budgets",
        "steps",
    }
    unknown = sorted(set(data) - allowed)
    if unknown and not allow_unknown:
        raise ValueError(f"Unknown workflow fields: {', '.join(unknown)}")
    workflow_id = _safe_id(data.get("id"), "workflow id")
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("Workflow steps must be a non-empty list")
    if len(raw_steps) > MAX_WORKFLOW_STEPS:
        raise ValueError(f"Workflow exceeds {MAX_WORKFLOW_STEPS} steps")
    steps = tuple(_parse_step(item, allow_unknown=allow_unknown) for item in raw_steps)
    _validate_graph(steps)
    budget_data = _mapping(data.get("budgets"))
    budgets = WorkflowBudgets(
        max_concurrency=_bounded_int(
            budget_data.get("max_concurrency", 1), "max_concurrency", 1, MAX_FAN_OUT
        ),
        max_steps=_bounded_int(
            budget_data.get("max_steps", MAX_WORKFLOW_STEPS),
            "max_steps",
            len(steps),
            MAX_WORKFLOW_STEPS,
        ),
        timeout_seconds=_optional_positive_int(
            budget_data.get("timeout_seconds"), "timeout_seconds"
        ),
    )
    if len(steps) > budgets.max_steps:
        raise ValueError("Workflow step count exceeds its max_steps budget")
    safe_inputs = redact_for_storage(_mapping(data.get("inputs")))
    safe_provenance = redact_for_storage(_mapping(data.get("provenance")))
    return WorkflowDefinition(
        id=workflow_id,
        title=_required_text(data.get("title"), "workflow title"),
        description=str(data.get("description") or "").strip(),
        schema_version=_bounded_int(
            data.get("schema_version", 1), "schema_version", 1, 1
        ),
        version=_required_text(data.get("version"), "workflow version"),
        steps=steps,
        budgets=budgets,
        inputs=dict(safe_inputs) if isinstance(safe_inputs, Mapping) else {},
        provenance=(
            dict(safe_provenance) if isinstance(safe_provenance, Mapping) else {}
        ),
        source_path=source_path,
        source_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


def discover_workflows(
    project_root: str | Path,
) -> tuple[tuple[WorkflowDefinition, ...], tuple[WorkflowLoadError, ...]]:
    """Discover project workflows without hiding independent parse failures."""
    root = resolve_operator_path(project_root)
    directory = root / WORKFLOW_DIRECTORY
    definitions: list[WorkflowDefinition] = []
    errors: list[WorkflowLoadError] = []
    for path in sorted((*directory.glob("*.yaml"), *directory.glob("*.yml"))):
        relative = path.relative_to(root).as_posix()
        try:
            definition = parse_workflow_definition(
                path.read_text(encoding="utf-8"),
                source_path=relative,
                allow_unknown=True,
            )
            if path.stem != definition.id:
                raise ValueError("Workflow filename must match its id")
            definitions.append(definition)
        except (OSError, ValueError) as exc:
            errors.append(WorkflowLoadError(relative, str(exc)))
    return tuple(definitions), tuple(errors)


def load_workflow(project_root: str | Path, workflow_id: str) -> WorkflowDefinition:
    """Load one safe project workflow id."""
    safe_id = _safe_id(workflow_id, "workflow id")
    root = resolve_operator_path(project_root)
    path = resolve_path_within(root, WORKFLOW_DIRECTORY / f"{safe_id}.yaml")
    try:
        definition = parse_workflow_definition(
            path.read_text(encoding="utf-8"),
            source_path=path.relative_to(root).as_posix(),
            allow_unknown=True,
        )
    except FileNotFoundError as exc:
        raise KeyError(safe_id) from exc
    if definition.id != safe_id:
        raise ValueError("Workflow filename must match its id")
    return definition


def workflow_definition_to_dict(definition: WorkflowDefinition) -> dict[str, Any]:
    """Serialize an immutable definition or run snapshot."""
    payload = asdict(definition)
    for step in payload["steps"]:
        step["kind"] = (
            step["kind"].value if isinstance(step["kind"], Enum) else step["kind"]
        )
    return dict(redact_for_storage(payload))


def workflow_plan(definition: WorkflowDefinition) -> dict[str, Any]:
    """Return deterministic dependency levels for dry-run inspection."""
    levels: list[list[str]] = []
    placed: set[str] = set()
    while len(placed) < len(definition.steps):
        ready = [
            step.id
            for step in definition.steps
            if step.id not in placed and set(step.depends_on) <= placed
        ]
        if not ready:
            raise ValueError("Workflow dependency graph contains a cycle")
        levels.append(ready)
        placed.update(ready)
    return {
        "workflow_id": definition.id,
        "definition_hash": definition.source_hash,
        "version": definition.version,
        "levels": levels,
        "max_concurrency": definition.budgets.max_concurrency,
        "step_count": len(definition.steps),
    }


class WorkflowRepository:
    """SQLite-backed workflow coordination repository."""

    def __init__(self, runtime_store: RuntimeCoordinationStore) -> None:
        self.runtime_store = runtime_store

    def create_run(
        self,
        definition: WorkflowDefinition,
        project: HarnessProject,
        session_id: str,
        inputs: Mapping[str, Any],
    ) -> WorkflowRun:
        """Persist a run and immutable initial step snapshots atomically."""
        run_id = f"workflow_{uuid4().hex}"
        now = utc_now()
        definition_payload = workflow_definition_to_dict(definition)
        with self.runtime_store._connect() as connection:  # noqa: SLF001
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    INSERT INTO workflow_runs (
                        id, workflow_id, definition_hash, schema_version, status,
                        project_id, project_root, session_id, definition_json,
                        inputs_json, max_concurrency, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        definition.id,
                        definition.source_hash or "",
                        definition.schema_version,
                        WorkflowStatus.QUEUED.value,
                        project.id,
                        project.root,
                        session_id,
                        _json(definition_payload),
                        _json(inputs),
                        definition.budgets.max_concurrency,
                        now,
                        now,
                    ),
                )
                for step in definition.steps:
                    connection.execute(
                        """
                        INSERT INTO workflow_step_attempts (
                            id, workflow_run_id, step_id, attempt_number, kind,
                            status, snapshot_json, inputs_json, created_at, updated_at
                        ) VALUES (?, ?, ?, 1, ?, 'pending', ?, '{}', ?, ?)
                        """,
                        (
                            f"step_{uuid4().hex}",
                            run_id,
                            step.id,
                            step.kind.value,
                            _json(_step_to_dict(step)),
                            now,
                            now,
                        ),
                    )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> WorkflowRun:
        """Return one workflow run."""
        with self.runtime_store._connect() as connection:  # noqa: SLF001
            row = connection.execute(
                "SELECT * FROM workflow_runs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return _workflow_run_from_row(row)

    def list_runs(
        self,
        *,
        workflow_id: str | None = None,
        project_id: str | None = None,
    ) -> tuple[WorkflowRun, ...]:
        """List newest workflow runs."""
        with self.runtime_store._connect() as connection:  # noqa: SLF001
            if workflow_id and project_id:
                rows = connection.execute(
                    """
                    SELECT * FROM workflow_runs
                    WHERE workflow_id = ? AND project_id = ?
                    ORDER BY created_at DESC
                    """,
                    (workflow_id, project_id),
                ).fetchall()
            elif workflow_id:
                rows = connection.execute(
                    "SELECT * FROM workflow_runs WHERE workflow_id = ? ORDER BY created_at DESC",
                    (workflow_id,),
                ).fetchall()
            elif project_id:
                rows = connection.execute(
                    "SELECT * FROM workflow_runs WHERE project_id = ? ORDER BY created_at DESC",
                    (project_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM workflow_runs ORDER BY created_at DESC"
                ).fetchall()
        return tuple(_workflow_run_from_row(row) for row in rows)

    def list_steps(self, run_id: str) -> tuple[StepAttempt, ...]:
        """Return stable definition order step attempts."""
        run = self.get_run(run_id)
        order = {
            str(item["id"]): index
            for index, item in enumerate(run.definition.get("steps", ()))
            if isinstance(item, Mapping)
        }
        with self.runtime_store._connect() as connection:  # noqa: SLF001
            rows = connection.execute(
                "SELECT * FROM workflow_step_attempts WHERE workflow_run_id = ?",
                (run_id,),
            ).fetchall()
        attempts = [_step_attempt_from_row(row) for row in rows]
        attempts.sort(
            key=lambda item: (order.get(item.step_id, len(order)), item.attempt_number)
        )
        return tuple(attempts)

    def update_step(
        self,
        attempt_id: str,
        *,
        status: str,
        job_id: str | None = None,
        inputs: Mapping[str, Any] | None = None,
        outputs: Mapping[str, Any] | None = None,
        artifact_refs: Sequence[Mapping[str, Any]] | None = None,
        error_summary: str | None = None,
    ) -> StepAttempt:
        """Update one step projection under an immediate transaction."""
        now = utc_now()
        terminal = now if status in TERMINAL_STEP_STATUSES else None
        with self.runtime_store._connect() as connection:  # noqa: SLF001
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT * FROM workflow_step_attempts WHERE id = ?", (attempt_id,)
                ).fetchone()
                if row is None:
                    raise KeyError(attempt_id)
                current = _step_attempt_from_row(row)
                connection.execute(
                    """
                    UPDATE workflow_step_attempts SET status = ?, job_id = ?,
                        inputs_json = ?, outputs_json = ?, artifact_refs_json = ?,
                        error_summary = ?, updated_at = ?, finished_at = ?
                    WHERE id = ?
                    """,
                    (
                        status,
                        job_id if job_id is not None else current.job_id,
                        _json(inputs if inputs is not None else current.inputs),
                        _json(outputs if outputs is not None else current.outputs),
                        _json(
                            artifact_refs
                            if artifact_refs is not None
                            else current.artifact_refs
                        ),
                        error_summary,
                        now,
                        terminal,
                        attempt_id,
                    ),
                )
                updated = connection.execute(
                    "SELECT * FROM workflow_step_attempts WHERE id = ?", (attempt_id,)
                ).fetchone()
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return _step_attempt_from_row(updated)

    def update_run(
        self,
        run_id: str,
        status: WorkflowStatus,
        *,
        outputs: Mapping[str, Any] | None = None,
        error_summary: str | None = None,
        request_cancel: bool = False,
    ) -> WorkflowRun:
        """Update workflow lifecycle state."""
        now = utc_now()
        finished = (
            now
            if status
            in {
                WorkflowStatus.SUCCEEDED,
                WorkflowStatus.FAILED,
                WorkflowStatus.CANCELED,
            }
            else None
        )
        with self.runtime_store._connect() as connection:  # noqa: SLF001
            connection.execute(
                """
                UPDATE workflow_runs SET status = ?, outputs_json = COALESCE(?, outputs_json),
                    error_summary = ?, cancel_requested_at = CASE WHEN ? THEN ? ELSE cancel_requested_at END,
                    updated_at = ?, finished_at = ? WHERE id = ?
                """,
                (
                    status.value,
                    _json(outputs) if outputs is not None else None,
                    error_summary,
                    1 if request_cancel else 0,
                    now,
                    now,
                    finished,
                    run_id,
                ),
            )
        return self.get_run(run_id)


class WorkflowCoordinator:
    """Advance workflow DAGs by projecting durable child job state."""

    def __init__(
        self,
        *,
        project: HarnessProject,
        runtime_store: RuntimeCoordinationStore,
        runner: HarnessSessionRunner,
        dispatcher: DurableJobDispatcher,
        origin: str = "manual",
        schedule_id: str | None = None,
    ) -> None:
        self.project = project
        self.runtime_store = runtime_store
        self.runner = runner
        self.dispatcher = dispatcher
        self.origin = origin
        self.schedule_id = schedule_id
        self.repository = WorkflowRepository(runtime_store)

    def start(
        self,
        definition: WorkflowDefinition,
        *,
        inputs: Mapping[str, Any] | None = None,
        prompt: str | None = None,
    ) -> WorkflowRun:
        """Create and advance one immutable workflow definition snapshot."""
        for step in definition.steps:
            if step.kind is WorkflowStepKind.AGENT:
                load_agent_profile(self.project.root, step.agent_id or "")
        effective_inputs = dict(definition.inputs)
        effective_inputs.update(dict(inputs or {}))
        if prompt is not None:
            effective_inputs["prompt"] = prompt
        session = self.runner.create_session(
            title=title_from_prompt(prompt or definition.title),
            workspace=self.project.root,
            default_harness_id="echo",
            default_mode="read",
        )
        run = self.repository.create_run(
            definition, self.project, session.id, effective_inputs
        )
        return self.advance(run.id)

    def advance(self, run_id: str) -> WorkflowRun:
        """Synchronize children, run safe local nodes, and queue ready work."""
        lock = Path(self.runtime_store.data_dir) / "runtime" / "workflow_locks" / run_id
        with exclusive_file_lock(lock):
            run = self.repository.get_run(run_id)
            if run.status in {
                WorkflowStatus.SUCCEEDED,
                WorkflowStatus.FAILED,
                WorkflowStatus.CANCELED,
            }:
                return run
            attempts = list(self.repository.list_steps(run_id))
            attempts = [self._sync_child(run, attempt) for attempt in attempts]
            if run.cancel_requested_at:
                return self._cancel_children(run, attempts)
            active = sum(
                item.status in {"queued", "running", "waiting_approval"}
                for item in attempts
            )
            by_id = {item.step_id: item for item in attempts}
            for attempt in attempts:
                if attempt.status != "pending" or active >= run.max_concurrency:
                    continue
                step = _step_from_snapshot(attempt.snapshot)
                dependencies = [by_id[item] for item in step.depends_on]
                if not dependencies or all(
                    item.status in TERMINAL_STEP_STATUSES for item in dependencies
                ):
                    if not _condition_matches(step.condition, dependencies):
                        by_id[step.id] = self.repository.update_step(
                            attempt.id, status="skipped"
                        )
                        continue
                    updated = self._start_step(run, step, attempt, dependencies)
                    by_id[step.id] = updated
                    active += updated.status in {
                        "queued",
                        "running",
                        "waiting_approval",
                    }
            attempts = list(self.repository.list_steps(run_id))
            statuses = {item.status for item in attempts}
            outputs = {
                item.step_id: dict(item.outputs) for item in attempts if item.outputs
            }
            outputs.update(
                {
                    key: value
                    for key, value in run.outputs.items()
                    if str(key).startswith("_")
                }
            )
            if statuses <= {"succeeded", "skipped"}:
                return self.repository.update_run(
                    run_id, WorkflowStatus.SUCCEEDED, outputs=outputs
                )
            failed = [item for item in attempts if item.status == "failed"]
            pending = [item for item in attempts if item.status == "pending"]
            active_statuses = {"queued", "running", "waiting_approval"}
            if (
                failed
                and statuses.isdisjoint(active_statuses)
                and not any(
                    _step_from_snapshot(item.snapshot).condition
                    in {"on_failure", "always"}
                    for item in pending
                )
            ):
                return self.repository.update_run(
                    run_id,
                    WorkflowStatus.FAILED,
                    outputs=outputs,
                    error_summary=failed[0].error_summary
                    or f"step {failed[0].step_id} failed",
                )
            status = (
                WorkflowStatus.WAITING_APPROVAL
                if "waiting_approval" in statuses
                else WorkflowStatus.RUNNING
            )
            return self.repository.update_run(run_id, status, outputs=outputs)

    def cancel(self, run_id: str) -> WorkflowRun:
        """Persist cancellation and propagate it to every active child job."""
        run = self.repository.update_run(
            run_id, WorkflowStatus.CANCELED, request_cancel=True
        )
        return self._cancel_children(run, self.repository.list_steps(run_id))

    def _sync_child(self, run: WorkflowRun, attempt: StepAttempt) -> StepAttempt:
        if attempt.status == "waiting_approval":
            approval_id = str(attempt.outputs.get("approval_id") or "")
            if not approval_id:
                return attempt
            approval = self.runtime_store.get_approval_request(approval_id)
            if approval.status is ApprovalStatus.APPROVED:
                return self.repository.update_step(
                    attempt.id,
                    status="succeeded",
                    outputs={"approved": True, "approval_id": approval_id},
                )
            if approval.status in {
                ApprovalStatus.DENIED,
                ApprovalStatus.EXPIRED,
                ApprovalStatus.CANCELED,
            }:
                return self.repository.update_step(
                    attempt.id,
                    status="failed",
                    outputs={"approved": False, "approval_id": approval_id},
                    error_summary=f"approval {approval.status.value}",
                )
            return attempt
        if attempt.job_id:
            job = self.runtime_store.get_job(attempt.job_id)
            mapped = {
                JobStatus.QUEUED: "queued",
                JobStatus.RETRY_WAIT: "queued",
                JobStatus.RUNNING: "running",
                JobStatus.WAITING_APPROVAL: "waiting_approval",
                JobStatus.WAITING_INPUT: "queued",
                JobStatus.SUCCEEDED: "succeeded",
                JobStatus.FAILED: "failed",
                JobStatus.CANCELED: "canceled",
            }[job.status]
            if mapped == attempt.status:
                return attempt
            output: dict[str, Any] = dict(attempt.outputs)
            artifacts: list[Mapping[str, Any]] = list(attempt.artifact_refs)
            if mapped in TERMINAL_STEP_STATUSES:
                run_id = self.runtime_store.list_attempts(job.id)[-1].run_id
                output["run_id"] = run_id
                output["job_id"] = job.id
                summary = self._child_summary(run.session_id, run_id)
                if summary:
                    output["summary"] = summary
                run_artifact = {"type": "harness_run", "id": run_id}
                if run_artifact not in artifacts:
                    artifacts.append(run_artifact)
                child_run = self.runner.store.get_run(run_id)
                for artifact in _typed_run_artifacts(child_run, output):
                    if artifact not in artifacts:
                        artifacts.append(artifact)
                output["artifacts"] = [
                    dict(item) for item in artifacts[:MAX_HANDOFF_ARTIFACTS]
                ]
            return self.repository.update_step(
                attempt.id,
                status=mapped,
                outputs=output,
                artifact_refs=artifacts,
                error_summary=job.error_summary,
            )
        if attempt.kind is WorkflowStepKind.ARENA and attempt.status == "running":
            arena_id = str(attempt.outputs.get("arena_id") or "")
            arena = FilesystemHarnessArenaStore(self.runtime_store.data_dir).get(
                arena_id
            )
            if arena.status != "running":
                return self.repository.update_step(
                    attempt.id,
                    status="succeeded" if arena.status == "succeeded" else "failed",
                    outputs={**attempt.outputs, "status": arena.status},
                    artifact_refs=({"type": "arena", "id": arena.id},),
                    error_summary=None
                    if arena.status == "succeeded"
                    else "arena failed",
                )
        if attempt.kind is WorkflowStepKind.EVAL and attempt.status == "running":
            eval_id = str(attempt.outputs.get("eval_run_id") or "")
            eval_run = FilesystemHarnessEvalStore(self.runtime_store.data_dir).get_any(
                eval_id
            )
            if eval_run.status != "running":
                return self.repository.update_step(
                    attempt.id,
                    status="succeeded" if eval_run.status == "passed" else "failed",
                    outputs={
                        **attempt.outputs,
                        "status": eval_run.status,
                        "summary": eval_run.summary,
                    },
                    artifact_refs=({"type": "eval", "id": eval_run.id},),
                    error_summary=None
                    if eval_run.status == "passed"
                    else "eval failed",
                )
        return attempt

    def _start_step(
        self,
        run: WorkflowRun,
        step: WorkflowStep,
        attempt: StepAttempt,
        dependencies: Sequence[StepAttempt],
    ) -> StepAttempt:
        resolved_inputs = _step_inputs(run.inputs, step, dependencies)
        if step.kind is WorkflowStepKind.TRANSFORM:
            output = _safe_transform(step, resolved_inputs)
            return self.repository.update_step(
                attempt.id, status="succeeded", inputs=resolved_inputs, outputs=output
            )
        if step.kind is WorkflowStepKind.JOIN:
            output = {item.step_id: dict(item.outputs) for item in dependencies}
            return self.repository.update_step(
                attempt.id, status="succeeded", inputs=resolved_inputs, outputs=output
            )
        if step.kind is WorkflowStepKind.APPROVAL:
            action = PermissionAction(
                step.action or PermissionAction.EXTERNAL_WRITE.value
            )
            resolution = PolicyResolution(
                action=action,
                decision=PolicyDecision.ASK,
                enforcement=EnforcementLevel.ENFORCED_BY_HARNESS,
                policy_source=f"workflow:{run.workflow_id}:{step.id}",
            )
            approval = self.runtime_store.create_approval_request(
                resolution,
                PolicyContext(
                    project_id=run.project_id,
                    session_id=run.session_id,
                    reason=step.prompt or f"Approve workflow step {step.title}.",
                    preview={
                        "workflow_run_id": run.id,
                        "step_id": step.id,
                        **resolved_inputs,
                    },
                ),
            )
            return self.repository.update_step(
                attempt.id,
                status="waiting_approval",
                inputs=resolved_inputs,
                outputs={"approval_id": approval.id},
            )
        if step.kind is WorkflowStepKind.AGENT:
            profile = load_agent_profile(self.project.root, step.agent_id or "")
            prompt = _render_step_prompt(step, run.inputs, dependencies)
            payload = agent_run_payload(
                profile,
                prompt,
                workspace=self.project.root,
                harness=self.runner.registry.get(profile.harness_id),
                default_timeout_seconds=self.runner.config.timeout_seconds,
            )
            if profile.mode == "edit":
                # Agent teams never share the source checkout or another agent's
                # worktree, even if a profile was authored with a weaker policy.
                payload["workspace_policy"] = "worktree"
            payload.update(
                {
                    "workflow_id": run.id,
                    "workflow_version": run.definition_hash,
                    "workflow_step_id": step.id,
                    "max_attempts": max(
                        step.retries + 1, payload.get("max_attempts") or 1
                    ),
                    "timeout_seconds": step.timeout_seconds
                    or payload.get("timeout_seconds"),
                }
            )
            if self.origin == "scheduled":
                payload.update(
                    {
                        "permission_profile": "unattended",
                        "schedule_id": self.schedule_id,
                        "workspace_policy": "worktree",
                    }
                )
            payload = apply_agent_run_overrides(
                payload,
                workspace_policy=str(payload.get("workspace_policy") or "auto"),
                permission_profile=str(
                    payload.get("permission_profile") or "interactive"
                ),
                timeout_seconds=payload.get("timeout_seconds"),
                max_attempts=int(payload.get("max_attempts") or 1),
            )
            submission = self.dispatcher.submit(
                run.session_id,
                payload,
                idempotency_key=f"workflow:{run.id}:{step.id}:1",
                origin=self.origin,
            )
            return self.repository.update_step(
                attempt.id,
                status=submission.job.status.value,
                job_id=submission.job.id,
                inputs=resolved_inputs,
                outputs={
                    "run_id": submission.queued.run.id,
                    "agent": {
                        "id": profile.id,
                        "title": profile.title,
                        "harness_id": profile.harness_id,
                        "model": profile.model,
                        "reasoning_effort": profile.reasoning_effort,
                        "mode": profile.mode,
                        "permission_profile": profile.permission_profile,
                        "tool_ids": list(profile.tool_ids),
                        "budgets": asdict(profile.budgets),
                        "profile_hash": profile.source_hash,
                        "workspace_policy": "worktree"
                        if profile.mode == "edit"
                        else profile.workspace_policy,
                    },
                },
            )
        if step.kind is WorkflowStepKind.ARENA:
            arena = queue_arena(
                runner=self.runner,
                dispatcher=self.dispatcher,
                arena_store=FilesystemHarnessArenaStore(self.runtime_store.data_dir),
                payload={
                    "prompt": _render_step_prompt(step, run.inputs, dependencies),
                    "harness_ids": list(step.harness_ids),
                    "workspace": self.project.root,
                    "mode": "read",
                    "extra": {"workflow_run_id": run.id, "workflow_step_id": step.id},
                },
                session_id=run.session_id,
            )
            for child in arena.child_runs:
                if child.run_id:
                    job = self.runtime_store.find_job_for_run(child.run_id)
                    if job is not None:
                        self.runtime_store.link_job_workflow(
                            job.id,
                            workflow_id=run.id,
                            workflow_version=run.definition_hash,
                        )
            return self.repository.update_step(
                attempt.id,
                status="running",
                inputs=resolved_inputs,
                outputs={"arena_id": arena.id},
            )
        spec = load_eval_spec(self.project.root, step.eval_id or "")
        eval_run = queue_eval(
            runner=self.runner,
            dispatcher=self.dispatcher,
            eval_store=FilesystemHarnessEvalStore(self.runtime_store.data_dir),
            project=self.project,
            spec=spec,
            harness_ids=step.harness_ids,
        )
        for result in eval_run.results:
            if result.run_id:
                job = self.runtime_store.find_job_for_run(result.run_id)
                if job is not None:
                    self.runtime_store.link_job_workflow(
                        job.id,
                        workflow_id=run.id,
                        workflow_version=run.definition_hash,
                    )
        return self.repository.update_step(
            attempt.id,
            status="running",
            inputs=resolved_inputs,
            outputs={"eval_run_id": eval_run.id},
        )

    def _cancel_children(
        self, run: WorkflowRun, attempts: Sequence[StepAttempt]
    ) -> WorkflowRun:
        for job in self.runtime_store.list_jobs():
            if job.workflow_id == run.id and job.status not in {
                JobStatus.SUCCEEDED,
                JobStatus.FAILED,
                JobStatus.CANCELED,
            }:
                self.runtime_store.request_cancel(job.id)
        for attempt in attempts:
            if attempt.status not in TERMINAL_STEP_STATUSES:
                self.repository.update_step(attempt.id, status="canceled")
        return self.repository.update_run(
            run.id, WorkflowStatus.CANCELED, request_cancel=True
        )

    def _child_summary(self, session_id: str, run_id: str) -> str | None:
        messages = [
            message.content.strip()
            for message in self.runner.store.list_messages(session_id)
            if message.run_id == run_id
            and message.role == "assistant"
            and message.content.strip()
        ]
        if not messages:
            return None
        summary = messages[-1]
        if len(summary) > MAX_HANDOFF_SUMMARY_CHARS:
            summary = summary[: MAX_HANDOFF_SUMMARY_CHARS - 1].rstrip() + "…"
        redacted = redact_for_storage(summary)
        return str(redacted) if redacted else None


class WorkflowHandoffManager:
    """Coordinate explicit patch selection, merge, apply, and cleanup actions."""

    def __init__(self, coordinator: WorkflowCoordinator) -> None:
        self.coordinator = coordinator
        self.repository = coordinator.repository

    def status(self, run_id: str) -> dict[str, Any]:
        """Return selected edit steps, file conflicts, and merge state."""
        run = self.repository.get_run(run_id)
        steps = self.repository.list_steps(run_id)
        candidates: list[dict[str, Any]] = []
        selected_metadata: dict[str, Mapping[str, Any]] = {}
        for step in steps:
            child_run_id = str(step.outputs.get("run_id") or "")
            if not child_run_id:
                continue
            child_run = self.coordinator.runner.store.get_run(child_run_id)
            execution = _mapping(child_run.metadata.get("workspace_execution"))
            if execution.get("policy") != "worktree":
                continue
            selected = bool(step.outputs.get("handoff_selected"))
            if selected:
                selected_metadata[child_run_id] = child_run.metadata
            candidates.append(
                {
                    "step_id": step.step_id,
                    "run_id": child_run_id,
                    "selected": selected,
                    "changed_files": list(execution.get("changed_files") or ()),
                    "untracked_files": list(execution.get("untracked_files") or ()),
                    "retained": bool(
                        execution.get("worktree_path")
                        and not execution.get("discarded_at")
                    ),
                    "applied": bool(execution.get("applied_at")),
                    "actions": {
                        "choose": f"/api/workflow-runs/{run_id}/handoffs/{step.step_id}/choose",
                        "apply": f"/api/runs/{child_run_id}/apply",
                        "discard": f"/api/workflow-runs/{run_id}/handoffs/{step.step_id}/discard",
                    },
                }
            )
        return {
            "workflow_run_id": run_id,
            "candidates": candidates,
            "conflicts": list(detect_overlapping_run_diffs(selected_metadata)),
            "merge_queue": dict(_mapping(run.outputs.get("_merge_queue"))),
            "actions": {
                "prepare_merge": f"/api/workflow-runs/{run_id}/merge-queue",
                "apply_merge": f"/api/workflow-runs/{run_id}/merge-queue/apply",
            },
        }

    def choose(self, run_id: str, step_id: str, *, selected: bool) -> dict[str, Any]:
        """Choose or remove one retained edit patch from the merge queue."""
        step = self._edit_step(run_id, step_id)
        outputs = {**dict(step.outputs), "handoff_selected": selected}
        self.repository.update_step(step.id, status=step.status, outputs=outputs)
        run = self.repository.get_run(run_id)
        if run.outputs.get("_merge_queue"):
            self.repository.update_run(
                run_id,
                run.status,
                outputs={
                    **dict(run.outputs),
                    "_merge_queue": {
                        "stale": True,
                        "reason": "selection changed",
                    },
                },
            )
        return self.status(run_id)

    def prepare_merge(self, run_id: str) -> dict[str, Any]:
        """Prepare a combined patch without changing the source checkout."""
        run = self.repository.get_run(run_id)
        selected: dict[str, Mapping[str, Any]] = {}
        for step in self.repository.list_steps(run_id):
            if not step.outputs.get("handoff_selected"):
                continue
            child_run_id = str(step.outputs.get("run_id") or "")
            if child_run_id:
                selected[child_run_id] = self.coordinator.runner.store.get_run(
                    child_run_id
                ).metadata
        merged = prepare_run_diff_merge(
            selected,
            data_dir=self.coordinator.runtime_store.data_dir,
            session_id=run.session_id,
            merge_id=f"merge_{run.id}",
        )
        state = {
            "status": "prepared",
            "workspace_execution": merged,
            "source_run_ids": list(merged["source_run_ids"]),
            "changed_files": list(merged.get("changed_files") or ()),
            "prepared_at": merged["prepared_at"],
        }
        self.repository.update_run(
            run.id,
            run.status,
            outputs={**dict(run.outputs), "_merge_queue": state},
        )
        return self.status(run_id)

    def apply_merge(self, run_id: str, *, review: RunDiffReview) -> dict[str, Any]:
        """Apply a previously prepared combined patch to a clean source checkout."""
        run = self.repository.get_run(run_id)
        queue = _mapping(run.outputs.get("_merge_queue"))
        execution = _mapping(queue.get("workspace_execution"))
        if queue.get("status") != "prepared" or not execution:
            raise WorktreeError("Merge queue is not prepared.")
        applied = apply_run_diff(
            {"workspace_execution": execution},
            review=review,
        )
        state = {**dict(queue), "status": "applied", "workspace_execution": applied}
        self.repository.update_run(
            run.id,
            run.status,
            outputs={**dict(run.outputs), "_merge_queue": state},
        )
        return self.status(run_id)

    def discard(self, run_id: str, step_id: str) -> dict[str, Any]:
        """Discard one retained child worktree without applying its patch."""
        step = self._edit_step(run_id, step_id)
        child_run = self.coordinator.runner.store.get_run(
            str(step.outputs.get("run_id") or "")
        )
        execution = discard_run_worktree(child_run.metadata)
        self.coordinator.runner.store.update_run(
            child_run.id,
            metadata={**dict(child_run.metadata), "workspace_execution": execution},
        )
        self.repository.update_step(
            step.id,
            status=step.status,
            outputs={**dict(step.outputs), "handoff_selected": False},
        )
        return self.status(run_id)

    def _edit_step(self, run_id: str, step_id: str) -> StepAttempt:
        for step in self.repository.list_steps(run_id):
            if step.step_id != step_id:
                continue
            child_run_id = str(step.outputs.get("run_id") or "")
            if not child_run_id:
                break
            child_run = self.coordinator.runner.store.get_run(child_run_id)
            execution = _mapping(child_run.metadata.get("workspace_execution"))
            if execution.get("policy") == "worktree":
                return step
            break
        raise WorktreeError(f"Workflow step {step_id} has no retained edit patch.")


def _typed_run_artifacts(
    child_run: Any, outputs: Mapping[str, Any]
) -> tuple[dict[str, Any], ...]:
    """Project one child run into the strict typed handoff artifact vocabulary."""
    metadata = _mapping(child_run.metadata)
    execution = _mapping(metadata.get("workspace_execution"))
    agent = _mapping(outputs.get("agent"))
    summary = str(outputs.get("summary") or "")
    artifacts: list[dict[str, Any]] = []
    mode = str(agent.get("mode") or "")
    expected = str(
        _mapping(metadata.get("agent_profile_snapshot")).get("expected_artifact") or ""
    )
    if mode == "plan" or expected == "plan":
        artifacts.append({"type": "plan", "run_id": child_run.id, "preview": summary})
    if mode == "read" or expected == "review_findings":
        artifact_type = (
            "test_report" if expected == "test_report" else "review_findings"
        )
        artifacts.append(
            {"type": artifact_type, "run_id": child_run.id, "preview": summary}
        )
    changed_files = tuple(
        dict.fromkeys(
            str(item)
            for item in (
                *(execution.get("changed_files") or ()),
                *(execution.get("untracked_files") or ()),
            )
        )
    )
    patch = str(execution.get("patch") or "")
    if changed_files:
        artifacts.append(
            {
                "type": "selected_files",
                "run_id": child_run.id,
                "paths": list(changed_files),
            }
        )
    if patch:
        preview = patch[:MAX_HANDOFF_PATCH_PREVIEW_CHARS]
        for artifact_type in ("patch", "diff"):
            artifacts.append(
                {
                    "type": artifact_type,
                    "run_id": child_run.id,
                    "changed_files": list(changed_files),
                    "preview": preview,
                    "truncated": len(patch) > len(preview),
                }
            )
        if isinstance(metadata.get("pr_artifact"), Mapping):
            artifacts.append(
                {"type": "pr_draft", "run_id": child_run.id, "preview": summary}
            )
    return tuple(
        artifact for artifact in artifacts if artifact["type"] in HANDOFF_ARTIFACT_TYPES
    )


def workflow_run_to_dict(
    run: WorkflowRun, steps: Sequence[StepAttempt] = ()
) -> dict[str, Any]:
    """Serialize a workflow run and optional step projections."""
    return {
        "id": run.id,
        "workflow_id": run.workflow_id,
        "definition_hash": run.definition_hash,
        "schema_version": run.schema_version,
        "status": run.status.value,
        "project_id": run.project_id,
        "project_root": run.project_root,
        "session_id": run.session_id,
        "definition": dict(run.definition),
        "inputs": dict(run.inputs),
        "outputs": dict(run.outputs),
        "max_concurrency": run.max_concurrency,
        "cancel_requested_at": run.cancel_requested_at,
        "error_summary": run.error_summary,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "finished_at": run.finished_at,
        "steps": [step_attempt_to_dict(item) for item in steps],
    }


def step_attempt_to_dict(attempt: StepAttempt) -> dict[str, Any]:
    """Serialize one redacted workflow step attempt."""
    return {
        "id": attempt.id,
        "workflow_run_id": attempt.workflow_run_id,
        "step_id": attempt.step_id,
        "attempt_number": attempt.attempt_number,
        "kind": attempt.kind.value,
        "status": attempt.status,
        "snapshot": dict(attempt.snapshot),
        "job_id": attempt.job_id,
        "inputs": dict(attempt.inputs),
        "outputs": dict(attempt.outputs),
        "artifact_refs": [dict(item) for item in attempt.artifact_refs],
        "error_summary": attempt.error_summary,
        "created_at": attempt.created_at,
        "updated_at": attempt.updated_at,
        "finished_at": attempt.finished_at,
    }


def render_review_team_workflow() -> str:
    """Render the built-in read-only Review Team definition."""
    payload = {
        "id": "review-team",
        "title": "Review Team",
        "description": "Read-only fan-out review and synthesis workflow.",
        "schema_version": 1,
        "version": "1.0.0",
        "inputs": {"prompt": "Review the current project."},
        "budgets": {"max_concurrency": 3, "max_steps": 5},
        "steps": [
            {
                "id": "plan",
                "kind": "agent",
                "agent_id": "planner",
                "prompt": "${prompt}",
            },
            {
                "id": "security",
                "kind": "agent",
                "agent_id": "reviewer",
                "depends_on": ["plan"],
                "prompt": "Perform a security review for: ${prompt}",
            },
            {
                "id": "tests",
                "kind": "agent",
                "agent_id": "test-runner",
                "depends_on": ["plan"],
                "prompt": "Review test gaps for: ${prompt}",
            },
            {
                "id": "maintainability",
                "kind": "agent",
                "agent_id": "reviewer",
                "depends_on": ["plan"],
                "prompt": "Review maintainability for: ${prompt}",
            },
            {
                "id": "synthesize",
                "kind": "agent",
                "agent_id": "planner",
                "depends_on": ["security", "tests", "maintainability"],
                "prompt": "Synthesize the review findings for: ${prompt}",
            },
        ],
    }
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def _parse_step(value: Any, *, allow_unknown: bool = False) -> WorkflowStep:
    data = _mapping(value)
    allowed = {
        "id",
        "kind",
        "title",
        "depends_on",
        "condition",
        "agent_id",
        "prompt",
        "eval_id",
        "harness_ids",
        "action",
        "transform",
        "select",
        "artifact_types",
        "retries",
        "timeout_seconds",
        "max_fan_out",
        "inputs",
        "output",
    }
    unknown = sorted(set(data) - allowed)
    if unknown and not allow_unknown:
        raise ValueError(f"Unknown workflow step fields: {', '.join(unknown)}")
    step_id = _safe_id(data.get("id"), "step id")
    try:
        kind = WorkflowStepKind(str(data.get("kind") or ""))
    except ValueError as exc:
        raise ValueError(f"Unsupported workflow step kind: {data.get('kind')}") from exc
    agent_id = _optional_text(data.get("agent_id"))
    eval_id = _optional_text(data.get("eval_id"))
    harness_ids = _text_tuple(data.get("harness_ids"), "harness_ids")
    action = _optional_text(data.get("action"))
    transform = _optional_text(data.get("transform"))
    if kind is WorkflowStepKind.AGENT and not agent_id:
        raise ValueError(f"Agent step {step_id} requires agent_id")
    if kind is WorkflowStepKind.ARENA and not harness_ids:
        raise ValueError(f"Arena step {step_id} requires harness_ids")
    if kind is WorkflowStepKind.EVAL and not eval_id:
        raise ValueError(f"Eval step {step_id} requires eval_id")
    if kind is WorkflowStepKind.APPROVAL:
        PermissionAction(action or PermissionAction.EXTERNAL_WRITE.value)
    if kind is WorkflowStepKind.TRANSFORM and transform not in {
        "identity",
        "select",
        "template",
    }:
        raise ValueError(
            f"Transform step {step_id} requires identity, select, or template"
        )
    condition = str(data.get("condition") or "on_success")
    if condition not in {"on_success", "on_failure", "always"}:
        raise ValueError(f"Unsupported condition for step {step_id}: {condition}")
    artifact_types = _text_tuple(data.get("artifact_types"), "artifact_types")
    unsupported_artifacts = sorted(set(artifact_types) - HANDOFF_ARTIFACT_TYPES)
    if unsupported_artifacts:
        raise ValueError(
            f"Unsupported handoff artifact types for step {step_id}: "
            f"{', '.join(unsupported_artifacts)}"
        )
    return WorkflowStep(
        id=step_id,
        kind=kind,
        title=str(data.get("title") or step_id).strip(),
        depends_on=_text_tuple(data.get("depends_on"), "depends_on"),
        condition=condition,
        agent_id=agent_id,
        prompt=_optional_text(data.get("prompt")),
        eval_id=eval_id,
        harness_ids=harness_ids,
        action=action,
        transform=transform,
        select=_text_tuple(data.get("select"), "select"),
        artifact_types=artifact_types,
        retries=_bounded_int(data.get("retries", 0), "retries", 0, 10),
        timeout_seconds=_optional_positive_int(
            data.get("timeout_seconds"), "timeout_seconds"
        ),
        max_fan_out=_bounded_int(
            data.get("max_fan_out", 1), "max_fan_out", 1, MAX_FAN_OUT
        ),
        inputs=dict(redact_for_storage(_mapping(data.get("inputs")))),
        output=_optional_text(data.get("output")),
    )


def _validate_graph(steps: Sequence[WorkflowStep]) -> None:
    ids = [step.id for step in steps]
    if len(ids) != len(set(ids)):
        raise ValueError("Workflow step ids must be unique")
    known = set(ids)
    for step in steps:
        missing = sorted(set(step.depends_on) - known)
        if missing:
            raise ValueError(
                f"Step {step.id} has unknown dependencies: {', '.join(missing)}"
            )
        if step.id in step.depends_on:
            raise ValueError(f"Step {step.id} cannot depend on itself")
    placed: set[str] = set()
    while len(placed) < len(steps):
        ready = [
            step.id
            for step in steps
            if step.id not in placed and set(step.depends_on) <= placed
        ]
        if not ready:
            raise ValueError("Workflow dependency graph contains a cycle")
        placed.update(ready)


def _step_from_snapshot(value: Mapping[str, Any]) -> WorkflowStep:
    return _parse_step(value)


def _step_to_dict(step: WorkflowStep) -> dict[str, Any]:
    payload = asdict(step)
    payload["kind"] = step.kind.value
    return dict(redact_for_storage(payload))


def _workflow_run_from_row(row: sqlite3.Row) -> WorkflowRun:
    return WorkflowRun(
        id=str(row["id"]),
        workflow_id=str(row["workflow_id"]),
        definition_hash=str(row["definition_hash"]),
        schema_version=int(row["schema_version"]),
        status=WorkflowStatus(str(row["status"])),
        project_id=str(row["project_id"]),
        project_root=str(row["project_root"]),
        session_id=str(row["session_id"]),
        definition=_json_mapping(row["definition_json"]),
        inputs=_json_mapping(row["inputs_json"]),
        outputs=_json_mapping(row["outputs_json"]),
        max_concurrency=int(row["max_concurrency"]),
        cancel_requested_at=_optional_text(row["cancel_requested_at"]),
        error_summary=_optional_text(row["error_summary"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        finished_at=_optional_text(row["finished_at"]),
    )


def _step_attempt_from_row(row: sqlite3.Row) -> StepAttempt:
    artifacts = _json_value(row["artifact_refs_json"], [])
    return StepAttempt(
        id=str(row["id"]),
        workflow_run_id=str(row["workflow_run_id"]),
        step_id=str(row["step_id"]),
        attempt_number=int(row["attempt_number"]),
        kind=WorkflowStepKind(str(row["kind"])),
        status=str(row["status"]),
        snapshot=_json_mapping(row["snapshot_json"]),
        job_id=_optional_text(row["job_id"]),
        inputs=_json_mapping(row["inputs_json"]),
        outputs=_json_mapping(row["outputs_json"]),
        artifact_refs=tuple(
            dict(item) for item in artifacts if isinstance(item, Mapping)
        ),
        error_summary=_optional_text(row["error_summary"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        finished_at=_optional_text(row["finished_at"]),
    )


def _condition_matches(condition: str, dependencies: Sequence[StepAttempt]) -> bool:
    if condition == "always" or not dependencies:
        return True
    failed = any(item.status in {"failed", "canceled"} for item in dependencies)
    return failed if condition == "on_failure" else not failed


def _step_inputs(
    workflow_inputs: Mapping[str, Any],
    step: WorkflowStep,
    dependencies: Sequence[StepAttempt],
) -> dict[str, Any]:
    return dict(
        redact_for_storage(
            {
                "workflow": dict(workflow_inputs),
                "dependencies": {
                    item.step_id: dict(item.outputs) for item in dependencies
                },
                "configured": dict(step.inputs),
            }
        )
    )


def _render_step_prompt(
    step: WorkflowStep,
    workflow_inputs: Mapping[str, Any],
    dependencies: Sequence[StepAttempt],
) -> str:
    values = {
        key: str(value)
        for key, value in workflow_inputs.items()
        if isinstance(value, (str, int, float, bool))
    }
    prompt = Template(step.prompt or "${prompt}").safe_substitute(values).strip()
    handoffs: list[str] = []
    remaining = MAX_HANDOFF_SUMMARY_CHARS
    selected_types = set(step.artifact_types)
    for item in dependencies:
        summary = str(item.outputs.get("summary") or "").strip()
        artifacts = [
            dict(artifact)
            for artifact in item.artifact_refs
            if not selected_types or str(artifact.get("type") or "") in selected_types
        ][:MAX_HANDOFF_ARTIFACTS]
        handoff = {"step_id": item.step_id}
        if summary:
            handoff["summary"] = summary
        if artifacts:
            handoff["artifacts"] = artifacts
        if len(handoff) == 1:
            continue
        rendered = json.dumps(handoff, ensure_ascii=False)
        if len(rendered) > remaining:
            rendered = rendered[: max(0, remaining - 1)].rstrip() + "…"
        if rendered:
            handoffs.append(rendered)
            remaining -= len(rendered)
        if remaining <= 0:
            break
    if handoffs:
        prompt += "\n\nBounded dependency handoffs:\n" + "\n".join(handoffs)
    return prompt or step.title


def _safe_transform(step: WorkflowStep, inputs: Mapping[str, Any]) -> dict[str, Any]:
    if step.transform == "identity":
        return {"value": inputs}
    if step.transform == "select":
        source = inputs.get("workflow")
        source = source if isinstance(source, Mapping) else {}
        return {key: source[key] for key in step.select if key in source}
    values = inputs.get("workflow")
    values = values if isinstance(values, Mapping) else {}
    rendered = Template(step.prompt or "").safe_substitute(
        {key: str(value) for key, value in values.items()}
    )
    return {step.output or "text": rendered}


def _safe_id(value: Any, name: str) -> str:
    text = _required_text(value, name)
    if not WORKFLOW_ID_PATTERN.fullmatch(text):
        raise ValueError(f"{name} must match ^[a-z][a-z0-9_-]{{1,63}}$")
    return text


def _required_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _mapping(value: Any) -> Mapping[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text_tuple(value: Any, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"{name} must be a list of non-empty strings")
    return tuple(item.strip() for item in value)


def _bounded_int(value: Any, name: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _optional_positive_int(value: Any, name: str) -> int | None:
    return None if value in {None, ""} else _bounded_int(value, name, 1, 86400)


def _json(value: Any) -> str:
    return json.dumps(redact_for_storage(value), ensure_ascii=False, sort_keys=True)


def _json_value(value: Any, default: Any) -> Any:
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return default


def _json_mapping(value: Any) -> dict[str, Any]:
    decoded = _json_value(value, {})
    return dict(decoded) if isinstance(decoded, Mapping) else {}
