import concurrent.futures
import hashlib
import json
import sqlite3
import threading

import pytest

from gpt2giga_harness import cli
from gpt2giga_harness.harnesses.codex_cli import CodexCliHarness
from gpt2giga_harness.harnesses.echo import EchoHarness
from gpt2giga_harness.runtime.capabilities import negotiate_execution_capabilities
from gpt2giga_harness.runtime.models import (
    JobAttemptStatus,
    JobStatus,
    RunStatus,
)
from gpt2giga_harness.runtime.reconcile import RuntimeReconciler
from gpt2giga_harness.runtime.store import (
    RUNTIME_SCHEMA_VERSION,
    ConcurrentUpdateError,
    IdempotencyConflictError,
    RuntimeCoordinationStore,
    _MIGRATIONS,
)
from gpt2giga_harness.sessions import FilesystemHarnessSessionStore
from gpt2giga_harness.sessions.models import (
    HarnessStoredEvent,
    event_from_dict,
    event_to_dict,
    run_from_dict,
    run_to_dict,
)
from gpt2giga_harness.types import GigaChatApiMode, HarnessCapability


def test_runtime_store_uses_wal_hashed_idempotency_and_safe_json_export(tmp_path):
    store = RuntimeCoordinationStore(tmp_path)

    first = store.submit_job(
        session_id="sess_1",
        user_message_id="msg_1",
        idempotency_key="private-submit-key",
        project_id="proj_1",
        workflow_id="flow_1",
        workflow_version="v3",
        schedule_id="schedule_1",
        agent_id="agent_1",
    )
    repeated = store.submit_job(
        session_id="sess_1",
        user_message_id="msg_1",
        idempotency_key="private-submit-key",
        project_id="proj_1",
        workflow_id="flow_1",
        workflow_version="v3",
        schedule_id="schedule_1",
        agent_id="agent_1",
    )

    assert first.created is True
    assert repeated.created is False
    assert repeated.job == first.job
    assert first.job.idempotency_key_hash != "private-submit-key"
    assert len(first.job.idempotency_key_hash) == 64
    assert store.inspect()["journal_mode"] == "wal"
    assert store.inspect()["schema_version"] == RUNTIME_SCHEMA_VERSION
    exported = store.export()
    assert exported["jobs"][0]["workflow_version"] == "v3"
    assert "private-submit-key" not in json.dumps(exported)
    assert "prompt" not in exported["jobs"][0]


def test_runtime_store_rejects_idempotency_key_rebinding(tmp_path):
    store = RuntimeCoordinationStore(tmp_path)
    store.submit_job(
        session_id="sess_1",
        user_message_id="msg_1",
        idempotency_key="same-key",
    )

    with pytest.raises(IdempotencyConflictError):
        store.submit_job(
            session_id="sess_2",
            user_message_id="msg_2",
            idempotency_key="same-key",
        )


def test_runtime_store_allocates_attempt_and_trace_identity_concurrently(tmp_path):
    store = RuntimeCoordinationStore(tmp_path)
    job = store.submit_job(
        session_id="sess_1",
        user_message_id="msg_1",
        idempotency_key="attempts",
        max_attempts=2,
    ).job
    first = store.create_attempt(job.id, run_id="run_1")
    store.transition_attempt(first.id, JobAttemptStatus.FAILED)
    second = store.create_attempt(
        job.id,
        run_id="run_2",
        retry_reason="transient",
        idempotency_class="safe_retry",
    )

    assert first.attempt_number == 1
    assert second.attempt_number == 2
    assert first.run_id != second.run_id

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        sequences = list(executor.map(store.next_trace_sequence, ["trace_1"] * 80))

    assert sorted(sequences) == list(range(1, 81))


