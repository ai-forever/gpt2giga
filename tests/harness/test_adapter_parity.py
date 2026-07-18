from dataclasses import replace

import pytest

from gpt2giga_harness.harnesses.claude_code import ClaudeCodeHarness
from gpt2giga_harness.harnesses.codex_cli import CodexCliHarness
from gpt2giga_harness.harnesses.gemini_cli import GeminiCliHarness
from gpt2giga_harness.native.claude import ClaudeNativeHistoryConnector
from gpt2giga_harness.native.codex import CodexNativeHistoryConnector
from gpt2giga_harness.native.gemini import GeminiNativeHistoryConnector
from gpt2giga_harness.native.models import NativeSessionRef, NativeSessionStatus
from gpt2giga_harness.native.store import native_session_ref_to_dict
from gpt2giga_harness.project import project_id_for_root
from gpt2giga_harness.types import (
    AdapterSupportLevel,
    GigaChatApiMode,
    HarnessChatMessage,
    HarnessContext,
    HarnessRequest,
    spec_to_dict,
)


BUILTIN_ADAPTERS = {
    "codex-cli": CodexCliHarness,
    "claude-code": ClaudeCodeHarness,
    "gemini-cli": GeminiCliHarness,
}

EXPECTED_SUPPORT = {
    "codex-cli": {
        "attachment_transport": "supported",
        "headless_one_shot": "supported",
        "headless_structured_events": "supported",
        "cli_capability_probe": "supported",
        "headless_continuity": "supported",
        "native_initial_prompt": "supported",
        "native_permission_mode": "supported",
        "native_workspace": "supported",
        "native_resume": "partial",
        "native_route_snapshot": "supported",
        "native_durable_lifecycle": "supported",
        "native_terminal_transport": "supported",
        "native_telemetry": "delegated",
        "managed_mcp_native": "supported",
        "managed_mcp_headless": "supported",
        "interactive_approvals": "delegated",
        "external_history": "partial",
        "structured_app_server": "supported",
        "agent_profile_options": "partial",
    },
    "claude-code": {
        "attachment_transport": "partial",
        "headless_one_shot": "supported",
        "headless_structured_events": "supported",
        "cli_capability_probe": "supported",
        "headless_continuity": "unsupported",
        "native_initial_prompt": "supported",
        "native_permission_mode": "supported",
        "native_workspace": "supported",
        "native_resume": "supported",
        "native_route_snapshot": "supported",
        "native_durable_lifecycle": "supported",
        "native_terminal_transport": "supported",
        "native_telemetry": "delegated",
        "managed_mcp_native": "supported",
        "managed_mcp_headless": "supported",
        "interactive_approvals": "delegated",
        "external_history": "partial",
        "structured_app_server": "unsupported",
        "provider_ui_handoff": "supported",
        "agent_profile_options": "partial",
    },
    "gemini-cli": {
        "attachment_transport": "partial",
        "headless_one_shot": "supported",
        "headless_structured_events": "supported",
        "cli_capability_probe": "supported",
        "headless_continuity": "unsupported",
        "native_initial_prompt": "supported",
        "native_permission_mode": "supported",
        "native_workspace": "supported",
        "native_resume": "partial",
        "native_route_snapshot": "supported",
        "native_durable_lifecycle": "supported",
        "native_terminal_transport": "supported",
        "native_telemetry": "delegated",
        "managed_mcp_native": "supported",
        "managed_mcp_headless": "supported",
        "interactive_approvals": "delegated",
        "external_history": "partial",
        "structured_app_server": "supported",
        "agent_profile_options": "partial",
    },
}


@pytest.mark.parametrize("harness_id", BUILTIN_ADAPTERS)
def test_builtin_adapter_capability_matrix_is_serialized_from_specs(harness_id):
    payload = spec_to_dict(BUILTIN_ADAPTERS[harness_id].spec())

    assert payload["protocol_capability_scope"] == "harness_surface"
    assert payload["plugin_metadata"]["protocol_capability_scope"] == (
        "harness_surface"
    )
    assert {
        name: claim["status"] for name, claim in payload["adapter_capabilities"].items()
    } == EXPECTED_SUPPORT[harness_id]
    assert (
        payload["plugin_metadata"]["adapter_capabilities"]
        == payload["adapter_capabilities"]
    )
    assert all(claim["detail"] for claim in payload["adapter_capabilities"].values())

    attachments = payload["attachment_capabilities"]
    assert attachments == payload["plugin_metadata"]["attachments"]["capabilities"]
    assert set(attachments) == set(payload["accepted_attachment_kinds"])
    assert all(item["detail"] for item in attachments.values())
    if harness_id == "codex-cli":
        assert attachments["image"] == {
            "headless": ["cli_image_flag"],
            "native": ["cli_image_flag"],
            "rich": True,
            "required_cli_capabilities": ["--image"],
            "detail": attachments["image"]["detail"],
        }
    else:
        assert attachments["image"]["rich"] is False
        assert "prompt_path_reference" in attachments["image"]["headless"]


