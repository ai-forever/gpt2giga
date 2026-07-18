from gpt2giga_harness.execution import ExecutionTransport
from gpt2giga_harness.structured_sessions import AdapterCapabilitySnapshot
from gpt2giga_harness.types import HarnessCapability, HarnessSpec
from gpt2giga_harness.workbench_execution import (
    default_workbench_transport,
    effective_workbench_transport,
    workbench_transport_projection,
)


class _Harness:
    def __init__(self, harness_id: str, *, kind: str = "agent-cli") -> None:
        self.harness_id = harness_id
        self.kind = kind

    def spec(self) -> HarnessSpec:
        return HarnessSpec(
            id=self.harness_id,
            title=self.harness_id,
            kind=self.kind,
            description="test harness",
            capabilities=(HarnessCapability.AGENT_CLI,),
        )


class _StructuredHarness(_Harness):
    def durable_structured_capabilities(self) -> AdapterCapabilitySnapshot:
        return AdapterCapabilitySnapshot(
            adapter_id=self.harness_id,
            adapter_version="1.0.0",
            protocol="test-structured",
            protocol_version="1",
            structured_events=True,
            partial_output=True,
            interactive_input=False,
            live_approvals=True,
            durable_approval=False,
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
        raise AssertionError("projection must not execute the driver")


def test_provider_agents_default_structured_without_silent_fallback():
    claude = _Harness("claude-code")

    assert default_workbench_transport(claude) is ExecutionTransport.NATIVE_STRUCTURED
    projection = workbench_transport_projection(claude)
    structured = projection["options"][0]
    assert projection["default"] == "native_structured"
    assert structured["status"] == "blocked"
    assert structured["blocker"] == "structured_driver_unavailable"
    assert structured["remediation"] == "giga harness inspect claude-code --json"
    assert structured["provider_native_continuity"] is False


def test_direct_and_legacy_adapters_default_to_explicit_one_shot():
    direct = _Harness("direct-chat", kind="direct")
    legacy = _Harness("custom-agent")

    assert default_workbench_transport(direct) is ExecutionTransport.ONE_SHOT
    assert (
        effective_workbench_transport(
            direct, {}, configured_default="native_structured"
        )
        is ExecutionTransport.ONE_SHOT
    )
    assert (
        effective_workbench_transport(
            legacy, {}, configured_default="native_structured"
        )
        is ExecutionTransport.ONE_SHOT
    )
    assert (
        effective_workbench_transport(
            legacy, {"execution_transport": "native_structured"}
        )
        is ExecutionTransport.NATIVE_STRUCTURED
    )


def test_proven_custom_driver_defaults_to_structured_and_projects_protocol():
    harness = _StructuredHarness("custom-structured")

    assert default_workbench_transport(harness) is ExecutionTransport.NATIVE_STRUCTURED
    projection = workbench_transport_projection(harness)
    structured = projection["options"][0]
    assert structured["status"] == "ready"
    assert structured["durable"] is True
    assert structured["provider_native_continuity"] is True
    assert "test-structured" in structured["detail"]


def test_legacy_native_input_is_native_terminal_and_explicit_input_is_exact():
    harness = _Harness("claude-code")

    assert (
        effective_workbench_transport(harness, {"invocation_mode": "native"})
        is ExecutionTransport.NATIVE_TERMINAL
    )
    assert (
        effective_workbench_transport(harness, {"execution_transport": "one_shot"})
        is ExecutionTransport.ONE_SHOT
    )
