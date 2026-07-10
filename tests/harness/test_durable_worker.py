import concurrent.futures
import threading
import time

from fastapi.testclient import TestClient

from gpt2giga.harness import cli
from gpt2giga.harness.arena import FilesystemHarnessArenaStore, queue_arena
from gpt2giga.harness.config import HarnessConfig
from gpt2giga.harness.harnesses.base import BaseHarness
from gpt2giga.harness.registry import HarnessRegistry, create_default_registry
from gpt2giga.harness.runtime.models import JobAttemptStatus, JobStatus
from gpt2giga.harness.runtime.payloads import DurableJobPayloadStore
from gpt2giga.harness.runtime.store import RuntimeCoordinationStore
from gpt2giga.harness.runtime.worker import DurableJobDispatcher, DurableJobWorker
from gpt2giga.harness.session_runner import HarnessSessionRunner
from gpt2giga.harness.sessions import FilesystemHarnessSessionStore
from gpt2giga.harness.types import (
    Availability,
    HarnessCapability,
    HarnessContext,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
)
from gpt2giga.harness.ui.app import create_app


def test_durable_dispatcher_worker_executes_once_and_preserves_logical_message(
    tmp_path,
):
    config = HarnessConfig(data_dir=str(tmp_path), auto_start_proxy=True)
    registry = create_default_registry(include_entry_points=False)
    sessions = FilesystemHarnessSessionStore(tmp_path)
    runtime = RuntimeCoordinationStore(tmp_path)
    runner = HarnessSessionRunner(registry=registry, config=config, store=sessions)
    dispatcher = DurableJobDispatcher(
        runtime_store=runtime,
        payload_store=DurableJobPayloadStore(tmp_path),
        runner=runner,
    )
    session = runner.create_session(title="durable")

    submitted = dispatcher.submit(
        session.id,
        {"harness_id": "echo", "prompt": "hello", "mode": "read"},
        idempotency_key="browser-submit-1",
    )
    worker = DurableJobWorker(config, registry=registry, worker_id="worker_test")

    assert submitted.queued.run.status.value == "queued"
    assert worker.config.auto_start_proxy is False
    assert worker.run_once() is True

    job = runtime.get_job(submitted.job.id)
    attempts = runtime.list_attempts(job.id)
    bundle = sessions.get_session_bundle(session.id)
    assert job.status is JobStatus.SUCCEEDED
    assert [attempt.status for attempt in attempts] == [JobAttemptStatus.SUCCEEDED]
    assert [message.role for message in bundle.messages] == ["user", "assistant"]
    assert [message.content for message in bundle.messages] == ["hello", "hello"]
    assert bundle.runs[0].status.value == "succeeded"
    assert bundle.runs[0].metadata["runtime"]["worker_id"] == "worker_test"


def test_atomic_claim_allows_only_one_matching_worker(tmp_path):
    store = RuntimeCoordinationStore(tmp_path)
    job = store.submit_job(
        session_id="sess_1",
        user_message_id="msg_1",
        initial_run_id="run_1",
        idempotency_key="claim",
        required_harness_id="echo",
    ).job
    fingerprint = {"harnesses": {"echo": {"available": True}}}

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(
            executor.map(
                lambda owner: store.claim_next_job(
                    worker_id=owner,
                    capability_fingerprint=fingerprint,
                    lease_seconds=5,
                ),
                ("worker_a", "worker_b"),
            )
        )

    assert sum(claim is not None for claim in claims) == 1
    assert store.get_job(job.id).status is JobStatus.RUNNING
    assert len(store.list_attempts(job.id)) == 1