@pytest.mark.parametrize(
    ("harness_cls", "history_consumed", "mode_value", "stream_value"),
    (
        (CodexCliHarness, True, "read-only", "--json"),
        (ClaudeCodeHarness, False, "plan", "stream-json"),
        (GeminiCliHarness, False, "--approval-mode=plan", "stream-json"),
    ),
)
def test_headless_request_field_consumption_is_explicit(
    harness_cls,
    history_consumed,
    mode_value,
    stream_value,
    tmp_path,
):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    context = HarnessContext(proxy_url="http://127.0.0.1:8090")
    request = HarnessRequest(
        prompt="current request",
        model="GigaChat-2-Max",
        api_mode=GigaChatApiMode.V1,
        mode="plan",
        stream=True,
        workspace=str(workspace),
        messages=(
            HarnessChatMessage(role="user", content="prior request"),
            HarnessChatMessage(role="user", content="current request"),
        ),
        native_session_id="native-session-not-consumed",
        extra={"managed_mcp_snapshot": {"server_ids": ["reviewed-server"]}},
    )
    harness = harness_cls()

    command = harness.build_command(request, context)
    command_text = " ".join(command)
    if isinstance(harness, CodexCliHarness):
        env = harness.build_env(request, context, codex_home=str(tmp_path / "home"))
    else:
        env = harness.build_env(request, context, home=str(tmp_path / "home"))

    assert "GigaChat-2-Max" in command
    assert "current request" in command_text
    assert ("prior request" in command_text) is history_consumed
    assert mode_value in command
    assert stream_value in command
    assert env["GPT2GIGA_HARNESS_API_MODE"] == "v1"

    without_unconsumed_fields = replace(
        request,
        native_session_id=None,
        extra={},
    )
    assert harness.build_command(without_unconsumed_fields, context) == command
    assert harness.spec().adapter_capabilities["managed_mcp_headless"].status is (
        AdapterSupportLevel.SUPPORTED
    )


@pytest.mark.parametrize(
    ("harness_id", "connector_cls", "prompt_delivered", "permission_value"),
    (
        ("codex-cli", CodexNativeHistoryConnector, True, "read-only"),
        ("claude-code", ClaudeNativeHistoryConnector, True, "plan"),
        ("gemini-cli", GeminiNativeHistoryConnector, True, "plan"),
    ),
)
def test_native_request_field_consumption_and_policy_gap_are_explicit(
    harness_id,
    connector_cls,
    prompt_delivered,
    permission_value,
    tmp_path,
):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    connector_kwargs = {}
    if connector_cls is GeminiNativeHistoryConnector:
        connector_kwargs["capability_probe_runner"] = _supported_gemini_probe
    connector = connector_cls(
        data_dir=tmp_path / "data",
        executable=harness_id,
        **connector_kwargs,
    )
    request = HarnessRequest(
        prompt="inspect the project",
        model="GigaChat-2-Max",
        api_mode=GigaChatApiMode.V1,
        mode="plan",
        workspace=str(workspace),
        session_id="session-contract",
    )

    plan = connector.build_start_command(
        request,
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
    )

    assert plan.execution_snapshot is not None
    assert plan.execution_snapshot.harness_id == harness_id
    assert plan.execution_snapshot.api_mode == "v1"
    assert plan.execution_snapshot.model == "GigaChat-2-Max"
    assert plan.execution_snapshot.native_home == plan.native_home
    assert plan.execution_snapshot.workspace == str(workspace)
    assert plan.execution_snapshot.permission_mode == "plan"
    assert plan.execution_snapshot.tool_config_hash
    assert plan.cwd == str(workspace)
    assert plan.metadata["api_mode"] == "v1"
    assert "GigaChat-2-Max" in plan.command
    assert ("inspect the project" in plan.command) is prompt_delivered
    assert permission_value in plan.command
    permission = plan.metadata["permission_enforcement"]
    assert permission["requested_mode"] == "plan"
    assert permission["read_only"] is True
    assert permission["interactive_approvals"] == "delegated_to_cli_sandbox"
    if harness_id == "gemini-cli":
        assert plan.command[-2:] == (
            "--prompt-interactive",
            "inspect the project",
        )
        assert "initial_prompt" not in plan.metadata
        assert plan.prompt_delivery is not None

    spec = BUILTIN_ADAPTERS[harness_id].spec()
    assert spec.adapter_capabilities["native_workspace"].status is (
        AdapterSupportLevel.SUPPORTED
    )
    expected_prompt_status = (
        AdapterSupportLevel.SUPPORTED
        if prompt_delivered
        else AdapterSupportLevel.UNSUPPORTED
    )
    assert spec.adapter_capabilities["native_initial_prompt"].status is (
        expected_prompt_status
    )


