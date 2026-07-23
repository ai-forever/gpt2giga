from gpt2giga_harness.application import SessionApplicationService
from gpt2giga_harness.cli_capabilities import CliCapabilitySnapshot
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.registry import HarnessRegistry
from gpt2giga_harness.runtime.models import ApprovalStatus, JobStatus, RunStatus
from gpt2giga_harness.runtime.payloads import DurableJobPayloadStore
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore
from gpt2giga_harness.runtime.worker import DurableJobDispatcher, DurableJobWorker
from gpt2giga_harness.session_runner import HarnessSessionRunner
from gpt2giga_harness.sessions import FilesystemHarnessSessionStore
from gpt2giga_harness.settings import HarnessSettingsStore
from gpt2giga_harness.structured_sessions import AdapterCapabilitySnapshot
from gpt2giga_harness.types import (
    Availability,
    HarnessCapability,
    HarnessContext,
    HarnessEvent,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
    HeadlessContinuationStrategy,
)


def test_session_application_service_completes_approval_and_event_vertical(tmp_path):
    config = HarnessConfig(
        data_dir=str(tmp_path / "data"),
        default_model="ConfiguredModel",
    )
    registry = HarnessRegistry()
    registry.register(_StructuredNativeHarness())
    sessions = FilesystemHarnessSessionStore(config.data_dir)
    runtime = RuntimeCoordinationStore(config.data_dir)
    runner = HarnessSessionRunner(
        registry=registry,
        config=config,
        store=sessions,
    )
    service = SessionApplicationService(
        runner=runner,
        settings_store=HarnessSettingsStore(config.data_dir, config),
        runtime_store=runtime,
        dispatcher=DurableJobDispatcher(
            runtime_store=runtime,
            payload_store=DurableJobPayloadStore(config.data_dir),
            runner=runner,
        ),
    )

    session = service.create_session(
        {
            "title": "Shared application path",
            "harness_id": "codex-cli",
            "model": "ConfiguredModel",
        },
        validate_harness=True,
    )
    submission = service.submit_turn(
        session.id,
        {
            "harness_id": "codex-cli",
            "prompt": "application service turn",
            "model": "ConfiguredModel",
            "permission_profile": "review_every_action",
            "stream": True,
        },
        idempotency_key="shared-session-turn",
    )

    assert submission.job.status is JobStatus.WAITING_APPROVAL
    pending = runtime.list_approval_requests(
        status=ApprovalStatus.PENDING,
        limit=10,
    )
    assert len(pending) == 1
    assert pending[0].run_id == submission.queued.run.id
    assert [
        event.type for event in service.list_run_events(submission.queued.run.id)
    ] == ["approval_requested"]

    decision = service.decide_approval(pending[0].id, "allow_once")

    assert decision.job is not None
    assert decision.job.status is JobStatus.QUEUED
    assert decision.retry_action is False
    worker = DurableJobWorker(config, registry=registry, worker_id="worker_application")
    assert worker.run_once() is True
    completed = service.get_run(submission.queued.run.id)
    assert completed.status is RunStatus.SUCCEEDED
    assert completed.metadata["continuation"]["strategy"] == "structured_thread"
    assert completed.metadata["app_server_thread"]["thread_id"] == "thread-1"
    run, page = service.read_run_event_tail(completed.id, 0)
    assert run.id == completed.id
    event_types = [item.event.type for item in page.items]
    assert event_types[0:2] == ["approval_requested", "approval_decided"]
    assert "run_started" in event_types
    assert "message_delta" in event_types
    assert "run_finished" in event_types


class _StructuredNativeHarness(BaseHarness):
    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="codex-cli",
            title="Structured Codex",
            kind="agent-cli",
            description="Hermetic structured native session fixture",
            capabilities=(HarnessCapability.AGENT_CLI,),
            supports_streaming=True,
            headless_continuation=HeadlessContinuationStrategy.STRUCTURED_THREAD,
        )

    def capability_probe(self):
        return CliCapabilitySnapshot(
            harness_id="codex-cli",
            status="supported",
            version="0.144.5",
            parsed_version="0.144.5",
            command=("codex",),
            capabilities={
                "--json": True,
                "--sandbox": True,
                "--ephemeral": True,
                "app-server": True,
            },
            event_schema="codex-exec-jsonl-v1",
            history_schema="codex-session-jsonl-v1",
            version_window_status="in_window",
            minimum_version="0.144.0",
            maximum_version_exclusive="0.145.0",
        )

    def availability(self) -> Availability:
        return Availability.available("hermetic structured fixture")

    def durable_structured_capabilities(self) -> AdapterCapabilitySnapshot:
        return AdapterCapabilitySnapshot(
            adapter_id="codex-cli",
            adapter_version="0.144.5",
            protocol="codex-app-server-json-rpc-v2",
            protocol_version="2",
            structured_events=True,
            partial_output=True,
            interactive_input=False,
            live_approvals=True,
            durable_approval=True,
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

    def run_durable_structured(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        return self.run(request, context)

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        del context
        continuation = request.extra["continuation"]
        return HarnessResult(
            ok=True,
            text="structured native answer",
            raw={
                "app_server_thread": {
                    "schema_version": 1,
                    "protocol": continuation["protocol"],
                    "runtime_id": "runtime-1",
                    "thread_id": "thread-1",
                    "latest_turn_id": "turn-1",
                    "snapshot": continuation["snapshot"],
                    "snapshot_hash": continuation["snapshot"]["snapshot_hash"],
                    "runtime_status": "loaded",
                }
            },
            events=(
                HarnessEvent(
                    type="message_delta",
                    message="Structured native response delta.",
                    payload={"delta": "structured native answer"},
                ),
            ),
            command=("codex", "app-server", "--stdio"),
        )
