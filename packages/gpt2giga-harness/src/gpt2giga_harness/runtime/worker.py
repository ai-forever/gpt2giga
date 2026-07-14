"""Durable job submission and standalone worker execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import os
import socket
import threading
import time
from typing import Any, Mapping
from uuid import uuid4

from gpt2giga_harness.attachments import FilesystemAttachmentStore
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.project_memory import FilesystemProjectMemoryStore
from gpt2giga_harness.registry import HarnessRegistry, create_default_registry
from gpt2giga_harness.runtime.fingerprint import build_worker_fingerprint
from gpt2giga_harness.runtime.models import (
    JobAttemptStatus,
    RuntimeJob,
)
from gpt2giga_harness.runtime.payloads import DurableJobPayloadStore
from gpt2giga_harness.runtime.policy import (
    EnforcementLevel,
    PermissionAction,
    PolicyContext,
    PolicyDecision,
    PolicyEngine,
    permission_profile,
)
from gpt2giga_harness.runtime.reconcile import RuntimeReconciler
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore
from gpt2giga_harness.session_runner import HarnessSessionRunner, QueuedHarnessRun
from gpt2giga_harness.sessions import FilesystemHarnessSessionStore
from gpt2giga_harness.sessions.locking import exclusive_file_lock
from gpt2giga_harness.sessions.models import HarnessStoredEvent
from gpt2giga_harness.sessions.store import new_id, utc_now
from gpt2giga_harness.types import HarnessEventType

DEFAULT_LEASE_SECONDS = 15.0
DEFAULT_HEARTBEAT_SECONDS = 2.0
DEFAULT_POLL_SECONDS = 0.25
DEFAULT_RETRY_BACKOFF_SECONDS = 1.0


@dataclass(frozen=True)
class DurableSubmission:
    """Queued job plus the first run visible to existing UI clients."""

    job: RuntimeJob
    queued: QueuedHarnessRun
    created: bool


class DurableJobDispatcher:
    """Prepare one logical message/run and submit durable coordination state."""

    def __init__(
        self,
        *,
        runtime_store: RuntimeCoordinationStore,
        payload_store: DurableJobPayloadStore,
        runner: HarnessSessionRunner,
    ) -> None:
        self.runtime_store = runtime_store
        self.payload_store = payload_store
        self.runner = runner
        self.submitter_fingerprint = build_worker_fingerprint(runner.registry)
        self.policy_engine = PolicyEngine(runtime_store)

    def submit(
        self,
        session_id: str,
        payload: Mapping[str, Any],
        *,
        idempotency_key: str,
        origin: str = "manual",
    ) -> DurableSubmission:
        """Submit a durable job through the selected permission profile."""
        selected_profile = permission_profile(
            payload.get("permission_profile"), origin=origin
        )
        if (
            origin not in {"manual", "interactive"}
            and selected_profile.id != "unattended"
        ):
            raise ValueError(
                "unattended durable jobs require the unattended policy profile"
            )
        digest = hashlib.sha256(f"{origin}\0{idempotency_key}".encode()).hexdigest()
        lock_target = self.payload_store.root / "idempotency" / digest
        with exclusive_file_lock(lock_target):
            return self._submit_locked(
                session_id,
                payload,
                idempotency_key=idempotency_key,
                origin=origin,
            )

    def _submit_locked(
        self,
        session_id: str,
        payload: Mapping[str, Any],
        *,
        idempotency_key: str,
        origin: str,
    ) -> DurableSubmission:
        existing = self.runtime_store.find_job_by_idempotency(
            origin=origin, idempotency_key=idempotency_key
        )
        if existing is not None:
            run = self.runner.store.get_run(existing.initial_run_id)
            session = self.runner.store.get_session(existing.session_id)
            messages = self.runner.store.list_messages(existing.session_id)
            message = next(
                item for item in messages if item.id == existing.user_message_id
            )
            return DurableSubmission(
                job=existing,
                queued=QueuedHarnessRun(session=session, run=run, user_message=message),
                created=False,
            )
        run_id = new_id("run")
        queued = self.runner.enqueue_in_session(session_id, payload, run_id=run_id)
        harness_id = queued.run.harness_id
        timeout_seconds = _positive_float(
            payload.get("timeout_seconds"), self.runner.config.timeout_seconds
        )
        max_attempts = max(int(payload.get("max_attempts") or 1), 1)
        submission = self.runtime_store.submit_job(
            session_id=session_id,
            user_message_id=queued.user_message.id,
            initial_run_id=queued.run.id,
            idempotency_key=idempotency_key,
            origin=origin,
            project_id=str(queued.session.metadata.get("project_id") or "") or None,
            workflow_id=str(payload.get("workflow_id") or "") or None,
            workflow_version=str(payload.get("workflow_version") or "") or None,
            schedule_id=str(payload.get("schedule_id") or "") or None,
            agent_id=str(payload.get("agent_id") or "") or None,
            max_attempts=max_attempts,
            required_harness_id=harness_id,
            required_capability_fingerprint=_job_fingerprint_requirement(
                self.submitter_fingerprint, harness_id
            ),
            timeout_seconds=timeout_seconds,
            initial_status="waiting_input",
        )
        persisted_payload = dict(payload)
        managed_mcp_snapshot = queued.run.metadata.get("managed_mcp_snapshot")
        if isinstance(managed_mcp_snapshot, Mapping):
            extra = (
                dict(persisted_payload["extra"])
                if isinstance(persisted_payload.get("extra"), Mapping)
                else {}
            )
            extra["managed_mcp_snapshot"] = dict(managed_mcp_snapshot)
            extra["tool_ids"] = list(managed_mcp_snapshot.get("server_ids") or ())
            persisted_payload["extra"] = extra
        self.payload_store.save(submission.job.id, persisted_payload)
        selected_profile = permission_profile(
            payload.get("permission_profile"), origin=origin
        )
        action = (
            PermissionAction.SCHEDULE_UNATTENDED_EDIT
            if origin == "scheduled" and str(payload.get("mode") or "plan") == "edit"
            else PermissionAction.PROCESS_SPAWN
        )
        context = PolicyContext(
            project_id=str(queued.session.metadata.get("project_id") or "") or None,
            session_id=session_id,
            run_id=queued.run.id,
            job_id=submission.job.id,
            reason=(
                "Start an unattended scheduled edit in an isolated worktree."
                if action is PermissionAction.SCHEDULE_UNATTENDED_EDIT
                else "Start a durable harness process."
            ),
            preview={
                "harness_id": harness_id,
                "mode": payload.get("mode") or "plan",
                "workspace": payload.get("workspace"),
                "origin": origin,
            },
        )
        resolution = self.policy_engine.resolve(
            action,
            profile=selected_profile,
            context=context,
            enforcement=EnforcementLevel.ENFORCED_BY_HARNESS,
        )
        approval = None
        if resolution.decision is PolicyDecision.ALLOW:
            ready_job = self.runtime_store.transition_job(
                submission.job.id,
                "queued",
                expected_status="waiting_input",
            )
            event_type = "job_queued"
            event_message = "Durable harness job queued."
            span_status = "queued"
        elif resolution.decision is PolicyDecision.ASK:
            ready_job = self.runtime_store.transition_job(
                submission.job.id,
                "waiting_approval",
                expected_status="waiting_input",
            )
            approval = self.runtime_store.create_approval_request(resolution, context)
            ready_job = self.runtime_store.get_job(ready_job.id)
            event_type = "approval_requested"
            event_message = "Durable harness job is waiting for process approval."
            span_status = "waiting_approval"
        else:
            ready_job = self.runtime_store.transition_job(
                submission.job.id,
                "canceled",
                expected_status="waiting_input",
                error_summary="process spawn denied by policy",
            )
            approval = None
            event_type = "policy_denied"
            event_message = "Durable harness job was denied by policy."
            span_status = "canceled"
        run = self.runner.store.update_run(
            queued.run.id,
            metadata={
                **dict(queued.run.metadata),
                "runtime": {
                    "job_id": ready_job.id,
                    "attempt_number": 0,
                    "workflow_id": ready_job.workflow_id,
                    "workflow_version": ready_job.workflow_version,
                    "workflow_step_id": payload.get("workflow_step_id"),
                },
            },
        )
        self.runner.store.append_event(
            HarnessStoredEvent(
                id=new_id("evt"),
                session_id=session_id,
                run_id=run.id,
                type=event_type,
                message=event_message,
                payload={
                    "job_id": ready_job.id,
                    "action": action.value,
                    "policy_source": resolution.policy_source,
                    "enforcement": resolution.enforcement.value,
                    "approval_id": approval.id if approval is not None else None,
                },
                created_at=utc_now(),
                trace_id=ready_job.id,
                job_id=ready_job.id,
                span_kind="approval" if approval is not None else "run",
                span_status=span_status,
            )
        )
        return DurableSubmission(
            job=ready_job,
            queued=QueuedHarnessRun(
                session=queued.session, run=run, user_message=queued.user_message
            ),
            created=submission.created,
        )


class DurableJobWorker:
    """Claim and execute durable headless jobs independently from the UI server."""

    def __init__(
        self,
        config: HarnessConfig,
        *,
        registry: HarnessRegistry | None = None,
        worker_id: str | None = None,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
        heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
    ) -> None:
        self.config = config.with_overrides(auto_start_proxy=False)
        self.registry = registry or create_default_registry()
        self.worker_id = (
            worker_id
            or f"worker_{socket.gethostname()}_{os.getpid()}_{uuid4().hex[:8]}"
        )
        self.lease_seconds = max(lease_seconds, 1.0)
        self.heartbeat_seconds = max(heartbeat_seconds, 0.1)
        self.runtime_store = RuntimeCoordinationStore(self.config.data_dir)
        self.session_store = FilesystemHarnessSessionStore(self.config.data_dir)
        self.payload_store = DurableJobPayloadStore(self.config.data_dir)
        self.runner = HarnessSessionRunner(
            registry=self.registry,
            config=self.config,
            store=self.session_store,
            attachment_store=FilesystemAttachmentStore(self.config.data_dir),
            memory_store=FilesystemProjectMemoryStore(),
        )
        self.fingerprint = build_worker_fingerprint(self.registry)
        self._registered = False

    def run_once(self) -> bool:
        """Claim and execute at most one job; return whether work was claimed."""
        self._register()
        self.runtime_store.heartbeat_worker(self.worker_id)
        self._trigger_schedules()
        self.runtime_store.recover_expired_attempts()
        self.runtime_store.requeue_due_jobs()
        RuntimeReconciler(self.runtime_store, self.session_store).reconcile()
        claim = self.runtime_store.claim_next_job(
            worker_id=self.worker_id,
            capability_fingerprint=self.fingerprint,
            lease_seconds=self.lease_seconds,
        )
        if claim is None:
            return False
        attempt = claim.attempt
        job = claim.job
        payload = self.payload_store.load(job.id)
        execution_payload = _worker_execution_payload(payload, self.fingerprint)
        idempotency_class = _idempotency_class(payload)
        attempt = self.runtime_store.set_attempt_idempotency_class(
            attempt.id, idempotency_class
        )
        self.runtime_store.transition_attempt(
            attempt.id,
            JobAttemptStatus.RUNNING,
            expected_status=JobAttemptStatus.CLAIMED,
        )
        self.payload_store.append_attempt_log(
            attempt.id,
            {"at": utc_now(), "type": "attempt_started", "worker_id": self.worker_id},
        )
        cancel_event = threading.Event()
        finished = threading.Event()
        timed_out = threading.Event()
        monitor = threading.Thread(
            target=self._monitor_attempt,
            args=(job, attempt.id, cancel_event, finished, timed_out),
            name=f"gpt2giga-{attempt.id}-heartbeat",
            daemon=True,
        )
        monitor.start()
        try:
            result = self.runner.run_in_session(
                job.session_id,
                execution_payload,
                cancel_event=cancel_event,
                existing_run_id=attempt.run_id,
                user_message_id=job.user_message_id,
                excluded_history_run_ids=tuple(
                    item.run_id
                    for item in self.runtime_store.list_attempts(job.id)
                    if item.id != attempt.id
                ),
                runtime_metadata={
                    "job_id": job.id,
                    "attempt_id": attempt.id,
                    "attempt_number": attempt.attempt_number,
                    "worker_id": self.worker_id,
                    "capability_fingerprint": self.fingerprint,
                },
                process_sink=lambda process: self._record_process(attempt.id, process),
            )
        except Exception as exc:
            error = str(exc)
            final_run = self._ensure_failed_run(job, attempt.run_id, payload, error)
            terminal = JobAttemptStatus.FAILED
            result_text = ""
        else:
            error = result.run.error
            self._append_process_output(attempt.id, result.result.raw)
            if timed_out.is_set():
                error = f"job timed out after {job.timeout_seconds} seconds"
                self.session_store.update_run(
                    result.run.id, status="failed", error=error, finished_at=utc_now()
                )
                terminal = JobAttemptStatus.FAILED
            elif result.run.status.value == "succeeded":
                terminal = JobAttemptStatus.SUCCEEDED
            elif result.run.status.value == "canceled":
                terminal = JobAttemptStatus.CANCELED
            else:
                terminal = JobAttemptStatus.FAILED
            result_text = result.result.text
            final_run = self.session_store.get_run(attempt.run_id)
        finally:
            finished.set()
            monitor.join(timeout=self.heartbeat_seconds * 2)
        if final_run is not None:
            self._sync_parent_records(execution_payload, final_run, result_text)
        retry_delay = (
            DEFAULT_RETRY_BACKOFF_SECONDS * (2 ** (attempt.attempt_number - 1))
            if final_run is not None
            and terminal in {JobAttemptStatus.FAILED, JobAttemptStatus.INTERRUPTED}
            else None
        )
        _, updated_job = self.runtime_store.finish_attempt(
            attempt.id,
            terminal,
            error_summary=error,
            retry_delay_seconds=retry_delay,
            sync_terminal_run=final_run is not None,
        )
        self.payload_store.append_attempt_log(
            attempt.id,
            {
                "at": utc_now(),
                "type": "attempt_finished",
                "status": terminal.value,
                "job_status": updated_job.status.value,
                "error": error,
            },
        )
        RuntimeReconciler(self.runtime_store, self.session_store).reconcile()
        self._advance_parent_workflow(updated_job)
        return True

    def _trigger_schedules(self) -> None:
        """Materialize due schedule occurrences before claiming normal work."""
        from gpt2giga_harness.evals import FilesystemHarnessEvalStore
        from gpt2giga_harness.schedules import ScheduleService

        dispatcher = DurableJobDispatcher(
            runtime_store=self.runtime_store,
            payload_store=self.payload_store,
            runner=self.runner,
        )
        ScheduleService(
            runtime_store=self.runtime_store,
            runner=self.runner,
            dispatcher=dispatcher,
            eval_store=FilesystemHarnessEvalStore(self.config.data_dir),
        ).tick()

    def run_forever(
        self,
        *,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        stop_on_idle_seconds: float | None = None,
    ) -> None:
        """Poll until interrupted or an optional idle deadline expires."""
        idle_since = time.monotonic()
        try:
            while True:
                if self.run_once():
                    idle_since = time.monotonic()
                    continue
                if (
                    stop_on_idle_seconds is not None
                    and time.monotonic() - idle_since >= stop_on_idle_seconds
                ):
                    return
                time.sleep(max(poll_seconds, 0.05))
        finally:
            if self._registered:
                self.runtime_store.stop_worker(self.worker_id)

    def _register(self) -> None:
        if self._registered:
            return
        self.runtime_store.register_worker(
            worker_id=self.worker_id,
            process_id=os.getpid(),
            hostname=socket.gethostname(),
            capability_fingerprint=self.fingerprint,
        )
        self._registered = True

    def _monitor_attempt(
        self,
        job: RuntimeJob,
        attempt_id: str,
        cancel_event: threading.Event,
        finished: threading.Event,
        timed_out: threading.Event,
    ) -> None:
        started = time.monotonic()
        while not finished.wait(self.heartbeat_seconds):
            current = self.runtime_store.get_job(job.id)
            if current.cancel_requested_at is not None:
                cancel_event.set()
            if (
                job.timeout_seconds is not None
                and time.monotonic() - started >= job.timeout_seconds
            ):
                timed_out.set()
                cancel_event.set()
            self.runtime_store.heartbeat_attempt(
                attempt_id,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
            )
            self.runtime_store.heartbeat_worker(self.worker_id)

    def _record_process(self, attempt_id: str, process: Mapping[str, Any]) -> None:
        process_id = int(process["process_id"])
        group = process.get("process_group_id")
        self.runtime_store.update_attempt_process(
            attempt_id,
            process_id=process_id,
            process_group_id=int(group) if group is not None else None,
        )
        self.payload_store.append_attempt_log(
            attempt_id,
            {
                "at": utc_now(),
                "type": "process_started",
                "process_id": process_id,
                "process_group_id": group,
            },
        )

    def _append_process_output(self, attempt_id: str, raw: Mapping[str, Any]) -> None:
        stdout = raw.get("stdout")
        stderr = raw.get("stderr")
        if stdout is None and stderr is None:
            return
        self.payload_store.append_attempt_log(
            attempt_id,
            {
                "at": utc_now(),
                "type": "process_output",
                "stdout": str(stdout or ""),
                "stderr": str(stderr or ""),
            },
        )

    def _ensure_failed_run(
        self,
        job: RuntimeJob,
        run_id: str,
        payload: Mapping[str, Any],
        error: str,
    ) -> Any | None:
        try:
            run = self.session_store.get_run(run_id)
        except KeyError:
            try:
                session = self.session_store.get_session(job.session_id)
            except KeyError:
                return None
            run = self.session_store.create_run(
                run_id=run_id,
                session_id=job.session_id,
                harness_id=str(payload.get("harness_id") or session.default_harness_id),
                prompt=str(payload.get("prompt") or ""),
                model=payload.get("model"),
                api_mode=session.default_api_mode,
                capability=self.registry.get(
                    str(payload.get("harness_id") or session.default_harness_id)
                )
                .spec()
                .capabilities[0],
                mode=str(payload.get("mode") or "plan"),
                workspace=session.workspace,
                status="failed",
                metadata={"runtime": {"job_id": job.id}},
            )
        self.session_store.update_run(
            run.id, status="failed", error=error, finished_at=utc_now()
        )
        self.session_store.append_event(
            HarnessStoredEvent(
                id=new_id("evt"),
                session_id=job.session_id,
                run_id=run.id,
                type=HarnessEventType.ERROR.value,
                message="Durable worker failed before harness completion.",
                payload={"error": error},
                created_at=utc_now(),
                job_id=job.id,
            )
        )
        return run

    def _sync_parent_records(
        self, payload: Mapping[str, Any], run: Any, result_text: str
    ) -> None:
        from gpt2giga_harness.arena import sync_durable_arena_child
        from gpt2giga_harness.evals import sync_durable_eval_case

        sync_durable_arena_child(self.config.data_dir, payload, run, result_text)
        sync_durable_eval_case(self.config.data_dir, payload, run, result_text)

    def _advance_parent_workflow(self, job: RuntimeJob) -> None:
        """Advance a parent workflow after one durable child settles."""
        if not job.workflow_id:
            return
        from gpt2giga_harness.project import resolve_project
        from gpt2giga_harness.workflows import WorkflowCoordinator, WorkflowRepository

        try:
            workflow_run = WorkflowRepository(self.runtime_store).get_run(
                job.workflow_id
            )
        except KeyError:
            return
        project = resolve_project(
            workflow_run.project_root, data_dir=self.config.data_dir
        )
        dispatcher = DurableJobDispatcher(
            runtime_store=self.runtime_store,
            payload_store=self.payload_store,
            runner=self.runner,
        )
        WorkflowCoordinator(
            project=project,
            runtime_store=self.runtime_store,
            runner=self.runner,
            dispatcher=dispatcher,
        ).advance(job.workflow_id)


def worker_status(
    store: RuntimeCoordinationStore, *, stale_after: float = 30.0
) -> dict[str, Any]:
    """Return a JSON-ready worker status snapshot."""
    now = time.time()
    workers = []
    for worker in store.list_workers():
        try:
            heartbeat = datetime.fromisoformat(worker.heartbeat_at).timestamp()
        except ValueError:
            heartbeat = 0.0
        effective = (
            "offline"
            if worker.status == "online" and now - heartbeat > stale_after
            else worker.status
        )
        workers.append(
            {
                "id": worker.id,
                "process_id": worker.process_id,
                "hostname": worker.hostname,
                "status": effective,
                "started_at": worker.started_at,
                "heartbeat_at": worker.heartbeat_at,
                "stopped_at": worker.stopped_at,
                "capability_fingerprint": dict(worker.capability_fingerprint),
            }
        )
    return {
        "workers": workers,
        "online": sum(item["status"] == "online" for item in workers),
    }


def _idempotency_class(payload: Mapping[str, Any]) -> str:
    mode = str(payload.get("mode") or "plan")
    return "read_only" if mode in {"plan", "read"} else "external_write"


def _positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _job_fingerprint_requirement(
    fingerprint: Mapping[str, Any], harness_id: str
) -> dict[str, Any]:
    harnesses = fingerprint.get("harnesses")
    harness = harnesses.get(harness_id) if isinstance(harnesses, Mapping) else None
    return {
        "os": fingerprint.get("os"),
        "harnesses": {
            harness_id: dict(harness) if isinstance(harness, Mapping) else {}
        },
    }


def _worker_execution_payload(
    payload: Mapping[str, Any], fingerprint: Mapping[str, Any]
) -> dict[str, Any]:
    prepared = dict(payload)
    harness_id = str(payload.get("harness_id") or "")
    harnesses = fingerprint.get("harnesses")
    harness = harnesses.get(harness_id) if isinstance(harnesses, Mapping) else None
    features = harness.get("features") if isinstance(harness, Mapping) else None
    if isinstance(features, Mapping) and bool(features.get("streaming")):
        prepared["stream"] = True
    return prepared