def test_dispatcher_serializes_concurrent_idempotent_submissions(tmp_path):
    config = HarnessConfig(data_dir=str(tmp_path))
    registry = create_default_registry(include_entry_points=False)
    sessions = FilesystemHarnessSessionStore(tmp_path)
    runtime = RuntimeCoordinationStore(tmp_path)
    dispatcher = DurableJobDispatcher(
        runtime_store=runtime,
        payload_store=DurableJobPayloadStore(tmp_path),
        runner=HarnessSessionRunner(registry=registry, config=config, store=sessions),
    )
    session = sessions.create_session(title="concurrent")

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        submissions = list(
            executor.map(
                lambda _: dispatcher.submit(
                    session.id,
                    {"harness_id": "echo", "prompt": "once", "mode": "read"},
                    idempotency_key="same-browser-submit",
                ),
                range(2),
            )
        )

    assert submissions[0].job.id == submissions[1].job.id
    assert len(runtime.list_jobs()) == 1
    assert len(sessions.list_runs(session.id)) == 1
    assert len(sessions.list_messages(session.id)) == 1


def test_claim_rejects_mismatched_binary_fingerprint(tmp_path):
    store = RuntimeCoordinationStore(tmp_path)
    job = store.submit_job(
        session_id="sess_1",
        user_message_id="msg_1",
        idempotency_key="fingerprint",
        required_harness_id="codex-cli",
        required_capability_fingerprint={
            "os": "darwin",
            "harnesses": {
                "codex-cli": {
                    "distribution": "builtin",
                    "binary_version": "codex-cli 99.0",
                    "features": {"cancellation": True},
                }
            },
        },
    ).job

    claim = store.claim_next_job(
        worker_id="worker_old",
        capability_fingerprint={
            "os": "darwin",
            "harnesses": {
                "codex-cli": {
                    "available": True,
                    "distribution": "builtin",
                    "binary_version": "codex-cli 1.0",
                    "features": {"cancellation": True},
                }
            },
        },
        lease_seconds=5,
    )

    assert claim is None
    assert store.get_job(job.id).status is JobStatus.QUEUED


def test_worker_cancellation_is_persisted_and_cooperative(tmp_path):
    config = HarnessConfig(data_dir=str(tmp_path))
    registry = HarnessRegistry()
    registry.register(_SlowHarness())
    sessions = FilesystemHarnessSessionStore(tmp_path)
    runtime = RuntimeCoordinationStore(tmp_path)
    runner = HarnessSessionRunner(registry=registry, config=config, store=sessions)
    dispatcher = DurableJobDispatcher(
        runtime_store=runtime,
        payload_store=DurableJobPayloadStore(tmp_path),
        runner=runner,
    )
    session = runner.create_session(title="cancel")
    submitted = dispatcher.submit(
        session.id,
        {"harness_id": "slow-worker", "prompt": "wait", "mode": "read"},
        idempotency_key="cancel",
    )
    worker = DurableJobWorker(
        config,
        registry=registry,
        worker_id="worker_cancel",
        heartbeat_seconds=0.02,
        lease_seconds=2,
    )
    thread = threading.Thread(target=worker.run_once)
    thread.start()
    deadline = time.monotonic() + 2
    while runtime.get_job(submitted.job.id).status is not JobStatus.RUNNING:
        assert time.monotonic() < deadline
        time.sleep(0.01)

    runtime.request_cancel(submitted.job.id)
    thread.join(timeout=3)

    assert not thread.is_alive()
    assert runtime.get_job(submitted.job.id).status is JobStatus.CANCELED
    assert sessions.get_run(submitted.queued.run.id).status.value == "canceled"


