from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.execution import ExecutionTransport
from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.registry import HarnessRegistry
from gpt2giga_harness.runtime.models import JobAttemptStatus, JobStatus
from gpt2giga_harness.runtime.payloads import DurableJobPayloadStore
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore
from gpt2giga_harness.runtime.structured import (
    DURABLE_STRUCTURED_ADMISSION_FIELD,
    DurableStructuredAdmissionError,
)
from gpt2giga_harness.runtime.worker import DurableJobDispatcher, DurableJobWorker
from gpt2giga_harness.session_runner import HarnessSessionRunner
from gpt2giga_harness.sessions import FilesystemHarnessSessionStore
from gpt2giga_harness.structured_sessions import AdapterCapabilitySnapshot
from gpt2giga_harness.types import (
    Availability,
    HarnessCapability,
    HarnessContext,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
)


def test_proven_structured_transport_is_worker_owned_and_retryable(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "gpt2giga_harness.runtime.worker.DEFAULT_RETRY_BACKOFF_SECONDS", 0.0
    )
    harness = _StructuredHarness("recoverable", durable_approval=True, fail_once=True)
    registry, dispatcher, worker, runtime, payloads, sessions = _runtime(
        tmp_path, harness
    )
    session = sessions.create_session(title="structured")

    submitted = dispatcher.submit(
        session.id,
        {
            "harness_id": harness.harness_id,
            "prompt": "resume exactly",
            "execution_transport": ExecutionTransport.NATIVE_STRUCTURED.value,
            "max_attempts": 2,
        },
        idempotency_key="structured-recoverable",
    )

    stored = payloads.load(submitted.job.id)
    admission = stored[DURABLE_STRUCTURED_ADMISSION_FIELD]
    assert admission["transport"] == "native_structured"
    assert admission["retry_class"] == "structured_recoverable"
    assert worker.run_once() is True
    assert runtime.get_job(submitted.job.id).status is JobStatus.RETRY_WAIT
    assert worker.run_once() is True

    attempts = runtime.list_attempts(submitted.job.id)
    assert [item.status for item in attempts] == [
        JobAttemptStatus.FAILED,
        JobAttemptStatus.SUCCEEDED,
    ]
    assert [item.idempotency_class for item in attempts] == [
        "structured_recoverable",
        "structured_recoverable",
    ]
    assert harness.structured_calls == 2
    assert harness.legacy_calls == 0
    runs = sessions.list_runs(session.id)
    assert all(
        run.metadata["execution_transport"] == "native_structured" for run in runs
    )
    assert registry is worker.registry


def test_ambiguous_structured_turn_fails_closed_without_retry(tmp_path):
    harness = _StructuredHarness("ambiguous", durable_approval=False, fail_once=True)
    _, dispatcher, worker, runtime, _, sessions = _runtime(tmp_path, harness)
    session = sessions.create_session(title="ambiguous")
    submitted = dispatcher.submit(
        session.id,
        {
            "harness_id": harness.harness_id,
            "prompt": "do not duplicate",
            "execution_transport": "native_structured",
            "max_attempts": 3,
        },
        idempotency_key="structured-ambiguous",
    )

    assert worker.run_once() is True

    attempts = runtime.list_attempts(submitted.job.id)
    assert runtime.get_job(submitted.job.id).status is JobStatus.FAILED
    assert len(attempts) == 1
    assert attempts[0].idempotency_class == "structured_ambiguous"
    assert harness.structured_calls == 1
    assert worker.run_once() is False