def test_interactive_jobs_are_claimed_fifo_per_session(tmp_path):
    store = RuntimeCoordinationStore(tmp_path)
    first = store.submit_job(
        session_id="sess_1",
        user_message_id="msg_1",
        idempotency_key="interactive-first",
        origin="interactive",
    ).job
    second = store.submit_job(
        session_id="sess_1",
        user_message_id="msg_2",
        idempotency_key="interactive-second",
        origin="interactive",
    ).job
    fingerprint = {"harnesses": {}}

    first_claim = store.claim_next_job(
        worker_id="worker_1",
        capability_fingerprint=fingerprint,
        lease_seconds=5,
    )
    blocked_claim = store.claim_next_job(
        worker_id="worker_2",
        capability_fingerprint=fingerprint,
        lease_seconds=5,
    )

    assert first_claim is not None
    assert first_claim.job.id == first.id
    assert blocked_claim is None

    store.request_cancel(first.id)
    assert (
        store.claim_next_job(
            worker_id="worker_2",
            capability_fingerprint=fingerprint,
            lease_seconds=5,
        )
        is None
    )

    store.transition_attempt(
        first_claim.attempt.id,
        JobAttemptStatus.CANCELED,
        expected_status=JobAttemptStatus.CLAIMED,
    )
    store.transition_job(
        first.id,
        JobStatus.CANCELED,
        expected_status=JobStatus.RUNNING,
    )
    second_claim = store.claim_next_job(
        worker_id="worker_2",
        capability_fingerprint=fingerprint,
        lease_seconds=5,
    )

    assert second_claim is not None
    assert second_claim.job.id == second.id


def test_runtime_store_terminal_transition_is_compare_and_swap(tmp_path):
    store = RuntimeCoordinationStore(tmp_path)
    job = store.submit_job(
        session_id="sess_1",
        user_message_id="msg_1",
        idempotency_key="terminal-race",
    ).job
    store.create_attempt(job.id, run_id="run_1")
    barrier = threading.Barrier(2)

    def finish(status):
        barrier.wait()
        return store.transition_job(
            job.id,
            status,
            expected_status=JobStatus.RUNNING,
        )

    outcomes = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(finish, JobStatus.SUCCEEDED),
            executor.submit(finish, JobStatus.FAILED),
        ]
        for future in futures:
            try:
                outcomes.append(future.result())
            except ConcurrentUpdateError:
                outcomes.append("conflict")

    assert len([item for item in outcomes if item == "conflict"]) == 1
    assert len(store.pending_outbox()) == 1
    assert store.get_job(job.id).status in {JobStatus.SUCCEEDED, JobStatus.FAILED}


