"""Typed coordination models for the Unified Harness runtime."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class RunStatus(str, Enum):
    """Canonical status for one persisted harness run."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"

    def __str__(self) -> str:
        return self.value


class JobStatus(str, Enum):
    """Logical status shared by every attempt of one submitted job."""

    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_INPUT = "waiting_input"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class JobAttemptStatus(str, Enum):
    """Status of one concrete worker attempt."""

    CLAIMED = "claimed"
    STARTING = "starting"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    INTERRUPTED = "interrupted"


class WorkflowStatus(str, Enum):
    """Execution status reserved for the versioned workflow runtime."""

    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_INPUT = "waiting_input"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class ApprovalStatus(str, Enum):
    """Lifecycle state of one approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CANCELED = "canceled"


TERMINAL_RUN_STATUSES = frozenset(
    {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELED}
)
TERMINAL_JOB_STATUSES = frozenset(
    {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELED}
)
TERMINAL_ATTEMPT_STATUSES = frozenset(
    {
        JobAttemptStatus.SUCCEEDED,
        JobAttemptStatus.FAILED,
        JobAttemptStatus.CANCELED,
        JobAttemptStatus.INTERRUPTED,
    }
)

_RUN_STATUS_ALIASES = {
    "cancelled": RunStatus.CANCELED,
    "completed": RunStatus.SUCCEEDED,
    "done": RunStatus.SUCCEEDED,
    "error": RunStatus.FAILED,
    "in_progress": RunStatus.RUNNING,
    "pending": RunStatus.QUEUED,
    "started": RunStatus.RUNNING,
    "stopped": RunStatus.CANCELED,
    "success": RunStatus.SUCCEEDED,
}


def parse_run_status(value: Any) -> RunStatus:
    """Normalize legacy headless/native completion names."""
    if isinstance(value, RunStatus):
        return value
    normalized = str(value or RunStatus.QUEUED.value).strip().lower().replace("-", "_")
    alias = _RUN_STATUS_ALIASES.get(normalized)
    return alias if alias is not None else RunStatus(normalized)


def parse_job_status(value: Any) -> JobStatus:
    """Parse a logical job status."""
    if isinstance(value, JobStatus):
        return value
    return JobStatus(str(value).strip().lower())


def parse_attempt_status(value: Any) -> JobAttemptStatus:
    """Parse an attempt status."""
    if isinstance(value, JobAttemptStatus):
        return value
    return JobAttemptStatus(str(value).strip().lower())


@dataclass(frozen=True)
class RuntimeJob:
    """Mutable coordination record for one logical job."""

    id: str
    origin: str
    idempotency_key_hash: str
    status: JobStatus
    session_id: str
    user_message_id: str
    initial_run_id: str
    created_at: str
    updated_at: str
    project_id: str | None = None
    workflow_id: str | None = None
    workflow_version: str | None = None
    schedule_id: str | None = None
    agent_id: str | None = None
    available_at: str | None = None
    terminal_at: str | None = None
    cancel_requested_at: str | None = None
    max_attempts: int = 1
    priority: int = 0
    version: int = 0
    error_summary: str | None = None
    required_harness_id: str | None = None
    required_capability_fingerprint: Mapping[str, Any] | None = None
    timeout_seconds: float | None = None
    approval_request_id: str | None = None


@dataclass(frozen=True)
class JobAttempt:
    """One concrete execution attempt linked to one HarnessRun."""

    id: str
    job_id: str
    attempt_number: int
    status: JobAttemptStatus
    run_id: str
    created_at: str
    updated_at: str
    lease_owner: str | None = None
    leased_until: str | None = None
    heartbeat_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    process_id: int | None = None
    process_group_id: int | None = None
    retry_reason: str | None = None
    idempotency_class: str = "unknown"
    error_summary: str | None = None
    capability_fingerprint: Mapping[str, Any] | None = None
    version: int = 0


@dataclass(frozen=True)
class ClaimedJob:
    """Atomic worker claim containing a logical job and concrete attempt."""

    job: RuntimeJob
    attempt: JobAttempt


@dataclass(frozen=True)
class RuntimeWorker:
    """Durable worker liveness and capability snapshot."""

    id: str
    process_id: int
    hostname: str
    status: str
    started_at: str
    heartbeat_at: str
    stopped_at: str | None
    capability_fingerprint: Mapping[str, Any]


@dataclass(frozen=True)
class RuntimeOutboxEntry:
    """Idempotent bridge event between SQLite and JSON/JSONL history."""

    id: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    dedupe_key: str
    payload: Mapping[str, Any]
    created_at: str
    processed_at: str | None = None
    attempt_count: int = 0
    last_error: str | None = None


@dataclass(frozen=True)
class NativeProcessRecord:
    """Durable public ownership and recovery state for a native process."""

    id: str
    owner_id: str
    owner_process_id: int
    session_id: str
    run_id: str
    harness_id: str
    status: str
    process_id: int | None
    process_group_id: int | None
    transport: str
    ref: Mapping[str, Any]
    started_at: str
    updated_at: str
    heartbeat_at: str
    leased_until: str
    timeout_at: str | None = None
    cancel_requested_at: str | None = None
    finished_at: str | None = None
    terminal_cursor: int = 0
    recovery_outcome: str | None = None
    version: int = 0


@dataclass(frozen=True)
class NativeProcessOutputRecord:
    """One bounded redacted native terminal output reference."""

    process_id: str
    cursor: int
    stream: str
    text: str
    created_at: str


@dataclass(frozen=True)
class JobSubmission:
    """Result of an idempotent job submission."""

    job: RuntimeJob
    created: bool


def job_to_dict(job: RuntimeJob) -> dict[str, Any]:
    """Serialize one job without any task payload."""
    return {
        "id": job.id,
        "origin": job.origin,
        "idempotency_key_hash": job.idempotency_key_hash,
        "status": job.status.value,
        "session_id": job.session_id,
        "user_message_id": job.user_message_id,
        "initial_run_id": job.initial_run_id,
        "project_id": job.project_id,
        "workflow_id": job.workflow_id,
        "workflow_version": job.workflow_version,
        "schedule_id": job.schedule_id,
        "agent_id": job.agent_id,
        "available_at": job.available_at,
        "terminal_at": job.terminal_at,
        "cancel_requested_at": job.cancel_requested_at,
        "max_attempts": job.max_attempts,
        "priority": job.priority,
        "version": job.version,
        "error_summary": job.error_summary,
        "required_harness_id": job.required_harness_id,
        "required_capability_fingerprint": dict(
            job.required_capability_fingerprint or {}
        ),
        "timeout_seconds": job.timeout_seconds,
        "approval_request_id": job.approval_request_id,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def attempt_to_dict(attempt: JobAttempt) -> dict[str, Any]:
    """Serialize one attempt."""
    return {
        "id": attempt.id,
        "job_id": attempt.job_id,
        "attempt_number": attempt.attempt_number,
        "status": attempt.status.value,
        "run_id": attempt.run_id,
        "lease_owner": attempt.lease_owner,
        "leased_until": attempt.leased_until,
        "heartbeat_at": attempt.heartbeat_at,
        "started_at": attempt.started_at,
        "finished_at": attempt.finished_at,
        "process_id": attempt.process_id,
        "process_group_id": attempt.process_group_id,
        "retry_reason": attempt.retry_reason,
        "idempotency_class": attempt.idempotency_class,
        "error_summary": attempt.error_summary,
        "capability_fingerprint": dict(attempt.capability_fingerprint or {}),
        "version": attempt.version,
        "created_at": attempt.created_at,
        "updated_at": attempt.updated_at,
    }


def outbox_entry_to_dict(entry: RuntimeOutboxEntry) -> dict[str, Any]:
    """Serialize one outbox entry."""
    return {
        "id": entry.id,
        "aggregate_type": entry.aggregate_type,
        "aggregate_id": entry.aggregate_id,
        "event_type": entry.event_type,
        "dedupe_key": entry.dedupe_key,
        "payload": dict(entry.payload),
        "created_at": entry.created_at,
        "processed_at": entry.processed_at,
        "attempt_count": entry.attempt_count,
        "last_error": entry.last_error,
    }


def worker_to_dict(worker: RuntimeWorker) -> dict[str, Any]:
    """Serialize one redaction-safe worker capability snapshot."""
    return {
        "id": worker.id,
        "process_id": worker.process_id,
        "hostname": worker.hostname,
        "status": worker.status,
        "started_at": worker.started_at,
        "heartbeat_at": worker.heartbeat_at,
        "stopped_at": worker.stopped_at,
        "capability_fingerprint": dict(worker.capability_fingerprint),
    }


def native_process_record_to_dict(record: NativeProcessRecord) -> dict[str, Any]:
    """Serialize one durable native process ownership record."""
    return {
        "id": record.id,
        "owner_id": record.owner_id,
        "owner_process_id": record.owner_process_id,
        "session_id": record.session_id,
        "run_id": record.run_id,
        "harness_id": record.harness_id,
        "status": record.status,
        "process_id": record.process_id,
        "process_group_id": record.process_group_id,
        "transport": record.transport,
        "ref": dict(record.ref),
        "started_at": record.started_at,
        "updated_at": record.updated_at,
        "heartbeat_at": record.heartbeat_at,
        "leased_until": record.leased_until,
        "timeout_at": record.timeout_at,
        "cancel_requested_at": record.cancel_requested_at,
        "finished_at": record.finished_at,
        "terminal_cursor": record.terminal_cursor,
        "recovery_outcome": record.recovery_outcome,
        "version": record.version,
    }