def test_safe_retry_creates_new_attempt_and_run_without_new_user_message(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "gpt2giga.harness.runtime.worker.DEFAULT_RETRY_BACKOFF_SECONDS", 0.0
    )
    config = HarnessConfig(data_dir=str(tmp_path))
    registry = HarnessRegistry()
    flaky = _FlakyHarness()
    registry.register(flaky)
    sessions = FilesystemHarnessSessionStore(tmp_path)
    runtime = RuntimeCoordinationStore(tmp_path)
    runner = HarnessSessionRunner(registry=registry, config=config, store=sessions)
    dispatcher = DurableJobDispatcher(
        runtime_store=runtime,
        payload_store=DurableJobPayloadStore(tmp_path),
        runner=runner,
    )
    session = runner.create_session(title="retry")
    submitted = dispatcher.submit(
        session.id,
        {
            "harness_id": "flaky-worker",
            "prompt": "retry me",
            "mode": "read",
            "max_attempts": 2,
        },
        idempotency_key="retry",
    )
    worker = DurableJobWorker(config, registry=registry, worker_id="worker_retry")

    assert worker.run_once() is True
    assert runtime.get_job(submitted.job.id).status is JobStatus.RETRY_WAIT
    assert worker.run_once() is True

    bundle = sessions.get_session_bundle(session.id)
    assert runtime.get_job(submitted.job.id).status is JobStatus.SUCCEEDED
    assert len(runtime.list_attempts(submitted.job.id)) == 2
    assert len(bundle.runs) == 2
    assert [message.role for message in bundle.messages].count("user") == 1
    assert flaky.request_message_counts == [1, 1]


def test_worker_timeout_fails_job_and_records_process_metadata(tmp_path):
    config = HarnessConfig(data_dir=str(tmp_path))
    registry = HarnessRegistry()
    registry.register(_ProcessHarness())
    sessions = FilesystemHarnessSessionStore(tmp_path)
    runtime = RuntimeCoordinationStore(tmp_path)
    runner = HarnessSessionRunner(registry=registry, config=config, store=sessions)
    dispatcher = DurableJobDispatcher(
        runtime_store=runtime,
        payload_store=DurableJobPayloadStore(tmp_path),
        runner=runner,
    )
    session = runner.create_session(title="timeout")
    submitted = dispatcher.submit(
        session.id,
        {
            "harness_id": "process-worker",
            "prompt": "timeout",
            "mode": "read",
            "timeout_seconds": 0.05,
        },
        idempotency_key="timeout",
    )
    worker = DurableJobWorker(
        config,
        registry=registry,
        worker_id="worker_timeout",
        heartbeat_seconds=0.01,
    )

    assert worker.run_once() is True

    job = runtime.get_job(submitted.job.id)
    attempt = runtime.list_attempts(job.id)[0]
    run = sessions.get_run(attempt.run_id)
    assert job.status is JobStatus.FAILED
    assert attempt.process_id == 43210
    assert attempt.process_group_id == 43211
    assert run.status.value == "failed"
    assert "timed out" in (run.error or "")


def test_worker_forces_structured_stream_mode_for_cancelable_cli_shape(tmp_path):
    config = HarnessConfig(data_dir=str(tmp_path))
    registry = HarnessRegistry()
    harness = _StreamingCaptureHarness()
    registry.register(harness)
    sessions = FilesystemHarnessSessionStore(tmp_path)
    runtime = RuntimeCoordinationStore(tmp_path)
    runner = HarnessSessionRunner(registry=registry, config=config, store=sessions)
    dispatcher = DurableJobDispatcher(
        runtime_store=runtime,
        payload_store=DurableJobPayloadStore(tmp_path),
        runner=runner,
    )
    session = runner.create_session(title="stream")
    dispatcher.submit(
        session.id,
        {"harness_id": "stream-worker", "prompt": "run", "stream": False},
        idempotency_key="stream",
    )

    assert DurableJobWorker(config, registry=registry).run_once() is True
    assert harness.stream_values == [True]


def test_arena_children_run_as_independent_durable_jobs(tmp_path):
    config = HarnessConfig(data_dir=str(tmp_path))
    registry = HarnessRegistry()
    registry.register(_NamedEchoHarness("arena-one"))
    registry.register(_NamedEchoHarness("arena-two"))
    sessions = FilesystemHarnessSessionStore(tmp_path)
    runtime = RuntimeCoordinationStore(tmp_path)
    runner = HarnessSessionRunner(registry=registry, config=config, store=sessions)
    dispatcher = DurableJobDispatcher(
        runtime_store=runtime,
        payload_store=DurableJobPayloadStore(tmp_path),
        runner=runner,
    )
    arena_store = FilesystemHarnessArenaStore(tmp_path)
    arena = queue_arena(
        runner=runner,
        dispatcher=dispatcher,
        arena_store=arena_store,
        payload={
            "prompt": "compare",
            "harness_ids": ["arena-one", "arena-two"],
            "mode": "read",
        },
    )
    worker = DurableJobWorker(config, registry=registry, worker_id="worker_arena")

    assert arena.status == "running"
    assert [child.status for child in arena.child_runs] == ["queued", "queued"]
    assert worker.run_once() is True
    assert worker.run_once() is True

    completed = arena_store.get(arena.id)
    assert completed.status == "succeeded"
    assert [child.status for child in completed.child_runs] == [
        "succeeded",
        "succeeded",
    ]
    assert len(runtime.list_jobs()) == 2


