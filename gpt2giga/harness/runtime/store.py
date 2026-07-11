"""SQLite coordination store for durable Unified Harness jobs."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator, Mapping
from uuid import uuid4

from gpt2giga.harness.runtime.models import (
    ApprovalStatus,
    ClaimedJob,
    JobAttempt,
    JobAttemptStatus,
    JobStatus,
    JobSubmission,
    RuntimeJob,
    RuntimeOutboxEntry,
    RuntimeWorker,
    TERMINAL_ATTEMPT_STATUSES,
    TERMINAL_JOB_STATUSES,
    attempt_to_dict,
    job_to_dict,
    outbox_entry_to_dict,
    parse_attempt_status,
    parse_job_status,
    worker_to_dict,
)
from gpt2giga.harness.runtime.policy import (
    ApprovalDecision,
    ApprovalGrant,
    ApprovalRequest,
    EnforcementLevel,
    PermissionAction,
    PolicyContext,
    PolicyResolution,
    approval_grant_to_dict,
    approval_request_to_dict,
    redacted_policy_preview,
)
from gpt2giga.harness.sessions.redaction import redact_for_storage

RUNTIME_DB_NAME = "runtime.sqlite3"
RUNTIME_SCHEMA_VERSION = 6
SQLITE_TIMEOUT_SECONDS = 10.0


class RuntimeStoreError(RuntimeError):
    """Base error for durable coordination operations."""


class JobNotFoundError(RuntimeStoreError):
    """Raised when a logical job does not exist."""


class AttemptNotFoundError(RuntimeStoreError):
    """Raised when a job attempt does not exist."""


class IdempotencyConflictError(RuntimeStoreError):
    """Raised when one idempotency key is reused for a different job."""


class ConcurrentUpdateError(RuntimeStoreError):
    """Raised when an expected coordination state changed concurrently."""


class InvalidStateTransitionError(RuntimeStoreError):
    """Raised when a terminal object is restarted without an explicit retry."""


_MIGRATIONS: tuple[tuple[int, str, tuple[str, ...]], ...] = (
    (
        1,
        "initial runtime coordination schema",
        (
            """
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY,
                origin TEXT NOT NULL,
                idempotency_key_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                session_id TEXT NOT NULL,
                user_message_id TEXT NOT NULL,
                project_id TEXT,
                workflow_id TEXT,
                schedule_id TEXT,
                agent_id TEXT,
                available_at TEXT,
                terminal_at TEXT,
                cancel_requested_at TEXT,
                max_attempts INTEGER NOT NULL DEFAULT 1 CHECK (max_attempts > 0),
                priority INTEGER NOT NULL DEFAULT 0,
                version INTEGER NOT NULL DEFAULT 0,
                error_summary TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (origin, idempotency_key_hash)
            )
            """,
            """
            CREATE TABLE job_attempts (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
                status TEXT NOT NULL,
                run_id TEXT NOT NULL UNIQUE,
                lease_owner TEXT,
                leased_until TEXT,
                heartbeat_at TEXT,
                started_at TEXT,
                finished_at TEXT,
                process_id INTEGER,
                retry_reason TEXT,
                idempotency_class TEXT NOT NULL DEFAULT 'unknown',
                error_summary TEXT,
                version INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (job_id, attempt_number)
            )
            """,
            """
            CREATE TABLE runtime_outbox (
                id TEXT PRIMARY KEY,
                aggregate_type TEXT NOT NULL,
                aggregate_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                dedupe_key TEXT NOT NULL UNIQUE,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                processed_at TEXT,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT
            )
            """,
            """
            CREATE TABLE trace_sequences (
                trace_id TEXT PRIMARY KEY,
                last_sequence INTEGER NOT NULL CHECK (last_sequence >= 0)
            )
            """,
            "CREATE INDEX jobs_status_available_idx ON jobs(status, available_at, priority)",
            "CREATE INDEX attempts_job_idx ON job_attempts(job_id, attempt_number)",
            "CREATE INDEX attempts_status_lease_idx ON job_attempts(status, leased_until)",
            "CREATE INDEX outbox_pending_idx ON runtime_outbox(processed_at, created_at)",
        ),
    ),
    (
        2,
        "versioned workflow relationship indexes",
        (
            "ALTER TABLE jobs ADD COLUMN workflow_version TEXT",
            "CREATE INDEX jobs_session_idx ON jobs(session_id, created_at)",
            "CREATE INDEX jobs_project_idx ON jobs(project_id, created_at)",
            "CREATE INDEX jobs_workflow_idx ON jobs(workflow_id, workflow_version, created_at)",
            "CREATE INDEX jobs_schedule_idx ON jobs(schedule_id, created_at)",
            "CREATE INDEX attempts_run_idx ON job_attempts(run_id)",
        ),
    ),
    (
        3,
        "durable workers leases and capability matching",
        (
            "ALTER TABLE jobs ADD COLUMN initial_run_id TEXT",
            "ALTER TABLE jobs ADD COLUMN required_harness_id TEXT",
            "ALTER TABLE jobs ADD COLUMN required_fingerprint_json TEXT NOT NULL DEFAULT '{}'",
            "ALTER TABLE jobs ADD COLUMN timeout_seconds REAL",
            "ALTER TABLE job_attempts ADD COLUMN process_group_id INTEGER",
            "ALTER TABLE job_attempts ADD COLUMN capability_fingerprint_json TEXT NOT NULL DEFAULT '{}'",
            "CREATE INDEX jobs_required_harness_idx ON jobs(required_harness_id, status, available_at)",
            "CREATE INDEX jobs_initial_run_idx ON jobs(initial_run_id)",
            """
            CREATE TABLE workers (
                id TEXT PRIMARY KEY,
                process_id INTEGER NOT NULL,
                hostname TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                heartbeat_at TEXT NOT NULL,
                stopped_at TEXT,
                capability_fingerprint_json TEXT NOT NULL
            )
            """,
            "CREATE INDEX workers_status_heartbeat_idx ON workers(status, heartbeat_at)",
        ),
    ),
    (
        4,
        "unified policy approvals and scoped grants",
        (
            "ALTER TABLE jobs ADD COLUMN approval_request_id TEXT",
            "CREATE INDEX jobs_approval_idx ON jobs(approval_request_id, status)",
            """
            CREATE TABLE approval_requests (
                id TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                enforcement TEXT NOT NULL,
                policy_source TEXT NOT NULL,
                reason TEXT NOT NULL,
                preview_json TEXT NOT NULL DEFAULT '{}',
                project_id TEXT,
                session_id TEXT,
                run_id TEXT,
                job_id TEXT REFERENCES jobs(id) ON DELETE CASCADE,
                dedupe_key TEXT NOT NULL,
                decision TEXT,
                expires_at TEXT,
                decided_at TEXT,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE UNIQUE INDEX approval_pending_dedupe_idx
            ON approval_requests(dedupe_key) WHERE status = 'pending'
            """,
            "CREATE INDEX approval_inbox_idx ON approval_requests(status, created_at DESC)",
            "CREATE INDEX approval_job_idx ON approval_requests(job_id, created_at)",
            """
            CREATE TABLE approval_grants (
                id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL REFERENCES approval_requests(id) ON DELETE CASCADE,
                action TEXT NOT NULL,
                scope_type TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                uses_remaining INTEGER,
                expires_at TEXT,
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX approval_grant_match_idx ON approval_grants(action, scope_type, scope_id, expires_at)",
        ),
    ),
    (
        5,
        "versioned workflow runs and step attempts",
        (
            """
            CREATE TABLE workflow_runs (
                id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                definition_hash TEXT NOT NULL,
                schema_version INTEGER NOT NULL,
                status TEXT NOT NULL,
                project_id TEXT NOT NULL,
                project_root TEXT NOT NULL,
                session_id TEXT NOT NULL,
                definition_json TEXT NOT NULL,
                inputs_json TEXT NOT NULL DEFAULT '{}',
                outputs_json TEXT NOT NULL DEFAULT '{}',
                max_concurrency INTEGER NOT NULL DEFAULT 1,
                cancel_requested_at TEXT,
                error_summary TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                finished_at TEXT
            )
            """,
            "CREATE INDEX workflow_runs_definition_idx ON workflow_runs(workflow_id, definition_hash, created_at)",
            "CREATE INDEX workflow_runs_status_idx ON workflow_runs(status, updated_at)",
            """
            CREATE TABLE workflow_step_attempts (
                id TEXT PRIMARY KEY,
                workflow_run_id TEXT NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
                step_id TEXT NOT NULL,
                attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL,
                inputs_json TEXT NOT NULL DEFAULT '{}',
                outputs_json TEXT NOT NULL DEFAULT '{}',
                artifact_refs_json TEXT NOT NULL DEFAULT '[]',
                error_summary TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                finished_at TEXT,
                UNIQUE (workflow_run_id, step_id, attempt_number)
            )
            """,
            "CREATE INDEX workflow_steps_run_status_idx ON workflow_step_attempts(workflow_run_id, status, step_id)",
            "CREATE INDEX workflow_steps_job_idx ON workflow_step_attempts(job_id)",
        ),
    ),
    (
        6,
        "scheduled job definitions and occurrence state",
        (
            """
            CREATE TABLE schedule_states (
                schedule_key TEXT PRIMARY KEY,
                schedule_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                project_root TEXT NOT NULL,
                definition_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'paused',
                enabled INTEGER NOT NULL DEFAULT 0,
                timezone TEXT NOT NULL,
                next_run_at TEXT,
                tested_hash TEXT,
                tested_at TEXT,
                last_run_at TEXT,
                last_status TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (project_id, schedule_id)
            )
            """,
            "CREATE INDEX schedule_states_due_idx ON schedule_states(enabled, status, next_run_at)",
            "CREATE INDEX schedule_states_project_idx ON schedule_states(project_id, updated_at)",
            """
            CREATE TABLE schedule_occurrences (
                id TEXT PRIMARY KEY,
                schedule_key TEXT NOT NULL REFERENCES schedule_states(schedule_key) ON DELETE CASCADE,
                schedule_id TEXT NOT NULL,
                definition_hash TEXT NOT NULL,
                scheduled_for TEXT NOT NULL,
                trigger TEXT NOT NULL,
                status TEXT NOT NULL,
                destination_session_id TEXT,
                history_cutoff TEXT,
                job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL,
                run_id TEXT,
                error_summary TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                UNIQUE (schedule_id, scheduled_for, trigger)
            )
            """,
            "CREATE INDEX schedule_occurrences_schedule_idx ON schedule_occurrences(schedule_key, created_at DESC)",
            "CREATE INDEX schedule_occurrences_active_idx ON schedule_occurrences(status, destination_session_id)",
        ),
    ),
)