@pytest.mark.parametrize(
    ("harness_id", "connector_cls", "control", "plan_value", "edit_value"),
    (
        (
            "codex-cli",
            CodexNativeHistoryConnector,
            "--sandbox",
            "read-only",
            "workspace-write",
        ),
        (
            "claude-code",
            ClaudeNativeHistoryConnector,
            "--permission-mode",
            "plan",
            "default",
        ),
        (
            "gemini-cli",
            GeminiNativeHistoryConnector,
            "--approval-mode",
            "plan",
            "default",
        ),
    ),
)
@pytest.mark.parametrize("mode", ("plan", "read", "edit"))
def test_native_permission_modes_use_explicit_cli_controls(
    harness_id,
    connector_cls,
    control,
    plan_value,
    edit_value,
    mode,
    tmp_path,
):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    connector = connector_cls(
        data_dir=tmp_path / "data",
        executable=harness_id,
    )

    plan = connector.build_start_command(
        HarnessRequest(
            prompt="",
            api_mode=GigaChatApiMode.V1,
            mode=mode,
            workspace=str(workspace),
            session_id="session-permissions",
        ),
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
    )

    expected = edit_value if mode == "edit" else plan_value
    control_index = plan.command.index(control)
    assert plan.command[control_index + 1] == expected
    permission = plan.metadata["permission_enforcement"]
    assert permission["requested_mode"] == mode
    assert permission["cli_control"] == control
    assert permission["cli_value"] == expected
    assert permission["read_only"] is (mode != "edit")
    assert permission["harness_process_spawn"] == "enforced_by_harness"


@pytest.mark.parametrize(
    ("harness_id", "connector_cls"),
    (
        ("codex-cli", CodexNativeHistoryConnector),
        ("claude-code", ClaudeNativeHistoryConnector),
        ("gemini-cli", GeminiNativeHistoryConnector),
    ),
)
def test_native_edit_snapshot_preserves_source_and_effective_worktree(
    harness_id,
    connector_cls,
    tmp_path,
):
    source_workspace = tmp_path / "repo"
    effective_workspace = tmp_path / "data" / "worktrees" / "sess" / "run"
    source_workspace.mkdir()
    effective_workspace.mkdir(parents=True)
    connector = connector_cls(
        data_dir=tmp_path / "data",
        executable=harness_id,
    )

    plan = connector.build_start_command(
        HarnessRequest(
            prompt="",
            api_mode=GigaChatApiMode.V1,
            mode="edit",
            workspace=str(effective_workspace),
            session_id="session-worktree-snapshot",
            extra={
                "native_source_workspace": str(source_workspace),
                "workspace_execution": {
                    "requested_policy": "auto",
                    "policy": "worktree",
                    "source_workspace": str(source_workspace),
                    "effective_workspace": str(effective_workspace),
                },
            },
        ),
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
    )

    snapshot = plan.execution_snapshot
    assert snapshot is not None
    assert snapshot.workspace == str(source_workspace)
    assert snapshot.source_workspace == str(source_workspace)
    assert snapshot.effective_workspace == str(effective_workspace)
    assert snapshot.workspace_policy == "worktree"
    assert plan.cwd == str(effective_workspace)
    assert plan.metadata["project_id"] == project_id_for_root(source_workspace)


@pytest.mark.parametrize(
    ("harness_id", "connector_cls"),
    (
        ("codex-cli", CodexNativeHistoryConnector),
        ("claude-code", ClaudeNativeHistoryConnector),
        ("gemini-cli", GeminiNativeHistoryConnector),
    ),
)
def test_legacy_native_resume_route_is_limited_instead_of_guessed(
    harness_id,
    connector_cls,
    tmp_path,
):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    connector = connector_cls(data_dir=tmp_path / "data", executable=harness_id)
    ref = NativeSessionRef(
        id=f"{harness_id}-legacy",
        harness_id=harness_id,
        native_session_id="native-session",
        title="legacy",
        workspace=str(workspace),
        source="managed",
        status=NativeSessionStatus.MANAGED_NATIVE,
        created_at=None,
        updated_at=None,
        message_count=None,
        can_preview=True,
        can_import=True,
        can_resume=True,
        metadata={},
    )

    payload = native_session_ref_to_dict(ref)

    assert payload["limitations"] == ["route_unknown"]
    with pytest.raises(ValueError, match="route_unknown"):
        connector.build_resume_command(
            ref,
            HarnessContext(proxy_url="http://127.0.0.1:8090"),
        )
    assert (
        BUILTIN_ADAPTERS[harness_id]
        .spec()
        .adapter_capabilities["native_route_snapshot"]
        .status
        is AdapterSupportLevel.SUPPORTED
    )


def _supported_gemini_probe(command, env, cwd):
    del env, cwd

    class Completed:
        returncode = 0
        stdout = "--prompt-interactive Execute prompt and continue interactively"
        stderr = ""

    assert command[-1] == "--help"
    return Completed()