def test_expired_attempt_recovery_retries_only_safe_work(tmp_path):
    store = RuntimeCoordinationStore(tmp_path)
    safe = store.submit_job(
        session_id="sess_safe",
        user_message_id="msg_safe",
        idempotency_key="safe",
        max_attempts=2,
    ).job
    unsafe = store.submit_job(
        session_id="sess_unsafe",
        user_message_id="msg_unsafe",
        idempotency_key="unsafe",
        max_attempts=2,
    ).job
    safe_attempt = store.create_attempt(
        safe.id,
        run_id=safe.initial_run_id,
        leased_until="2000-01-01T00:00:00+00:00",
        idempotency_class="read_only",
    )
    unsafe_attempt = store.create_attempt(
        unsafe.id,
        run_id=unsafe.initial_run_id,
        leased_until="2000-01-01T00:00:00+00:00",
        idempotency_class="external_write",
    )

    recovered = store.recover_expired_attempts(retry_delay_seconds=0)

    assert {item.id for item in recovered} == {safe_attempt.id, unsafe_attempt.id}
    assert store.get_job(safe.id).status is JobStatus.RETRY_WAIT
    assert store.get_job(unsafe.id).status is JobStatus.FAILED
    assert store.get_attempt(safe_attempt.id).status is JobAttemptStatus.INTERRUPTED
    assert store.get_attempt(unsafe_attempt.id).status is JobAttemptStatus.INTERRUPTED


def test_filesystem_ui_submits_idempotent_durable_run_and_worker_completes(tmp_path):
    config = HarnessConfig(data_dir=str(tmp_path))
    registry = create_default_registry(include_entry_points=False)
    sessions = FilesystemHarnessSessionStore(tmp_path)
    client = TestClient(create_app(config, registry=registry, store=sessions))
    session_id = client.post(
        "/api/sessions", json={"title": "UI durable", "harness_id": "echo"}
    ).json()["session"]["id"]
    request = {
        "harness_id": "echo",
        "prompt": "queued hello",
        "mode": "read",
        "idempotency_key": "stable-ui-key",
    }

    first = client.post(f"/api/sessions/{session_id}/run/start", json=request)
    repeated = client.post(f"/api/sessions/{session_id}/run/start", json=request)

    assert first.status_code == 200
    assert first.json()["run"]["status"] == "queued"
    assert first.json()["run"]["id"] == repeated.json()["run"]["id"]
    assert first.json()["job"]["id"] == repeated.json()["job"]["id"]
    worker = DurableJobWorker(config, registry=registry, worker_id="worker_ui")
    assert worker.run_once() is True
    completed = client.get(f"/api/runs/{first.json()['run']['id']}")
    assert completed.status_code == 200
    selected = next(
        run
        for run in completed.json()["runs"]
        if run["id"] == completed.json()["selected_run_id"]
    )
    assert selected["status"] == "succeeded"
    assert [message["role"] for message in completed.json()["messages"]] == [
        "user",
        "assistant",
    ]