def test_native_terminal_and_unproven_handoff_are_not_durable_admitted(tmp_path):
    harness = _StructuredHarness("eligible", durable_approval=True)
    _, dispatcher, _, _, _, sessions = _runtime(tmp_path, harness)
    session = sessions.create_session(title="blocked")

    try:
        dispatcher.submit(
            session.id,
            {
                "harness_id": harness.harness_id,
                "prompt": "terminal",
                "execution_transport": "native_terminal",
            },
            idempotency_key="terminal",
        )
    except DurableStructuredAdmissionError as exc:
        assert "synchronous" in str(exc)
    else:  # pragma: no cover - fail-closed contract
        raise AssertionError("native terminal was durable-admitted")

    unproven = _LegacyHarness()
    registry = HarnessRegistry()
    registry.register(unproven)
    runner = HarnessSessionRunner(
        registry=registry,
        config=HarnessConfig(data_dir=str(tmp_path / "handoff")),
        store=FilesystemHarnessSessionStore(tmp_path / "handoff"),
    )
    unproven_session = runner.create_session(title="handoff")
    unproven_dispatcher = DurableJobDispatcher(
        runtime_store=RuntimeCoordinationStore(tmp_path / "handoff"),
        payload_store=DurableJobPayloadStore(tmp_path / "handoff"),
        runner=runner,
    )
    try:
        unproven_dispatcher.submit(
            unproven_session.id,
            {
                "harness_id": "provider-handoff",
                "prompt": "open provider",
                "execution_transport": "native_structured",
            },
            idempotency_key="handoff",
        )
    except DurableStructuredAdmissionError as exc:
        assert "no proven" in str(exc)
    else:  # pragma: no cover - fail-closed contract
        raise AssertionError("provider handoff was mislabeled as structured")


def _runtime(tmp_path, harness):
    config = HarnessConfig(data_dir=str(tmp_path))
    registry = HarnessRegistry()
    registry.register(harness)
    sessions = FilesystemHarnessSessionStore(tmp_path)
    runtime = RuntimeCoordinationStore(tmp_path)
    payloads = DurableJobPayloadStore(tmp_path)
    runner = HarnessSessionRunner(registry=registry, config=config, store=sessions)
    dispatcher = DurableJobDispatcher(
        runtime_store=runtime,
        payload_store=payloads,
        runner=runner,
    )
    worker = DurableJobWorker(config, registry=registry, worker_id="structured-worker")
    return registry, dispatcher, worker, runtime, payloads, sessions


class _StructuredHarness(BaseHarness):
    def __init__(self, harness_id, *, durable_approval, fail_once=False):
        self.harness_id = harness_id
        self._durable_approval = durable_approval
        self._fail_once = fail_once
        self.structured_calls = 0
        self.legacy_calls = 0

    def spec(self):
        return HarnessSpec(
            id=self.harness_id,
            title=self.harness_id,
            kind="test",
            description="structured runtime fixture",
            capabilities=(HarnessCapability.AGENT_CLI,),
            supports_streaming=True,
            supports_structured_events=True,
            supports_cancellation=True,
        )

    def availability(self):
        return Availability.available()

    def durable_structured_capabilities(self):
        return AdapterCapabilitySnapshot(
            adapter_id=self.harness_id,
            adapter_version="1.0",
            protocol="fixture-rpc",
            protocol_version="1",
            structured_events=True,
            partial_output=True,
            interactive_input=False,
            live_approvals=True,
            durable_approval=self._durable_approval,
            interrupt=True,
            steer=False,
            resume=True,
            fork=False,
            session_list=False,
            session_close=False,
            native_auth=False,
            provider_ui_handoff=False,
            dynamic_model=False,
            dynamic_mcp=False,
            recovery_after_process_loss=True,
        )

    def run_durable_structured(self, request, context):
        del context
        self.structured_calls += 1
        if self._fail_once and self.structured_calls == 1:
            return HarnessResult(ok=False, text="", error="owner lost")
        return HarnessResult(ok=True, text=request.prompt)

    def run(self, request: HarnessRequest, context: HarnessContext):
        del request, context
        self.legacy_calls += 1
        return HarnessResult(ok=True, text="legacy")


class _LegacyHarness(BaseHarness):
    @classmethod
    def spec(cls):
        return HarnessSpec(
            id="provider-handoff",
            title="Provider handoff",
            kind="test",
            description="provider-owned action only",
            capabilities=(HarnessCapability.AGENT_CLI,),
        )

    def availability(self):
        return Availability.available()

    def run(self, request, context):
        del request, context
        return HarnessResult(ok=True, text="handoff")
