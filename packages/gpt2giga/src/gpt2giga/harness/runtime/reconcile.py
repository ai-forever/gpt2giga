"""Recovery bridge between SQLite coordination and JSONL run history."""

from __future__ import annotations

from dataclasses import dataclass

from gpt2giga.harness.runtime.models import (
    JobAttempt,
    JobAttemptStatus,
    JobStatus,
    RunStatus,
    TERMINAL_ATTEMPT_STATUSES,
    TERMINAL_JOB_STATUSES,
    TERMINAL_RUN_STATUSES,
    parse_run_status,
)
from gpt2giga.harness.runtime.store import RuntimeCoordinationStore
from gpt2giga.harness.sessions.models import HarnessStoredEvent
from gpt2giga.harness.sessions.store import (
    HarnessSessionStore,
    RunNotFoundError,
    utc_now,
)

_RUN_TO_JOB_STATUS = {
    RunStatus.SUCCEEDED: JobStatus.SUCCEEDED,
    RunStatus.FAILED: JobStatus.FAILED,
    RunStatus.CANCELED: JobStatus.CANCELED,
}
_JOB_TO_RUN_STATUS = {
    JobStatus.SUCCEEDED: RunStatus.SUCCEEDED,
    JobStatus.FAILED: RunStatus.FAILED,
    JobStatus.CANCELED: RunStatus.CANCELED,
}
_RUN_TO_ATTEMPT_STATUS = {
    RunStatus.SUCCEEDED: JobAttemptStatus.SUCCEEDED,
    RunStatus.FAILED: JobAttemptStatus.FAILED,
    RunStatus.CANCELED: JobAttemptStatus.CANCELED,
}
_JOB_TO_ATTEMPT_STATUS = {
    JobStatus.SUCCEEDED: JobAttemptStatus.SUCCEEDED,
    JobStatus.FAILED: JobAttemptStatus.FAILED,
    JobStatus.CANCELED: JobAttemptStatus.CANCELED,
}


@dataclass(frozen=True)
class RuntimeReconciliationReport:
    """Summary of one startup recovery pass."""

    runs_scanned: int = 0
    jobs_repaired: int = 0
    attempts_repaired: int = 0
    outbox_processed: int = 0
    outbox_failed: int = 0


class RuntimeReconciler:
    """Idempotently repair cross-store terminal state after crash windows."""

    def __init__(
        self,
        runtime_store: RuntimeCoordinationStore,
        session_store: HarnessSessionStore,
    ) -> None:
        self.runtime_store = runtime_store
        self.session_store = session_store

    def reconcile(self) -> RuntimeReconciliationReport:
        """Repair run-to-job state, then drain the transactional outbox."""
        runs_scanned = 0
        jobs_repaired = 0
        attempts_repaired = 0
        for attempt in self.runtime_store.list_attempts():
            try:
                run = self.session_store.get_run(attempt.run_id)
            except RunNotFoundError:
                continue
            runs_scanned += 1
            run_status = parse_run_status(run.status)
            if run_status not in TERMINAL_RUN_STATUSES:
                continue
            expected_attempt = _RUN_TO_ATTEMPT_STATUS[run_status]
            attempt_was_terminal = attempt.status in TERMINAL_ATTEMPT_STATUSES
            if attempt.status not in TERMINAL_ATTEMPT_STATUSES:
                self.runtime_store.transition_attempt(attempt.id, expected_attempt)
                attempts_repaired += 1
            job = self.runtime_store.get_job(attempt.job_id)
            retry_is_pending = attempt_was_terminal and job.status in {
                JobStatus.RETRY_WAIT,
                JobStatus.QUEUED,
            }
            if job.status not in TERMINAL_JOB_STATUSES and not retry_is_pending:
                self.runtime_store.transition_job(
                    job.id,
                    _RUN_TO_JOB_STATUS[run_status],
                    error_summary=run.error,
                )
                jobs_repaired += 1

        processed = 0
        failed = 0
        for entry in self.runtime_store.pending_outbox(limit=1000):
            try:
                self._apply_outbox_entry(
                    entry.id, entry.event_type, dict(entry.payload)
                )
            except Exception as exc:  # recovery must leave the entry retryable
                self.runtime_store.record_outbox_failure(entry.id, str(exc))
                failed += 1
            else:
                self.runtime_store.mark_outbox_processed(entry.id)
                processed += 1
        return RuntimeReconciliationReport(
            runs_scanned=runs_scanned,
            jobs_repaired=jobs_repaired,
            attempts_repaired=attempts_repaired,
            outbox_processed=processed,
            outbox_failed=failed,
        )

    def _apply_outbox_entry(
        self,
        entry_id: str,
        event_type: str,
        payload: dict[str, object],
    ) -> None:
        if event_type != "job_terminal":
            raise ValueError(f"unsupported runtime outbox event: {event_type}")
        job_id = str(payload["job_id"])
        job = self.runtime_store.get_job(job_id)
        if job.status not in TERMINAL_JOB_STATUSES:
            raise ValueError(f"job {job_id} is not terminal")
        attempt = self._attempt_for_payload(job_id, payload.get("attempt_id"))
        run_id = str(payload.get("run_id") or (attempt.run_id if attempt else ""))
        if not run_id:
            return
        run = self.session_store.get_run(run_id)
        target_run_status = _JOB_TO_RUN_STATUS[job.status]
        if run.status is not target_run_status:
            run = self.session_store.update_run(
                run.id,
                status=target_run_status,
                finished_at=run.finished_at or utc_now(),
                error=(run.error if target_run_status is RunStatus.FAILED else None),
            )
        if attempt is not None and attempt.status not in TERMINAL_ATTEMPT_STATUSES:
            self.runtime_store.transition_attempt(
                attempt.id,
                _JOB_TO_ATTEMPT_STATUS[job.status],
                error_summary=run.error,
            )
        self._append_recovery_event(entry_id, job_id, attempt, run.session_id, run.id)

    def _attempt_for_payload(
        self,
        job_id: str,
        attempt_id: object,
    ) -> JobAttempt | None:
        if attempt_id:
            return self.runtime_store.get_attempt(str(attempt_id))
        attempts = self.runtime_store.list_attempts(job_id)
        return attempts[-1] if attempts else None

    def _append_recovery_event(
        self,
        entry_id: str,
        job_id: str,
        attempt: JobAttempt | None,
        session_id: str,
        run_id: str,
    ) -> None:
        event_id = f"evt_{entry_id}"
        existing = self.session_store.list_events(session_id, run_id=run_id)
        if any(event.id == event_id for event in existing):
            return
        trace_id = f"trace_{job_id}"
        self.session_store.append_event(
            HarnessStoredEvent(
                id=event_id,
                session_id=session_id,
                run_id=run_id,
                type="runtime_reconciled",
                message="Recovered terminal runtime state after restart.",
                payload={
                    "job_id": job_id,
                    "attempt_id": attempt.id if attempt else None,
                },
                created_at=utc_now(),
                trace_id=trace_id,
                span_id=f"span_{attempt.id}" if attempt else f"span_{job_id}",
                sequence=self.runtime_store.next_trace_sequence(trace_id),
                job_id=job_id,
                attempt_id=attempt.id if attempt else None,
                span_kind="run",
                span_status="reconciled",
            )
        )