def test_filesystem_ui_cancels_queued_job_before_worker_claim(tmp_path):
    config = HarnessConfig(data_dir=str(tmp_path))
    registry = create_default_registry(include_entry_points=False)
    sessions = FilesystemHarnessSessionStore(tmp_path)
    client = TestClient(create_app(config, registry=registry, store=sessions))

    started = client.post(
        "/api/sessions/run/start",
        json={"harness_id": "echo", "prompt": "cancel queued"},
    ).json()
    canceled = client.post(f"/api/runs/{started['run']['id']}/cancel")

    assert canceled.status_code == 200
    assert canceled.json()["active"] is False
    assert canceled.json()["job"]["status"] == "canceled"
    assert canceled.json()["run"]["status"] == "canceled"
    assert DurableJobWorker(config, registry=registry).run_once() is False


def test_worker_cli_status_and_once_are_json_inspectable(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(tmp_path))

    assert cli.main(["worker", "start", "--once"]) == 0
    assert capsys.readouterr().out.strip() == "idle"
    assert cli.main(["worker", "status", "--json"]) == 0

    payload = __import__("json").loads(capsys.readouterr().out)
    assert payload["online"] == 0
    assert payload["workers"][0]["status"] == "stopped"
    assert (
        cli.main(
            [
                "worker",
                "stop-on-idle",
                "--idle-seconds",
                "0",
                "--poll-seconds",
                "0.01",
            ]
        )
        == 0
    )
    assert "stopped after idle timeout" in capsys.readouterr().out


class _SlowHarness(BaseHarness):
    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="slow-worker",
            title="Slow",
            kind="test",
            description="cooperative worker cancellation",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
            supports_cancellation=True,
        )

    def availability(self) -> Availability:
        return Availability.available()

    def run(self, request: HarnessRequest, context: HarnessContext) -> HarnessResult:
        while request.cancel_event is None or not request.cancel_event.is_set():
            time.sleep(0.01)
        return HarnessResult(ok=False, text="", error="canceled")


class _FlakyHarness(BaseHarness):
    def __init__(self) -> None:
        self.calls = 0
        self.request_message_counts: list[int] = []

    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="flaky-worker",
            title="Flaky",
            kind="test",
            description="fails once",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
        )

    def availability(self) -> Availability:
        return Availability.available()

    def run(self, request: HarnessRequest, context: HarnessContext) -> HarnessResult:
        self.calls += 1
        self.request_message_counts.append(len(request.messages))
        if self.calls == 1:
            return HarnessResult(ok=False, text="", error="transient")
        return HarnessResult(ok=True, text="done")


class _ProcessHarness(BaseHarness):
    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="process-worker",
            title="Process",
            kind="test",
            description="reports process metadata",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
            supports_cancellation=True,
        )

    def availability(self) -> Availability:
        return Availability.available()

    def run(self, request: HarnessRequest, context: HarnessContext) -> HarnessResult:
        assert request.process_sink is not None
        request.process_sink({"process_id": 43210, "process_group_id": 43211})
        while request.cancel_event is None or not request.cancel_event.is_set():
            time.sleep(0.005)
        return HarnessResult(ok=False, text="", error="canceled")


class _NamedEchoHarness(BaseHarness):
    def __init__(self, harness_id: str) -> None:
        self.harness_id = harness_id

    def spec(self) -> HarnessSpec:
        return HarnessSpec(
            id=self.harness_id,
            title=self.harness_id,
            kind="test",
            description="durable arena echo",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
        )

    def availability(self) -> Availability:
        return Availability.available()

    def run(self, request: HarnessRequest, context: HarnessContext) -> HarnessResult:
        return HarnessResult(ok=True, text=request.prompt)


class _StreamingCaptureHarness(BaseHarness):
    def __init__(self) -> None:
        self.stream_values: list[bool] = []

    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="stream-worker",
            title="Stream",
            kind="agent-cli",
            description="captures worker stream mode",
            capabilities=(HarnessCapability.AGENT_CLI,),
            supports_streaming=True,
            supports_structured_events=True,
            supports_cancellation=True,
        )

    def availability(self) -> Availability:
        return Availability.available()

    def run(self, request: HarnessRequest, context: HarnessContext) -> HarnessResult:
        self.stream_values.append(request.stream)
        return HarnessResult(ok=True, text="done")
