"""SQLite coordination store for durable Unified Harness jobs."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator, Mapping
from uuid import uuid4

from gpt2giga.harness.runtime.models import (
    JobAttempt,
    JobAttemptStatus,
    JobStatus,
    JobSubmission,
    RuntimeJob,
    RuntimeOutboxEntry,
    TERMINAL_ATTEMPT_STATUSES,
    TERMINAL_JOB_STATUSES,
    attempt_to_dict,
    job_to_dict,
    outbox_entry_to_dict,
    parse_attempt_status,
    parse_job_status,
)
from gpt2giga.harness.sessions.redaction import redact_for_storage

RUNTIME_DB_NAME = "runtime.sqlite3"
RUNTIME_SCHEMA_VERSION = 2
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
        origin: str = "manual",
        project_id: str | None = None,
        workflow_id: str | None = None,
        workflow_version: str | None = None,
        schedule_id: str | None = None,
        agent_id: str | None = None,
        max_attempts: int = 1,
        priority: int = 0,
        available_at: str | None = None,
    ) -> JobSubmission:
        """Submit one job or return the existing identity-matched job."""
        session_id = _required_text(session_id, "session_id")
        user_message_id = _required_text(user_message_id, "user_message_id")
        origin = _required_text(origin, "origin")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        key_hash = _idempotency_hash(idempotency_key)
        now = _utc_now()
        job_id = _new_id("job")
        values = {
            "id": job_id,
            "origin": origin,
            "idempotency_key_hash": key_hash,
            "status": JobStatus.QUEUED.value,
            "session_id": session_id,
            "user_message_id": user_message_id,
            "project_id": _optional_text(project_id),
            "workflow_id": _optional_text(workflow_id),
            "workflow_version": _optional_text(workflow_version),
            "schedule_id": _optional_text(schedule_id),
            "agent_id": _optional_text(agent_id),
            "available_at": available_at or now,
            "max_attempts": max_attempts,
            "priority": int(priority),
            "created_at": now,
            "updated_at": now,
        }
        with self._connect() as connection, _transaction(connection):
            try:
                connection.execute(
                    """
                    INSERT INTO jobs (
                        id, origin, idempotency_key_hash, status, session_id,
                        user_message_id, project_id, workflow_id, workflow_version,
                        schedule_id, agent_id, available_at, max_attempts, priority,
                        created_at, updated_at
                    ) VALUES (
                        :id, :origin, :idempotency_key_hash, :status, :session_id,
                        :user_message_id, :project_id, :workflow_id, :workflow_version,
                        :schedule_id, :agent_id, :available_at, :max_attempts,
                        :priority, :created_at, :updated_at
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
        return {
            "schema_version": self.schema_version,
            "exported_at": _utc_now(),
            "jobs": [job_to_dict(job) for job in self.list_jobs()],
            "attempts": [attempt_to_dict(item) for item in self.list_attempts()],
            "outbox": [
                outbox_entry_to_dict(_outbox_from_row(row)) for row in outbox_rows
            ],
            "trace_sequences": [
                {"trace_id": str(row[0]), "last_sequence": int(row[1])}
                for row in sequence_rows
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
        retry_reason=_optional_text(row["retry_reason"]),
        idempotency_class=str(row["idempotency_class"]),
        error_summary=_optional_text(row["error_summary"]),
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