def test_runtime_store_migrates_existing_v1_database(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "runtime.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    version, name, statements = _MIGRATIONS[0]
    for statement in statements:
        connection.execute(statement)
    connection.execute(
        "INSERT INTO schema_migrations VALUES (?, ?, '2026-07-10T00:00:00+00:00')",
        (version, name),
    )
    connection.execute("PRAGMA user_version = 1")
    connection.commit()
    connection.close()

    store = RuntimeCoordinationStore(tmp_path)

    assert store.schema_version == RUNTIME_SCHEMA_VERSION
    with sqlite3.connect(path) as reopened:
        columns = {
            row[1] for row in reopened.execute("PRAGMA table_info(jobs)").fetchall()
        }
        versions = {
            row[0] for row in reopened.execute("SELECT version FROM schema_migrations")
        }
    assert "workflow_version" in columns
    assert versions == set(range(1, RUNTIME_SCHEMA_VERSION + 1))


def test_runtime_store_migrates_legacy_schedule_tables_to_project_keys(tmp_path):
    path = tmp_path / "runtime.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    for version, name, statements in _MIGRATIONS[:5]:
        for statement in statements:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO schema_migrations VALUES (?, ?, '2026-07-10T00:00:00+00:00')",
            (version, name),
        )
    connection.execute(
        """
        CREATE TABLE schedule_states (
            schedule_id TEXT PRIMARY KEY,
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
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX schedule_states_due_idx ON schedule_states(enabled, status, next_run_at)"
    )
    connection.execute(
        "CREATE INDEX schedule_states_project_idx ON schedule_states(project_id, updated_at)"
    )
    connection.execute(
        """
        CREATE TABLE schedule_occurrences (
            id TEXT PRIMARY KEY,
            schedule_id TEXT NOT NULL REFERENCES schedule_states(schedule_id) ON DELETE CASCADE,
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
        """
    )
    connection.execute(
        "CREATE INDEX schedule_occurrences_schedule_idx ON schedule_occurrences(schedule_id, created_at DESC)"
    )
    connection.execute(
        "CREATE INDEX schedule_occurrences_active_idx ON schedule_occurrences(status, destination_session_id)"
    )
    connection.execute(
        "INSERT INTO schema_migrations VALUES (6, ?, '2026-07-11T00:00:00+00:00')",
        (_MIGRATIONS[5][1],),
    )
    version, name, statements = _MIGRATIONS[6]
    for statement in statements:
        connection.execute(statement)
    connection.execute(
        "INSERT INTO schema_migrations VALUES (?, ?, '2026-07-11T01:00:00+00:00')",
        (version, name),
    )
    connection.execute(
        """
        INSERT INTO schedule_states (
            schedule_id, project_id, project_root, definition_hash, status,
            enabled, timezone, created_at, updated_at, definition_json
        ) VALUES ('nightly', 'project-1', '/tmp/project-1', 'hash-1', 'active',
                  1, 'UTC', '2026-07-11T00:00:00+00:00',
                  '2026-07-11T00:00:00+00:00', '{"id":"nightly"}')
        """
    )
    connection.execute(
        """
        INSERT INTO schedule_occurrences (
            id, schedule_id, definition_hash, scheduled_for, trigger, status,
            created_at
        ) VALUES ('occ-1', 'nightly', 'hash-1', '2026-07-12T00:00:00+00:00',
                  'schedule', 'queued', '2026-07-11T00:00:00+00:00')
        """
    )
    connection.execute("PRAGMA user_version = 7")
    connection.commit()
    connection.close()

    store = RuntimeCoordinationStore(tmp_path)

    expected_key = hashlib.sha256(b"project-1\0nightly").hexdigest()
    assert store.schema_version == RUNTIME_SCHEMA_VERSION
    with sqlite3.connect(path) as reopened:
        state = reopened.execute(
            "SELECT schedule_key, definition_json FROM schedule_states"
        ).fetchone()
        occurrence = reopened.execute(
            """
            SELECT schedule_occurrences.schedule_key
            FROM schedule_occurrences
            JOIN schedule_states USING (schedule_key)
            """
        ).fetchone()
        versions = {
            row[0] for row in reopened.execute("SELECT version FROM schema_migrations")
        }
        foreign_key_errors = reopened.execute("PRAGMA foreign_key_check").fetchall()
    assert state == (expected_key, '{"id":"nightly"}')
    assert occurrence == (expected_key,)
    assert versions == set(range(1, RUNTIME_SCHEMA_VERSION + 1))
    assert foreign_key_errors == []


def test_reconciler_repairs_terminal_job_to_run_and_is_idempotent(tmp_path):
    sessions = FilesystemHarnessSessionStore(tmp_path)
    session = sessions.create_session(title="recover")
    run = _create_run(sessions, session.id, status=RunStatus.RUNNING)
    runtime = RuntimeCoordinationStore(tmp_path)
    job = runtime.submit_job(
        session_id=session.id,
        user_message_id="msg_1",
        idempotency_key="recover-job",
    ).job
    attempt = runtime.create_attempt(job.id, run_id=run.id)
    runtime.transition_attempt(attempt.id, JobAttemptStatus.RUNNING)
    runtime.transition_job(job.id, JobStatus.SUCCEEDED)

    first = RuntimeReconciler(runtime, sessions).reconcile()
    second = RuntimeReconciler(runtime, sessions).reconcile()

    assert first.outbox_processed == 1
    assert first.outbox_failed == 0
    assert second.outbox_processed == 0
    assert sessions.get_run(run.id).status is RunStatus.SUCCEEDED
    events = sessions.list_events(session.id, run_id=run.id)
    assert [event.type for event in events] == ["runtime_reconciled"]
    assert events[0].job_id == job.id
    assert events[0].attempt_id == attempt.id
    assert events[0].sequence == 1


def test_reconciler_repairs_finished_run_to_terminal_job(tmp_path):
    sessions = FilesystemHarnessSessionStore(tmp_path)
    session = sessions.create_session(title="recover reverse")
    run = _create_run(sessions, session.id, status=RunStatus.SUCCEEDED)
    runtime = RuntimeCoordinationStore(tmp_path)
    job = runtime.submit_job(
        session_id=session.id,
        user_message_id="msg_1",
        idempotency_key="recover-run",
    ).job
    attempt = runtime.create_attempt(job.id, run_id=run.id)
    runtime.transition_attempt(attempt.id, JobAttemptStatus.RUNNING)

    report = RuntimeReconciler(runtime, sessions).reconcile()

    assert report.jobs_repaired == 1
    assert report.attempts_repaired == 1
    assert report.outbox_processed == 1
    assert runtime.get_job(job.id).status is JobStatus.SUCCEEDED
    assert runtime.get_attempt(attempt.id).status is JobAttemptStatus.SUCCEEDED


def test_filesystem_run_rewrites_preserve_concurrent_patches(tmp_path):
    sessions = FilesystemHarnessSessionStore(tmp_path)
    session = sessions.create_session(title="locked")
    run = _create_run(sessions, session.id, status=RunStatus.RUNNING)
    barrier = threading.Barrier(2)

    def patch(values):
        barrier.wait()
        sessions.update_run(run.id, **values)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(patch, {"status": RunStatus.FAILED}),
            executor.submit(patch, {"error": "boom"}),
        ]
        for future in futures:
            future.result()

    reopened = FilesystemHarnessSessionStore(tmp_path).get_run(run.id)
    assert reopened.status is RunStatus.FAILED
    assert reopened.error == "boom"


def test_capability_negotiation_preserves_sync_plugin_fallback():
    structured = negotiate_execution_capabilities(CodexCliHarness())
    fallback = negotiate_execution_capabilities(EchoHarness())

    assert structured.structured_events is True
    assert structured.streaming is True
    assert structured.cancellation is True
    assert fallback.structured_events is False
    assert fallback.streaming is False
    assert fallback.cancellation is False
    assert fallback.synchronous_fallback is True


def test_legacy_run_statuses_and_optional_trace_fields_round_trip(tmp_path):
    sessions = FilesystemHarnessSessionStore(tmp_path)
    session = sessions.create_session(title="legacy")
    run = _create_run(sessions, session.id, status=RunStatus.RUNNING)
    legacy_run = run_to_dict(run)
    legacy_run["status"] = "completed"
    event = HarnessStoredEvent(
        id="evt_trace",
        session_id=session.id,
        run_id=run.id,
        type="tool_call_finished",
        message="done",
        payload={},
        created_at=run.created_at,
        trace_id="trace_1",
        span_id="span_1",
        parent_span_id="span_root",
        sequence=7,
        job_id="job_1",
        attempt_id="attempt_1",
        span_kind="tool_call",
        span_status="succeeded",
    )

    assert run_from_dict(legacy_run).status is RunStatus.SUCCEEDED
    assert event_from_dict(event_to_dict(event)) == event
    plain_event = HarnessStoredEvent(
        id="evt_plain",
        session_id=session.id,
        run_id=run.id,
        type="warning",
        message="plain",
        payload={},
        created_at=run.created_at,
    )
    assert "trace_id" not in event_to_dict(plain_event)


def test_runtime_cli_inspect_and_export_json(tmp_path, monkeypatch, capsys):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(data_dir))

    inspect_code = cli.main(["runtime", "inspect", "--json"])
    inspected = json.loads(capsys.readouterr().out)
    output = tmp_path / "runtime.json"
    export_code = cli.main(["runtime", "export", "--output", str(output)])

    assert inspect_code == 0
    assert export_code == 0
    assert inspected["schema_version"] == RUNTIME_SCHEMA_VERSION
    assert json.loads(output.read_text(encoding="utf-8"))["jobs"] == []
    assert "Exported runtime coordination state" in capsys.readouterr().out


def _create_run(
    store: FilesystemHarnessSessionStore,
    session_id: str,
    *,
    status: RunStatus,
):
    return store.create_run(
        session_id=session_id,
        harness_id="echo",
        prompt="hello",
        model=None,
        api_mode=GigaChatApiMode.V2,
        capability=HarnessCapability.CHAT_COMPLETIONS,
        mode="plan",
        workspace=None,
        status=status,
    )
