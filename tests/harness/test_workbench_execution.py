import pytest

from gpt2giga_harness.execution import ExecutionTransport
from gpt2giga_harness.product_capabilities import ProductCapabilityError
from gpt2giga_harness.structured_sessions import AdapterCapabilitySnapshot
from gpt2giga_harness.types import HarnessCapability, HarnessSpec
from gpt2giga_harness.workbench_execution import (
    admit_workbench_execution,
    default_workbench_transport,
    effective_workbench_transport,
    workbench_admission_projection,
    workbench_transport_projection,
)


class _Harness:
    def __init__(
        self,
        harness_id: str,
        *,
        capabilities: tuple[HarnessCapability, ...] = (HarnessCapability.AGENT_CLI,),
        kind: str = "agent-cli",
    ) -> None:
        self.harness_id = harness_id
        self.capabilities = capabilities
        self.kind = kind

    def spec(self) -> HarnessSpec:
        return HarnessSpec(
            id=self.harness_id,
            title=self.harness_id,
            kind=self.kind,
            description="test harness",
            capabilities=self.capabilities,
        )


class _StructuredHarness(_Harness):
    def __init__(
        self,
        harness_id: str,
        *,
        protocol: str = "test-structured",
    ) -> None:
        super().__init__(harness_id)
        self.protocol = protocol

    def durable_structured_capabilities(self) -> AdapterCapabilitySnapshot:
        return AdapterCapabilitySnapshot(
            adapter_id=self.harness_id,
            adapter_version="1.0.0",
            protocol=self.protocol,
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


def test_product_request_selects_provider_path_without_transport_input():
    codex = _StructuredHarness(
        "codex-cli",
        protocol="codex-app-server-json-rpc-v2",
    )

    admission = admit_workbench_execution(
        codex,
        {
            "workbench_kind": "coding_agent",
            "task_intent": "change",
            "authority": "workspace_write",
        },
    )

    assert admission.transport is ExecutionTransport.NATIVE_STRUCTURED
    assert admission.capability is HarnessCapability.AGENT_CLI
    assert admission.mode == "edit"
    assert admission.status.value == "available"
    assert admission.input_source == "product"
    assert admission.to_dict()["diagnostics"] == {
        "content_free": True,
        "harness_id": "codex-cli",
        "provider_path": "codex_app_server",
        "execution_transport": "native_structured",
        "provider_native_continuity": True,
        "fallback": None,
    }


def test_gemini_product_request_selects_acp_from_reviewed_evidence():
    gemini = _StructuredHarness(
        "gemini-cli",
        protocol="gemini-acp-json-rpc-v1",
    )

    admission = admit_workbench_execution(
        gemini,
        {
            "workbench_kind": "coding_agent",
            "task_intent": "review",
            "authority": "read_only",
        },
    )

    assert admission.to_dict()["diagnostics"]["provider_path"] == "gemini_acp"
    assert admission.transport is ExecutionTransport.NATIVE_STRUCTURED
    assert admission.mode == "read"


def test_product_request_exposes_one_shot_fallback_and_read_only_limit():
    claude = _Harness("claude-code")

    admission = admit_workbench_execution(
        claude,
        {
            "workbench_kind": "coding_agent",
            "task_intent": "change",
            "authority": "read_only",
        },
    )

    assert admission.transport is ExecutionTransport.ONE_SHOT
    assert admission.mode == "read"
    assert admission.status.value == "degraded"
    assert admission.to_dict()["diagnostics"]["fallback"] == (
        "native_structured_to_one_shot"
    )
    assert set(admission.why) == {
        "provider_native_continuity_unavailable",
        "change_intent_limited_by_read_only_authority",
        "admitted_provider_path:claude_provider_owned_one_shot",
    }


def test_direct_chat_rejects_impossible_transport_and_projects_product_mode():
    direct = _Harness(
        "direct-chat",
        capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
        kind="direct",
    )
    projection = workbench_admission_projection(direct)

    assert projection["modes"] == [
        {
            "id": "coding_agent",
            "status": "blocked",
            "why": ["harness_capability_unavailable"],
            "recovery": ["select_compatible_harness"],
        },
        {
            "id": "direct_chat",
            "status": "available",
            "why": ["admitted_provider_path:direct_chat"],
            "recovery": [],
        },
    ]
    with pytest.raises(ProductCapabilityError, match="does not admit"):
        admit_workbench_execution(
            direct,
            {
                "workbench_kind": "direct_chat",
                "task_intent": "ask",
                "authority": "read_only",
                "execution_transport": "native_structured",
            },
        )


def test_incomplete_product_request_fails_closed_without_affecting_legacy_api():
    harness = _Harness("custom-agent")

    with pytest.raises(ProductCapabilityError, match="incomplete product request"):
        admit_workbench_execution(harness, {"workbench_kind": "coding_agent"})

    legacy = admit_workbench_execution(
        harness,
        {"mode": "read", "execution_transport": "one_shot"},
    )
    assert legacy.input_source == "legacy_machine"
    assert legacy.intent.value == "review"
    assert legacy.authority.value == "read_only"
    assert legacy.transport is ExecutionTransport.ONE_SHOT

    unknown_capability = admit_workbench_execution(
        harness,
        {
            "capability": "third_party_machine_capability",
            "mode": "custom-machine-mode",
            "execution_transport": "one_shot",
            "invocation_mode": "provider-owned",
        },
    )
    assert unknown_capability.status.value == "degraded"
    assert set(unknown_capability.why) >= {
        "legacy_capability_unmapped",
        "legacy_mode_unmapped",
    }