class RuntimeCoordinationStore:
    """Store atomic job, attempt, lease-link, and outbox coordination state."""

    def __init__(
        self, data_dir: str | Path, *, filename: str = RUNTIME_DB_NAME
    ) -> None:
        self.data_dir = Path(data_dir).expanduser()
        self.path = self.data_dir / filename
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._migrate()

    @property
    def schema_version(self) -> int:
        """Return the currently applied schema version."""
        with self._connect() as connection:
            row = connection.execute("PRAGMA user_version").fetchone()
        return int(row[0])

    def submit_job(
        self,
        *,
        session_id: str,
        user_message_id: str,
        idempotency_key: str,
        initial_run_id: str | None = None,
        origin: str = "manual",
        project_id: str | None = None,
        workflow_id: str | None = None,
        workflow_version: str | None = None,
        schedule_id: str | None = None,
        agent_id: str | None = None,
        max_attempts: int = 1,
        priority: int = 0,
        available_at: str | None = None,
        required_harness_id: str | None = None,
        required_capability_fingerprint: Mapping[str, Any] | None = None,
        timeout_seconds: float | None = None,
        initial_status: JobStatus | str = JobStatus.QUEUED,
    ) -> JobSubmission:
        """Submit one job or return the existing identity-matched job."""
        session_id = _required_text(session_id, "session_id")
        user_message_id = _required_text(user_message_id, "user_message_id")
        origin = _required_text(origin, "origin")
        submit_status = parse_job_status(initial_status)
        if submit_status not in {
            JobStatus.QUEUED,
            JobStatus.WAITING_INPUT,
            JobStatus.WAITING_APPROVAL,
        }:
            raise ValueError(
                "initial job status must be queued, waiting_input, or waiting_approval"
            )
        initial_run_id = _required_text(
            initial_run_id or _new_id("run"), "initial_run_id"
        )
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        key_hash = _idempotency_hash(idempotency_key)
        now = _utc_now()
        job_id = _new_id("job")
        values = {
            "id": job_id,
            "origin": origin,
            "idempotency_key_hash": key_hash,
            "status": submit_status.value,
            "session_id": session_id,
            "user_message_id": user_message_id,
            "initial_run_id": initial_run_id,
            "project_id": _optional_text(project_id),
            "workflow_id": _optional_text(workflow_id),
            "workflow_version": _optional_text(workflow_version),
            "schedule_id": _optional_text(schedule_id),
            "agent_id": _optional_text(agent_id),
            "available_at": available_at or now,
            "max_attempts": max_attempts,
            "priority": int(priority),
            "required_harness_id": _optional_text(required_harness_id),
            "required_fingerprint_json": _safe_json(
                required_capability_fingerprint or {}
            ),
            "timeout_seconds": (
                float(timeout_seconds) if timeout_seconds is not None else None
            ),
            "created_at": now,
            "updated_at": now,
        }
        with self._connect() as connection, _transaction(connection):
            try:
                connection.execute(
                    """
                    INSERT INTO jobs (
                        id, origin, idempotency_key_hash, status, session_id,
                        user_message_id, initial_run_id, project_id, workflow_id, workflow_version,
                        schedule_id, agent_id, available_at, max_attempts, priority,
                        required_harness_id, required_fingerprint_json,
                        timeout_seconds, created_at, updated_at
                    ) VALUES (
                        :id, :origin, :idempotency_key_hash, :status, :session_id,
                        :user_message_id, :initial_run_id, :project_id, :workflow_id, :workflow_version,
                        :schedule_id, :agent_id, :available_at, :max_attempts,
                        :priority, :required_harness_id, :required_fingerprint_json,
                        :timeout_seconds,
                        :created_at, :updated_at
                    )
                    """,
                    values,
                )
                row = connection.execute(
                    "SELECT * FROM jobs WHERE id = ?", (job_id,)
                ).fetchone()
                return JobSubmission(job=_job_from_row(row), created=True)
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT * FROM jobs
                    WHERE origin = ? AND idempotency_key_hash = ?
                    """,
                    (origin, key_hash),
                ).fetchone()
                if row is None:
                    raise
                existing = _job_from_row(row)
                expected_identity = (
                    session_id,
                    user_message_id,
                    _optional_text(project_id),
                    _optional_text(workflow_id),
                    _optional_text(workflow_version),
                    _optional_text(schedule_id),
                    _optional_text(agent_id),
                )
                actual_identity = (
                    existing.session_id,
                    existing.user_message_id,
                    existing.project_id,
                    existing.workflow_id,
                    existing.workflow_version,
                    existing.schedule_id,
                    existing.agent_id,
                )
                if actual_identity != expected_identity:
                    raise IdempotencyConflictError(
                        "idempotency key is already bound to a different job"
                    )
                return JobSubmission(job=existing, created=False)

    def find_job_by_idempotency(
        self, *, origin: str, idempotency_key: str
    ) -> RuntimeJob | None:
        """Return a job previously submitted with the caller-owned key."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE origin = ? AND idempotency_key_hash = ?",
                (_required_text(origin, "origin"), _idempotency_hash(idempotency_key)),
            ).fetchone()
        return _job_from_row(row) if row is not None else None

    def get_job(self, job_id: str) -> RuntimeJob:
        """Return one job."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise JobNotFoundError(job_id)
        return _job_from_row(row)

    def list_jobs(self) -> tuple[RuntimeJob, ...]:
        """List all jobs in stable creation order."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at, id"
            ).fetchall()
        return tuple(_job_from_row(row) for row in rows)

    def list_jobs_page(
        self,
        *,
        statuses: tuple[JobStatus | str, ...] = (),
        project_id: str | None = None,
        harness_id: str | None = None,
        cursor: tuple[str, str] | None = None,
        limit: int = 25,
    ) -> tuple[tuple[RuntimeJob, ...], bool]:
        """List a newest-first cursor page without loading task payloads."""
        page_size = max(1, min(int(limit), 100))
        clauses: list[str] = []
        params: list[Any] = []
        parsed_statuses = tuple(parse_job_status(status) for status in statuses)
        if parsed_statuses:
            placeholders = ", ".join("?" for _ in parsed_statuses)
            clauses.append(f"status IN ({placeholders})")
            params.extend(status.value for status in parsed_statuses)
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(_required_text(project_id, "project_id"))
        if harness_id is not None:
            clauses.append("required_harness_id = ?")
            params.append(_required_text(harness_id, "harness_id"))
        if cursor is not None:
            created_at, job_id = cursor
            clauses.append("(created_at < ? OR (created_at = ? AND id < ?))")
            params.extend((created_at, created_at, job_id))
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(page_size + 1)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM jobs{where} ORDER BY created_at DESC, id DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        has_more = len(rows) > page_size
        return (
            tuple(_job_from_row(row) for row in rows[:page_size]),
            has_more,
        )

    def transition_job(
        self,
        job_id: str,
        status: JobStatus | str,
        *,
        expected_status: JobStatus | str | None = None,
        error_summary: str | None = None,
        available_at: str | None = None,
    ) -> RuntimeJob:
        """Atomically transition one logical job and enqueue terminal sync."""
        target = parse_job_status(status)
        expected = parse_job_status(expected_status) if expected_status else None
        now = _utc_now()
        safe_error = _safe_optional_text(error_summary)
        with self._connect() as connection, _transaction(connection):
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise JobNotFoundError(job_id)
            current = _job_from_row(row)
            if expected is not None and current.status is not expected:
                raise ConcurrentUpdateError(
                    f"job {job_id} is {current.status.value}, expected {expected.value}"
                )
            if current.status is target:
                return current
            if current.status in TERMINAL_JOB_STATUSES:
                raise InvalidStateTransitionError(
                    f"terminal job {job_id} cannot transition to {target.value}"
                )
            terminal_at = now if target in TERMINAL_JOB_STATUSES else None
            next_version = current.version + 1
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, available_at = COALESCE(?, available_at),
                    terminal_at = ?, error_summary = ?, updated_at = ?,
                    version = ?
                WHERE id = ? AND version = ?
                """,
                (
                    target.value,
                    available_at,
                    terminal_at,
                    safe_error,
                    now,
                    next_version,
                    job_id,
                    current.version,
                ),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise ConcurrentUpdateError(f"job {job_id} changed concurrently")
            if target in TERMINAL_JOB_STATUSES:
                attempt_row = connection.execute(
                    """
                    SELECT * FROM job_attempts
                    WHERE job_id = ? ORDER BY attempt_number DESC LIMIT 1
                    """,
                    (job_id,),
                ).fetchone()
                attempt = _attempt_from_row(attempt_row) if attempt_row else None
                self._enqueue_terminal_sync(
                    connection,
                    job_id=job_id,
                    status=target,
                    version=next_version,
                    session_id=current.session_id,
                    attempt=attempt,
                )
            updated = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return _job_from_row(updated)

    def create_attempt(
        self,
        job_id: str,
        *,
        run_id: str,
        status: JobAttemptStatus | str = JobAttemptStatus.CLAIMED,
        lease_owner: str | None = None,
        leased_until: str | None = None,
        retry_reason: str | None = None,
        idempotency_class: str = "unknown",
    ) -> JobAttempt:
        """Create the next attempt and bind it to a distinct HarnessRun."""
        target = parse_attempt_status(status)
        run_id = _required_text(run_id, "run_id")
        now = _utc_now()
        with self._connect() as connection, _transaction(connection):
            job_row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if job_row is None:
                raise JobNotFoundError(job_id)
            job = _job_from_row(job_row)
            if job.status in TERMINAL_JOB_STATUSES:
                raise InvalidStateTransitionError(
                    f"cannot create an attempt for terminal job {job_id}"
                )
            row = connection.execute(
                "SELECT COALESCE(MAX(attempt_number), 0) FROM job_attempts WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            attempt_number = int(row[0]) + 1
            if attempt_number > job.max_attempts:
                raise InvalidStateTransitionError(
                    f"job {job_id} exhausted its {job.max_attempts} attempts"
                )
            attempt_id = _new_id("attempt")
            connection.execute(
                """
                INSERT INTO job_attempts (
                    id, job_id, attempt_number, status, run_id, lease_owner,
                    leased_until, retry_reason, idempotency_class, created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    job_id,
                    attempt_number,
                    target.value,
                    run_id,
                    _optional_text(lease_owner),
                    leased_until,
                    _safe_optional_text(retry_reason),
                    _required_text(idempotency_class, "idempotency_class"),
                    now,
                    now,
                ),
            )
            if job.status is not JobStatus.RUNNING:
                connection.execute(
                    """
                    UPDATE jobs SET status = ?, terminal_at = NULL,
                        updated_at = ?, version = version + 1 WHERE id = ?
                    """,
                    (JobStatus.RUNNING.value, now, job_id),
                )
            attempt_row = connection.execute(
                "SELECT * FROM job_attempts WHERE id = ?", (attempt_id,)
            ).fetchone()
        return _attempt_from_row(attempt_row)

    def get_attempt(self, attempt_id: str) -> JobAttempt:
        """Return one attempt."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM job_attempts WHERE id = ?", (attempt_id,)
            ).fetchone()
        if row is None:
            raise AttemptNotFoundError(attempt_id)
        return _attempt_from_row(row)

    def list_attempts(self, job_id: str | None = None) -> tuple[JobAttempt, ...]:
        """List attempts globally or for one job."""
        query = "SELECT * FROM job_attempts"
        params: tuple[Any, ...] = ()
        if job_id is not None:
            query += " WHERE job_id = ?"
            params = (job_id,)
        query += " ORDER BY created_at, attempt_number, id"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return tuple(_attempt_from_row(row) for row in rows)

    def find_job_for_run(self, run_id: str) -> RuntimeJob | None:
        """Return the job owning an initial or attempted run."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT jobs.* FROM jobs
                LEFT JOIN job_attempts ON job_attempts.job_id = jobs.id
                WHERE jobs.initial_run_id = ? OR job_attempts.run_id = ?
                ORDER BY job_attempts.attempt_number DESC LIMIT 1
                """,
                (run_id, run_id),
            ).fetchone()
        return _job_from_row(row) if row is not None else None

    def link_job_workflow(
        self, job_id: str, *, workflow_id: str, workflow_version: str
    ) -> RuntimeJob:
        """Attach an already-submitted child job to its immutable workflow run."""
        with self._connect() as connection, _transaction(connection):
            connection.execute(
                """
                UPDATE jobs SET workflow_id = ?, workflow_version = ?,
                    updated_at = ?, version = version + 1
                WHERE id = ? AND (workflow_id IS NULL OR workflow_id = ?)
                """,
                (workflow_id, workflow_version, _utc_now(), job_id, workflow_id),
            )
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise JobNotFoundError(job_id)
        job = _job_from_row(row)
        if job.workflow_id != workflow_id:
            raise ConcurrentUpdateError(f"job {job_id} belongs to another workflow")
        return job

    def claim_next_job(
        self,
        *,
        worker_id: str,
        capability_fingerprint: Mapping[str, Any],
        lease_seconds: float,
    ) -> ClaimedJob | None:
        """Atomically claim the first due job supported by this worker."""
        worker_id = _required_text(worker_id, "worker_id")
        now = _utc_now()
        leased_until = _future_time(max(lease_seconds, 1.0))
        with self._connect() as connection, _transaction(connection):
            rows = connection.execute(
                """
                SELECT * FROM jobs
                WHERE status = ? AND (available_at IS NULL OR available_at <= ?)
                  AND cancel_requested_at IS NULL
                ORDER BY priority DESC, created_at, id
                """,
                (JobStatus.QUEUED.value, now),
            ).fetchall()
            job_row = next(
                (
                    row
                    for row in rows
                    if _fingerprint_matches(
                        _json_mapping(row["required_fingerprint_json"]),
                        capability_fingerprint,
                        required_harness_id=_optional_text(row["required_harness_id"]),
                    )
                ),
                None,
            )
            if job_row is None:
                return None
            job = _job_from_row(job_row)
            count_row = connection.execute(
                "SELECT COALESCE(MAX(attempt_number), 0) FROM job_attempts WHERE job_id = ?",
                (job.id,),
            ).fetchone()
            attempt_number = int(count_row[0]) + 1
            if attempt_number > job.max_attempts:
                connection.execute(
                    "UPDATE jobs SET status = ?, terminal_at = ?, updated_at = ?, version = version + 1 WHERE id = ?",
                    (JobStatus.FAILED.value, now, now, job.id),
                )
                return None
            run_id = job.initial_run_id if attempt_number == 1 else _new_id("run")
            attempt_id = _new_id("attempt")
            connection.execute(
                """
                INSERT INTO job_attempts (
                    id, job_id, attempt_number, status, run_id, lease_owner,
                    leased_until, heartbeat_at, idempotency_class,
                    capability_fingerprint_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    job.id,
                    attempt_number,
                    JobAttemptStatus.CLAIMED.value,
                    run_id,
                    worker_id,
                    leased_until,
                    now,
                    "unknown",
                    _safe_json(capability_fingerprint),
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE jobs SET status = ?, updated_at = ?, version = version + 1
                WHERE id = ? AND status = ?
                """,
                (JobStatus.RUNNING.value, now, job.id, JobStatus.QUEUED.value),
            )
            claimed_job = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job.id,)
            ).fetchone()
            attempt_row = connection.execute(
                "SELECT * FROM job_attempts WHERE id = ?", (attempt_id,)
            ).fetchone()
        return ClaimedJob(
            job=_job_from_row(claimed_job), attempt=_attempt_from_row(attempt_row)
        )

    def heartbeat_attempt(
        self, attempt_id: str, *, worker_id: str, lease_seconds: float
    ) -> JobAttempt:
        """Renew an owned attempt lease."""
        now = _utc_now()
        with self._connect() as connection, _transaction(connection):
            connection.execute(
                """
                UPDATE job_attempts
                SET heartbeat_at = ?, leased_until = ?, updated_at = ?, version = version + 1
                WHERE id = ? AND lease_owner = ? AND status NOT IN (?, ?, ?, ?)
                """,
                (
                    now,
                    _future_time(max(lease_seconds, 1.0)),
                    now,
                    attempt_id,
                    worker_id,
                    JobAttemptStatus.SUCCEEDED.value,
                    JobAttemptStatus.FAILED.value,
                    JobAttemptStatus.CANCELED.value,
                    JobAttemptStatus.INTERRUPTED.value,
                ),
            )
            row = connection.execute(
                "SELECT * FROM job_attempts WHERE id = ?", (attempt_id,)
            ).fetchone()
        if row is None:
            raise AttemptNotFoundError(attempt_id)
        return _attempt_from_row(row)

    def update_attempt_process(
        self, attempt_id: str, *, process_id: int, process_group_id: int | None
    ) -> JobAttempt:
        """Persist redacted process ownership metadata for cancellation/audit."""
        with self._connect() as connection, _transaction(connection):
            connection.execute(
                """
                UPDATE job_attempts SET process_id = ?, process_group_id = ?,
                    updated_at = ?, version = version + 1 WHERE id = ?
                """,
                (process_id, process_group_id, _utc_now(), attempt_id),
            )
            row = connection.execute(
                "SELECT * FROM job_attempts WHERE id = ?", (attempt_id,)
            ).fetchone()
        if row is None:
            raise AttemptNotFoundError(attempt_id)
        return _attempt_from_row(row)

    def request_cancel(self, job_id: str) -> RuntimeJob:
        """Persist a cooperative cancellation request for a logical job."""
        now = _utc_now()
        with self._connect() as connection, _transaction(connection):
            connection.execute(
                """
                UPDATE jobs SET cancel_requested_at = COALESCE(cancel_requested_at, ?),
                    updated_at = ?, version = version + 1
                WHERE id = ? AND status NOT IN (?, ?, ?)
                """,
                (
                    now,
                    now,
                    job_id,
                    JobStatus.SUCCEEDED.value,
                    JobStatus.FAILED.value,
                    JobStatus.CANCELED.value,
                ),
            )
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise JobNotFoundError(job_id)
        return _job_from_row(row)

    def retry_safe_job(self, job_id: str) -> RuntimeJob:
        """Requeue one failed job whose latest attempt is explicitly retry-safe."""
        now = _utc_now()
        with self._connect() as connection, _transaction(connection):
            job_row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if job_row is None:
                raise JobNotFoundError(job_id)
            job = _job_from_row(job_row)
            if job.status is not JobStatus.FAILED:
                raise InvalidStateTransitionError(
                    f"only failed jobs can be retried; {job_id} is {job.status.value}"
                )
            attempt_row = connection.execute(
                """
                SELECT * FROM job_attempts
                WHERE job_id = ? ORDER BY attempt_number DESC LIMIT 1
                """,
                (job_id,),
            ).fetchone()
            if attempt_row is None:
                raise InvalidStateTransitionError(
                    f"job {job_id} has no completed attempt to retry"
                )
            attempt = _attempt_from_row(attempt_row)
            if attempt.status not in {
                JobAttemptStatus.FAILED,
                JobAttemptStatus.INTERRUPTED,
            } or not _retry_safe(attempt.idempotency_class):
                raise InvalidStateTransitionError("latest attempt is not safe to retry")
            next_max_attempts = max(job.max_attempts, attempt.attempt_number + 1)
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, available_at = ?, terminal_at = NULL,
                    cancel_requested_at = NULL, max_attempts = ?,
                    error_summary = NULL, updated_at = ?, version = version + 1
                WHERE id = ? AND status = ?
                """,
                (
                    JobStatus.QUEUED.value,
                    now,
                    next_max_attempts,
                    now,
                    job_id,
                    JobStatus.FAILED.value,
                ),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise ConcurrentUpdateError(f"job {job_id} changed concurrently")
            updated = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return _job_from_row(updated)

    def requeue_due_jobs(self) -> int:
        """Move due retry-wait jobs back to the claimable queue."""
        now = _utc_now()
        with self._connect() as connection, _transaction(connection):
            connection.execute(
                """
                UPDATE jobs SET status = ?, updated_at = ?, version = version + 1
                WHERE status = ? AND available_at <= ? AND cancel_requested_at IS NULL
                """,
                (JobStatus.QUEUED.value, now, JobStatus.RETRY_WAIT.value, now),
            )
            return int(connection.execute("SELECT changes()").fetchone()[0])

    def register_worker(
        self,
        *,
        worker_id: str,
        process_id: int,
        hostname: str,
        capability_fingerprint: Mapping[str, Any],
    ) -> RuntimeWorker:
        """Register or refresh a durable worker identity."""
        now = _utc_now()
        with self._connect() as connection, _transaction(connection):
            connection.execute(
                """
                INSERT INTO workers (
                    id, process_id, hostname, status, started_at, heartbeat_at,
                    stopped_at, capability_fingerprint_json
                ) VALUES (?, ?, ?, 'online', ?, ?, NULL, ?)
                ON CONFLICT(id) DO UPDATE SET process_id = excluded.process_id,
                    hostname = excluded.hostname, status = 'online',
                    heartbeat_at = excluded.heartbeat_at, stopped_at = NULL,
                    capability_fingerprint_json = excluded.capability_fingerprint_json
                """,
                (
                    worker_id,
                    process_id,
                    hostname,
                    now,
                    now,
                    _safe_json(capability_fingerprint),
                ),
            )
            row = connection.execute(
                "SELECT * FROM workers WHERE id = ?", (worker_id,)
            ).fetchone()
        return _worker_from_row(row)

    def heartbeat_worker(self, worker_id: str) -> None:
        """Refresh one worker liveness timestamp."""
        with self._connect() as connection, _transaction(connection):
            connection.execute(
                "UPDATE workers SET heartbeat_at = ?, status = 'online' WHERE id = ?",
                (_utc_now(), worker_id),
            )

    def stop_worker(self, worker_id: str) -> None:
        """Mark one worker as cleanly stopped."""
        now = _utc_now()
        with self._connect() as connection, _transaction(connection):
            connection.execute(
                "UPDATE workers SET status = 'stopped', stopped_at = ?, heartbeat_at = ? WHERE id = ?",
                (now, now, worker_id),
            )

    def list_workers(self) -> tuple[RuntimeWorker, ...]:
        """List durable worker records newest first."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM workers ORDER BY heartbeat_at DESC, id"
            ).fetchall()
        return tuple(_worker_from_row(row) for row in rows)

    def create_approval_request(
        self,
        resolution: PolicyResolution,
        context: PolicyContext,
        *,
        expires_at: str | None = None,
    ) -> ApprovalRequest:
        """Create or return one pending request for the same action and scope."""
        if resolution.decision.value != "ask":
            raise ValueError("approval requests require an ask policy resolution")
        now = _utc_now()
        request_id = _new_id("approval")
        scope_identity = "\0".join(
            (
                resolution.action.value,
                context.project_id or "",
                context.session_id or "",
                context.run_id or "",
                context.job_id or "",
            )
        )
        dedupe_key = hashlib.sha256(scope_identity.encode("utf-8")).hexdigest()
        values = (
            request_id,
            resolution.action.value,
            ApprovalStatus.PENDING.value,
            resolution.enforcement.value,
            resolution.policy_source,
            _required_text(context.reason, "approval reason"),
            json.dumps(
                redacted_policy_preview(context.preview),
                ensure_ascii=False,
                sort_keys=True,
            ),
            _optional_text(context.project_id),
            _optional_text(context.session_id),
            _optional_text(context.run_id),
            _optional_text(context.job_id),
            dedupe_key,
            expires_at,
            now,
        )
        with self._connect() as connection, _transaction(connection):
            _expire_approvals(connection, now)
            try:
                connection.execute(
                    """
                    INSERT INTO approval_requests (
                        id, action, status, enforcement, policy_source, reason,
                        preview_json, project_id, session_id, run_id, job_id,
                        dedupe_key, expires_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT * FROM approval_requests
                    WHERE dedupe_key = ? AND status = ?
                    """,
                    (dedupe_key, ApprovalStatus.PENDING.value),
                ).fetchone()
                if row is None:
                    raise
                return _approval_request_from_row(row)
            if context.job_id:
                connection.execute(
                    """
                    UPDATE jobs SET approval_request_id = ?, updated_at = ?,
                        version = version + 1 WHERE id = ?
                    """,
                    (request_id, now, context.job_id),
                )
            row = connection.execute(
                "SELECT * FROM approval_requests WHERE id = ?", (request_id,)
            ).fetchone()
        return _approval_request_from_row(row)

    def get_approval_request(self, request_id: str) -> ApprovalRequest:
        """Return one approval request after applying expiry."""
        now = _utc_now()
        with self._connect() as connection, _transaction(connection):
            _expire_approvals(connection, now)
            row = connection.execute(
                "SELECT * FROM approval_requests WHERE id = ?", (request_id,)
            ).fetchone()
        if row is None:
            raise KeyError(request_id)
        return _approval_request_from_row(row)

    def list_approval_requests(
        self,
        *,
        status: ApprovalStatus | str | None = None,
        limit: int = 100,
    ) -> tuple[ApprovalRequest, ...]:
        """List newest approval inbox items with bounded output."""
        parsed_status = ApprovalStatus(status) if status is not None else None
        page_size = max(1, min(int(limit), 200))
        now = _utc_now()
        with self._connect() as connection, _transaction(connection):
            _expire_approvals(connection, now)
            if parsed_status is None:
                rows = connection.execute(
                    "SELECT * FROM approval_requests ORDER BY created_at DESC, id DESC LIMIT ?",
                    (page_size,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM approval_requests WHERE status = ?
                    ORDER BY created_at DESC, id DESC LIMIT ?
                    """,
                    (parsed_status.value, page_size),
                ).fetchall()
        return tuple(_approval_request_from_row(row) for row in rows)

    def decide_approval_request(
        self,
        request_id: str,
        decision: ApprovalDecision | str,
        *,
        project_expiry_seconds: float | None = None,
    ) -> ApprovalRequest:
        """Persist a decision, optional scoped grant, and pre-spawn job outcome."""
        parsed_decision = ApprovalDecision(decision)
        now = _utc_now()
        with self._connect() as connection, _transaction(connection):
            _expire_approvals(connection, now)
            row = connection.execute(
                "SELECT * FROM approval_requests WHERE id = ?", (request_id,)
            ).fetchone()
            if row is None:
                raise KeyError(request_id)
            request = _approval_request_from_row(row)
            if request.status is not ApprovalStatus.PENDING:
                raise InvalidStateTransitionError(
                    f"approval {request_id} is {request.status.value}"
                )
            grant: tuple[str, str, int | None, str | None] | None = None
            if parsed_decision is ApprovalDecision.ALLOW_ONCE:
                scope_type, scope_id = _approval_once_scope(request)
                grant = (scope_type, scope_id, 1, None)
            elif parsed_decision is ApprovalDecision.ALLOW_RUN:
                if not request.run_id:
                    raise ValueError("run-scoped approval requires a run")
                grant = ("run", request.run_id, None, None)
            elif parsed_decision is ApprovalDecision.ALLOW_PROJECT:
                if not request.project_id:
                    raise ValueError("project-scoped approval requires a project")
                if project_expiry_seconds is None or project_expiry_seconds <= 0:
                    raise ValueError(
                        "project-scoped approval requires a positive expiry"
                    )
                grant = (
                    "project",
                    request.project_id,
                    None,
                    _future_time(project_expiry_seconds),
                )
            status = (
                ApprovalStatus.DENIED
                if parsed_decision is ApprovalDecision.DENY
                else ApprovalStatus.APPROVED
            )
            connection.execute(
                """
                UPDATE approval_requests
                SET status = ?, decision = ?, decided_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    status.value,
                    parsed_decision.value,
                    now,
                    request_id,
                    ApprovalStatus.PENDING.value,
                ),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise ConcurrentUpdateError(
                    f"approval {request_id} changed concurrently"
                )
            if grant is not None:
                scope_type, scope_id, uses_remaining, expires_at = grant
                connection.execute(
                    """
                    INSERT INTO approval_grants (
                        id, request_id, action, scope_type, scope_id,
                        uses_remaining, expires_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _new_id("grant"),
                        request_id,
                        request.action.value,
                        scope_type,
                        scope_id,
                        uses_remaining,
                        expires_at,
                        now,
                    ),
                )
            if request.job_id:
                job_row = connection.execute(
                    "SELECT * FROM jobs WHERE id = ?", (request.job_id,)
                ).fetchone()
                if job_row is not None:
                    job = _job_from_row(job_row)
                    if job.status is JobStatus.WAITING_APPROVAL:
                        target = (
                            JobStatus.CANCELED
                            if parsed_decision is ApprovalDecision.DENY
                            else JobStatus.QUEUED
                        )
                        next_version = job.version + 1
                        connection.execute(
                            """
                            UPDATE jobs SET status = ?, available_at = ?,
                                terminal_at = ?, error_summary = ?, updated_at = ?,
                                approval_request_id = NULL, version = ?
                            WHERE id = ? AND version = ?
                            """,
                            (
                                target.value,
                                now,
                                now if target is JobStatus.CANCELED else None,
                                "approval denied"
                                if target is JobStatus.CANCELED
                                else None,
                                now,
                                next_version,
                                job.id,
                                job.version,
                            ),
                        )
                        if target is JobStatus.CANCELED:
                            self._enqueue_terminal_sync(
                                connection,
                                job_id=job.id,
                                status=target,
                                version=next_version,
                                session_id=job.session_id,
                                attempt=None,
                            )
            updated = connection.execute(
                "SELECT * FROM approval_requests WHERE id = ?", (request_id,)
            ).fetchone()
        return _approval_request_from_row(updated)

    def consume_matching_approval_grant(
        self,
        *,
        action: PermissionAction | str,
        project_id: str | None,
        run_id: str | None,
        job_id: str | None,
    ) -> bool:
        """Consume a matching allow-once grant or observe a scoped grant."""
        parsed_action = PermissionAction(action)
        scopes = [
            ("job", _optional_text(job_id)),
            ("run", _optional_text(run_id)),
            ("project", _optional_text(project_id)),
        ]
        scopes = [(kind, value) for kind, value in scopes if value]
        if not scopes:
            return False
        clauses = " OR ".join("(scope_type = ? AND scope_id = ?)" for _ in scopes)
        params: list[Any] = [parsed_action.value]
        for kind, value in scopes:
            params.extend((kind, value))
        now = _utc_now()
        params.extend((now,))
        with self._connect() as connection, _transaction(connection):
            row = connection.execute(
                f"""
                SELECT * FROM approval_grants
                WHERE action = ? AND ({clauses})
                  AND (expires_at IS NULL OR expires_at > ?)
                  AND (uses_remaining IS NULL OR uses_remaining > 0)
                ORDER BY CASE scope_type WHEN 'job' THEN 0 WHEN 'run' THEN 1 ELSE 2 END,
                         created_at DESC LIMIT 1
                """,
                tuple(params),
            ).fetchone()
            if row is None:
                return False
            if row["uses_remaining"] is not None:
                connection.execute(
                    """
                    UPDATE approval_grants SET uses_remaining = uses_remaining - 1
                    WHERE id = ? AND uses_remaining > 0
                    """,
                    (row["id"],),
                )
                if connection.execute("SELECT changes()").fetchone()[0] != 1:
                    return False
        return True

    def list_approval_grants(self) -> tuple[ApprovalGrant, ...]:
        """List grants for safe runtime inspection and export."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM approval_grants ORDER BY created_at, id"
            ).fetchall()
        return tuple(_approval_grant_from_row(row) for row in rows)

    def transition_attempt(
        self,
        attempt_id: str,
        status: JobAttemptStatus | str,
        *,
        expected_status: JobAttemptStatus | str | None = None,
        process_id: int | None = None,
        error_summary: str | None = None,
    ) -> JobAttempt:
        """Atomically transition one concrete attempt."""
        target = parse_attempt_status(status)
        expected = parse_attempt_status(expected_status) if expected_status else None
        now = _utc_now()
        with self._connect() as connection, _transaction(connection):
            row = connection.execute(
                "SELECT * FROM job_attempts WHERE id = ?", (attempt_id,)
            ).fetchone()
            if row is None:
                raise AttemptNotFoundError(attempt_id)
            current = _attempt_from_row(row)
            if expected is not None and current.status is not expected:
                raise ConcurrentUpdateError(
                    f"attempt {attempt_id} is {current.status.value}, expected {expected.value}"
                )
            if current.status is target:
                return current
            if current.status in TERMINAL_ATTEMPT_STATUSES:
                raise InvalidStateTransitionError(
                    f"terminal attempt {attempt_id} cannot transition to {target.value}"
                )
            started_at = current.started_at or (
                now
                if target in {JobAttemptStatus.STARTING, JobAttemptStatus.RUNNING}
                else None
            )
            finished_at = now if target in TERMINAL_ATTEMPT_STATUSES else None
            next_version = current.version + 1
            connection.execute(
                """
                UPDATE job_attempts
                SET status = ?, started_at = ?, finished_at = ?,
                    process_id = COALESCE(?, process_id), error_summary = ?,
                    updated_at = ?, version = ?
                WHERE id = ? AND version = ?
                """,
                (
                    target.value,
                    started_at,
                    finished_at,
                    process_id,
                    _safe_optional_text(error_summary),
                    now,
                    next_version,
                    attempt_id,
                    current.version,
                ),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise ConcurrentUpdateError(
                    f"attempt {attempt_id} changed concurrently"
                )
            updated = connection.execute(
                "SELECT * FROM job_attempts WHERE id = ?", (attempt_id,)
            ).fetchone()
        return _attempt_from_row(updated)

    def set_attempt_idempotency_class(
        self, attempt_id: str, idempotency_class: str
    ) -> JobAttempt:
        """Record the retry safety class resolved from the immutable payload."""
        value = _required_text(idempotency_class, "idempotency_class")
        with self._connect() as connection, _transaction(connection):
            connection.execute(
                "UPDATE job_attempts SET idempotency_class = ?, updated_at = ?, version = version + 1 WHERE id = ?",
                (value, _utc_now(), attempt_id),
            )
            row = connection.execute(
                "SELECT * FROM job_attempts WHERE id = ?", (attempt_id,)
            ).fetchone()
        if row is None:
            raise AttemptNotFoundError(attempt_id)
        return _attempt_from_row(row)

    def finish_attempt(
        self,
        attempt_id: str,
        status: JobAttemptStatus | str,
        *,
        error_summary: str | None = None,
        retry_delay_seconds: float | None = None,
    ) -> tuple[JobAttempt, RuntimeJob]:
        """Finish an attempt and atomically retry or terminate its logical job."""
        target = parse_attempt_status(status)
        if target not in TERMINAL_ATTEMPT_STATUSES:
            raise ValueError("finish_attempt requires a terminal attempt status")
        now = _utc_now()
        safe_error = _safe_optional_text(error_summary)
        with self._connect() as connection, _transaction(connection):
            attempt_row = connection.execute(
                "SELECT * FROM job_attempts WHERE id = ?", (attempt_id,)
            ).fetchone()
            if attempt_row is None:
                raise AttemptNotFoundError(attempt_id)
            attempt = _attempt_from_row(attempt_row)
            job_row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (attempt.job_id,)
            ).fetchone()
            job = _job_from_row(job_row)
            if attempt.status not in TERMINAL_ATTEMPT_STATUSES:
                connection.execute(
                    """
                    UPDATE job_attempts SET status = ?, finished_at = ?,
                        error_summary = ?, updated_at = ?, version = version + 1
                    WHERE id = ?
                    """,
                    (target.value, now, safe_error, now, attempt.id),
                )
            retryable = (
                target in {JobAttemptStatus.FAILED, JobAttemptStatus.INTERRUPTED}
                and retry_delay_seconds is not None
                and attempt.attempt_number < job.max_attempts
                and _retry_safe(attempt.idempotency_class)
                and job.cancel_requested_at is None
            )
            if retryable:
                job_status = JobStatus.RETRY_WAIT
                available_at = _future_time(max(retry_delay_seconds, 0.0))
                terminal_at = None
            else:
                job_status = {
                    JobAttemptStatus.SUCCEEDED: JobStatus.SUCCEEDED,
                    JobAttemptStatus.CANCELED: JobStatus.CANCELED,
                }.get(target, JobStatus.FAILED)
                available_at = job.available_at
                terminal_at = now
            connection.execute(
                """
                UPDATE jobs SET status = ?, available_at = ?, terminal_at = ?,
                    error_summary = ?, updated_at = ?, version = version + 1
                WHERE id = ?
                """,
                (
                    job_status.value,
                    available_at,
                    terminal_at,
                    safe_error,
                    now,
                    job.id,
                ),
            )
            updated_attempt_row = connection.execute(
                "SELECT * FROM job_attempts WHERE id = ?", (attempt.id,)
            ).fetchone()
            updated_job_row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job.id,)
            ).fetchone()
            if job_status in TERMINAL_JOB_STATUSES:
                self._enqueue_terminal_sync(
                    connection,
                    job_id=job.id,
                    status=job_status,
                    version=int(updated_job_row["version"]),
                    session_id=job.session_id,
                    attempt=_attempt_from_row(updated_attempt_row),
                )
        return _attempt_from_row(updated_attempt_row), _job_from_row(updated_job_row)

    def recover_expired_attempts(
        self, *, retry_delay_seconds: float = 1.0
    ) -> tuple[JobAttempt, ...]:
        """Mark expired leases interrupted and requeue only retry-safe work."""
        now = _utc_now()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM job_attempts
                WHERE status IN (?, ?, ?) AND leased_until IS NOT NULL
                  AND leased_until < ?
                ORDER BY leased_until, id
                """,
                (
                    JobAttemptStatus.CLAIMED.value,
                    JobAttemptStatus.STARTING.value,
                    JobAttemptStatus.RUNNING.value,
                    now,
                ),
            ).fetchall()
        recovered: list[JobAttempt] = []
        for row in rows:
            attempt = _attempt_from_row(row)
            updated, _ = self.finish_attempt(
                attempt.id,
                JobAttemptStatus.INTERRUPTED,
                error_summary="worker lease expired; process adoption was not attempted",
                retry_delay_seconds=retry_delay_seconds,
            )
            recovered.append(updated)
        return tuple(recovered)

    def next_trace_sequence(self, trace_id: str) -> int:
        """Allocate one process-safe monotonically increasing trace sequence."""
        trace_id = _required_text(trace_id, "trace_id")
        with self._connect() as connection, _transaction(connection):
            row = connection.execute(
                "SELECT last_sequence FROM trace_sequences WHERE trace_id = ?",
                (trace_id,),
            ).fetchone()
            sequence = int(row[0]) + 1 if row is not None else 1
            connection.execute(
                """
                INSERT INTO trace_sequences(trace_id, last_sequence) VALUES (?, ?)
                ON CONFLICT(trace_id) DO UPDATE SET last_sequence = excluded.last_sequence
                """,
                (trace_id, sequence),
            )
        return sequence

    def pending_outbox(self, *, limit: int = 100) -> tuple[RuntimeOutboxEntry, ...]:
        """Return unprocessed bridge events."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM runtime_outbox WHERE processed_at IS NULL
                ORDER BY created_at, id LIMIT ?
                """,
                (max(0, limit),),
            ).fetchall()
        return tuple(_outbox_from_row(row) for row in rows)

    def mark_outbox_processed(self, entry_id: str) -> None:
        """Mark one bridge event as successfully applied."""
        with self._connect() as connection, _transaction(connection):
            connection.execute(
                """
                UPDATE runtime_outbox
                SET processed_at = ?, attempt_count = attempt_count + 1,
                    last_error = NULL
                WHERE id = ? AND processed_at IS NULL
                """,
                (_utc_now(), entry_id),
            )

    def record_outbox_failure(self, entry_id: str, error: str) -> None:
        """Record a redacted recovery failure for a later retry."""
        with self._connect() as connection, _transaction(connection):
            connection.execute(
                """
                UPDATE runtime_outbox
                SET attempt_count = attempt_count + 1, last_error = ?
                WHERE id = ? AND processed_at IS NULL
                """,
                (_safe_optional_text(error), entry_id),
            )

    def inspect(self) -> dict[str, Any]:
        """Return safe runtime metadata and row counts."""
        with self._connect() as connection:
            counts = {
                table: int(
                    connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                )
                for table in (
                    "jobs",
                    "job_attempts",
                    "runtime_outbox",
                    "trace_sequences",
                    "workers",
                    "approval_requests",
                    "approval_grants",
                    "workflow_runs",
                    "workflow_step_attempts",
                    "schedule_states",
                    "schedule_occurrences",
                )
            }
            pending = int(
                connection.execute(
                    "SELECT COUNT(*) FROM runtime_outbox WHERE processed_at IS NULL"
                ).fetchone()[0]
            )
            journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
        return {
            "path": str(self.path),
            "schema_version": self.schema_version,
            "journal_mode": journal_mode,
            "counts": counts,
            "pending_outbox": pending,
        }

    def export(self) -> dict[str, Any]:
        """Export coordination state as transparent, task-content-free JSON."""
        with self._connect() as connection:
            outbox_rows = connection.execute(
                "SELECT * FROM runtime_outbox ORDER BY created_at, id"
            ).fetchall()
            sequence_rows = connection.execute(
                "SELECT trace_id, last_sequence FROM trace_sequences ORDER BY trace_id"
            ).fetchall()
            workflow_rows = connection.execute(
                "SELECT * FROM workflow_runs ORDER BY created_at, id"
            ).fetchall()
            workflow_step_rows = connection.execute(
                "SELECT * FROM workflow_step_attempts ORDER BY workflow_run_id, created_at, id"
            ).fetchall()
            schedule_rows = connection.execute(
                "SELECT * FROM schedule_states ORDER BY project_id, schedule_id"
            ).fetchall()
            occurrence_rows = connection.execute(
                "SELECT * FROM schedule_occurrences ORDER BY created_at, id"
            ).fetchall()
        return {
            "schema_version": self.schema_version,
            "exported_at": _utc_now(),
            "jobs": [job_to_dict(job) for job in self.list_jobs()],
            "attempts": [attempt_to_dict(item) for item in self.list_attempts()],
            "workers": [worker_to_dict(item) for item in self.list_workers()],
            "approvals": [
                approval_request_to_dict(item)
                for item in self.list_approval_requests(limit=200)
            ],
            "approval_grants": [
                approval_grant_to_dict(item) for item in self.list_approval_grants()
            ],
            "outbox": [
                outbox_entry_to_dict(_outbox_from_row(row)) for row in outbox_rows
            ],
            "trace_sequences": [
                {"trace_id": str(row[0]), "last_sequence": int(row[1])}
                for row in sequence_rows
            ],
            "workflow_runs": [_safe_workflow_export_row(row) for row in workflow_rows],
            "workflow_step_attempts": [
                _safe_workflow_export_row(row) for row in workflow_step_rows
            ],
            "schedules": [_safe_workflow_export_row(row) for row in schedule_rows],
            "schedule_occurrences": [
                _safe_workflow_export_row(row) for row in occurrence_rows
            ],
        }

    def _enqueue_terminal_sync(
        self,
        connection: sqlite3.Connection,
        *,
        job_id: str,
        status: JobStatus,
        version: int,
        session_id: str,
        attempt: JobAttempt | None,
    ) -> None:
        payload = {
            "job_id": job_id,
            "status": status.value,
            "session_id": session_id,
            "attempt_id": attempt.id if attempt is not None else None,
            "run_id": attempt.run_id if attempt is not None else None,
        }
        connection.execute(
            """
            INSERT OR IGNORE INTO runtime_outbox (
                id, aggregate_type, aggregate_id, event_type, dedupe_key,
                payload_json, created_at
            ) VALUES (?, 'job', ?, 'job_terminal', ?, ?, ?)
            """,
            (
                _new_id("outbox"),
                job_id,
                f"job:{job_id}:terminal:{version}",
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                _utc_now(),
            ),
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.path,
            timeout=SQLITE_TIMEOUT_SECONDS,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(
            f"PRAGMA busy_timeout = {int(SQLITE_TIMEOUT_SECONDS * 1000)}"
        )
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        try:
            yield connection
        finally:
            connection.close()

    def _migrate(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                )
                """
            )
            for version, name, statements in _MIGRATIONS:
                with _transaction(connection):
                    row = connection.execute(
                        "SELECT 1 FROM schema_migrations WHERE version = ?",
                        (version,),
                    ).fetchone()
                    if row is not None:
                        continue
                    for statement in statements:
                        connection.execute(statement)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                        (version, name, _utc_now()),
                    )
                    connection.execute(f"PRAGMA user_version = {version}")


@contextmanager
def _transaction(connection: sqlite3.Connection) -> Iterator[None]:
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()


def _job_from_row(row: sqlite3.Row) -> RuntimeJob:
    return RuntimeJob(
        id=str(row["id"]),
        origin=str(row["origin"]),
        idempotency_key_hash=str(row["idempotency_key_hash"]),
        status=parse_job_status(row["status"]),
        session_id=str(row["session_id"]),
        user_message_id=str(row["user_message_id"]),
        initial_run_id=(
            str(row["initial_run_id"])
            if row["initial_run_id"] is not None
            else f"run_legacy_{row['id']}"
        ),
        project_id=_optional_text(row["project_id"]),
        workflow_id=_optional_text(row["workflow_id"]),
        workflow_version=_optional_text(row["workflow_version"]),
        schedule_id=_optional_text(row["schedule_id"]),
        agent_id=_optional_text(row["agent_id"]),
        available_at=_optional_text(row["available_at"]),
        terminal_at=_optional_text(row["terminal_at"]),
        cancel_requested_at=_optional_text(row["cancel_requested_at"]),
        max_attempts=int(row["max_attempts"]),
        priority=int(row["priority"]),
        version=int(row["version"]),
        error_summary=_optional_text(row["error_summary"]),
        required_harness_id=_optional_text(row["required_harness_id"]),
        required_capability_fingerprint=_json_mapping(row["required_fingerprint_json"]),
        timeout_seconds=(
            float(row["timeout_seconds"])
            if row["timeout_seconds"] is not None
            else None
        ),
        approval_request_id=_optional_text(row["approval_request_id"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _attempt_from_row(row: sqlite3.Row) -> JobAttempt:
    return JobAttempt(
        id=str(row["id"]),
        job_id=str(row["job_id"]),
        attempt_number=int(row["attempt_number"]),
        status=parse_attempt_status(row["status"]),
        run_id=str(row["run_id"]),
        lease_owner=_optional_text(row["lease_owner"]),
        leased_until=_optional_text(row["leased_until"]),
        heartbeat_at=_optional_text(row["heartbeat_at"]),
        started_at=_optional_text(row["started_at"]),
        finished_at=_optional_text(row["finished_at"]),
        process_id=int(row["process_id"]) if row["process_id"] is not None else None,
        process_group_id=(
            int(row["process_group_id"])
            if row["process_group_id"] is not None
            else None
        ),
        retry_reason=_optional_text(row["retry_reason"]),
        idempotency_class=str(row["idempotency_class"]),
        error_summary=_optional_text(row["error_summary"]),
        capability_fingerprint=_json_mapping(row["capability_fingerprint_json"]),
        version=int(row["version"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _outbox_from_row(row: sqlite3.Row) -> RuntimeOutboxEntry:
    payload = json.loads(str(row["payload_json"]))
    return RuntimeOutboxEntry(
        id=str(row["id"]),
        aggregate_type=str(row["aggregate_type"]),
        aggregate_id=str(row["aggregate_id"]),
        event_type=str(row["event_type"]),
        dedupe_key=str(row["dedupe_key"]),
        payload=dict(payload) if isinstance(payload, Mapping) else {},
        created_at=str(row["created_at"]),
        processed_at=_optional_text(row["processed_at"]),
        attempt_count=int(row["attempt_count"]),
        last_error=_optional_text(row["last_error"]),
    )


def _worker_from_row(row: sqlite3.Row) -> RuntimeWorker:
    return RuntimeWorker(
        id=str(row["id"]),
        process_id=int(row["process_id"]),
        hostname=str(row["hostname"]),
        status=str(row["status"]),
        started_at=str(row["started_at"]),
        heartbeat_at=str(row["heartbeat_at"]),
        stopped_at=_optional_text(row["stopped_at"]),
        capability_fingerprint=_json_mapping(row["capability_fingerprint_json"]),
    )


def _approval_request_from_row(row: sqlite3.Row) -> ApprovalRequest:
    preview = json.loads(str(row["preview_json"]))
    return ApprovalRequest(
        id=str(row["id"]),
        action=PermissionAction(str(row["action"])),
        status=ApprovalStatus(str(row["status"])),
        enforcement=EnforcementLevel(str(row["enforcement"])),
        policy_source=str(row["policy_source"]),
        reason=str(row["reason"]),
        preview=dict(preview) if isinstance(preview, Mapping) else {},
        project_id=_optional_text(row["project_id"]),
        session_id=_optional_text(row["session_id"]),
        run_id=_optional_text(row["run_id"]),
        job_id=_optional_text(row["job_id"]),
        decision=(
            ApprovalDecision(str(row["decision"]))
            if row["decision"] is not None
            else None
        ),
        expires_at=_optional_text(row["expires_at"]),
        decided_at=_optional_text(row["decided_at"]),
        created_at=str(row["created_at"]),
    )


def _approval_grant_from_row(row: sqlite3.Row) -> ApprovalGrant:
    return ApprovalGrant(
        id=str(row["id"]),
        request_id=str(row["request_id"]),
        action=PermissionAction(str(row["action"])),
        scope_type=str(row["scope_type"]),
        scope_id=str(row["scope_id"]),
        uses_remaining=(
            int(row["uses_remaining"]) if row["uses_remaining"] is not None else None
        ),
        expires_at=_optional_text(row["expires_at"]),
        created_at=str(row["created_at"]),
    )


def _approval_once_scope(request: ApprovalRequest) -> tuple[str, str]:
    if request.job_id:
        return "job", request.job_id
    if request.run_id:
        return "run", request.run_id
    if request.project_id:
        return "project", request.project_id
    raise ValueError("allow-once approval requires a job, run, or project scope")


def _expire_approvals(connection: sqlite3.Connection, now: str) -> None:
    connection.execute(
        """
        UPDATE approval_requests SET status = ?
        WHERE status = ? AND expires_at IS NOT NULL AND expires_at <= ?
        """,
        (ApprovalStatus.EXPIRED.value, ApprovalStatus.PENDING.value, now),
    )


def _idempotency_hash(value: str) -> str:
    text = _required_text(value, "idempotency_key")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _required_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_optional_text(value: Any) -> str | None:
    text = _optional_text(value)
    if text is None:
        return None
    safe = redact_for_storage(text)
    return str(safe)[:4000]


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _future_time(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _safe_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        redact_for_storage(dict(value)), ensure_ascii=False, sort_keys=True
    )


def _json_mapping(value: Any) -> dict[str, Any]:
    try:
        decoded = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return dict(decoded) if isinstance(decoded, Mapping) else {}


def _safe_workflow_export_row(row: sqlite3.Row) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in row.keys():
        value = row[key]
        if key.endswith("_json"):
            try:
                value = json.loads(str(value))
            except (TypeError, ValueError):
                value = {}
        payload[str(key)] = redact_for_storage(value)
    return payload


def _fingerprint_matches(
    required: Mapping[str, Any],
    worker: Mapping[str, Any],
    *,
    required_harness_id: str | None,
) -> bool:
    worker_harnesses = worker.get("harnesses")
    if not isinstance(worker_harnesses, Mapping):
        return required_harness_id is None and not required
    if required_harness_id is not None:
        worker_harness = worker_harnesses.get(required_harness_id)
        if not isinstance(worker_harness, Mapping) or not bool(
            worker_harness.get("available")
        ):
            return False
    required_os = _optional_text(required.get("os"))
    if required_os is not None and required_os != _optional_text(worker.get("os")):
        return False
    required_harnesses = required.get("harnesses")
    if not isinstance(required_harnesses, Mapping):
        return True
    for harness_id, expected in required_harnesses.items():
        actual = worker_harnesses.get(str(harness_id))
        if not isinstance(expected, Mapping) or not isinstance(actual, Mapping):
            return False
        for key in ("distribution", "binary_version"):
            value = expected.get(key)
            if value is not None and value != actual.get(key):
                return False
        expected_features = expected.get("features")
        actual_features = actual.get("features")
        if isinstance(expected_features, Mapping):
            if not isinstance(actual_features, Mapping):
                return False
            if any(
                bool(value) and not bool(actual_features.get(str(key)))
                for key, value in expected_features.items()
            ):
                return False
    return True


def _retry_safe(value: str) -> bool:
    return value in {"read_only", "safe_retry", "deterministic"}
