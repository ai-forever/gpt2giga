from gpt2giga.harness.config import HarnessConfig
from gpt2giga.harness.harnesses.base import BaseHarness
from gpt2giga.harness.registry import HarnessRegistry
from gpt2giga.harness.session_runner import HarnessSessionRunner
from gpt2giga.harness.sessions import InMemoryHarnessSessionStore
from gpt2giga.harness.types import (
    Availability,
    HarnessCapability,
    HarnessContext,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
)


def test_session_runner_create_and_run_persists_success():
    harness = _CaptureHarness()
    runner = _runner(harness)

    result = runner.create_and_run(
        {
            "harness_id": "capture",
            "prompt": "hello",
            "api_mode": "v2",
            "mode": "plan",
        }
    )
    bundle = result.bundle

    assert result.result.ok is True
    assert bundle.session.title == "hello"
    assert [message.role for message in bundle.messages] == ["user", "assistant"]
    assert bundle.messages[-1].content == "answer: hello"
    assert bundle.runs[0].status == "succeeded"
    assert bundle.raw_requests
    assert bundle.raw_responses
    assert {event.type for event in bundle.events} >= {
        "run_started",
        "raw_request",
        "raw_response",
        "message_completed",
        "run_finished",
    }


def test_session_runner_failed_harness_stores_error_message():
    runner = _runner(_FailingHarness())

    result = runner.create_and_run({"harness_id": "fail", "prompt": "hello"})

    assert result.run.status == "failed"
    assert result.bundle.messages[-1].role == "error"
    assert result.bundle.messages[-1].content == "boom"


def test_session_runner_passes_previous_messages_to_chat_harness():
    harness = _CaptureHarness()
    runner = _runner(harness)
    first = runner.create_and_run({"harness_id": "capture", "prompt": "first"})

    runner.run_in_session(first.session.id, {"prompt": "second"})

    assert harness.last_request is not None
    assert [
        (message.role, message.content) for message in harness.last_request.messages
    ] == [
        ("user", "first"),
        ("assistant", "answer: first"),
        ("user", "second"),
    ]


def _runner(harness: BaseHarness) -> HarnessSessionRunner:
    registry = HarnessRegistry()
    registry.register(harness)
    return HarnessSessionRunner(
        registry=registry,
        config=HarnessConfig(default_model="ConfiguredModel"),
        store=InMemoryHarnessSessionStore(),
    )


class _CaptureHarness(BaseHarness):
    def __init__(self) -> None:
        self.last_request: HarnessRequest | None = None

    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="capture",
            title="Capture",
            kind="test",
            description="Capture request",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
        )

    def availability(self) -> Availability:
        return Availability.available("test")

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        self.last_request = request
        return HarnessResult(
            ok=True,
            text=f"answer: {request.prompt}",
            raw={"request_id": "ok"},
            command=("capture", request.prompt),
        )


class _FailingHarness(BaseHarness):
    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="fail",
            title="Fail",
            kind="test",
            description="Fail request",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
        )

    def availability(self) -> Availability:
        return Availability.available("test")

    def run(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> HarnessResult:
        return HarnessResult(ok=False, text="", error="boom")
