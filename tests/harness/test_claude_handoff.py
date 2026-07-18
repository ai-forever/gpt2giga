import json
from pathlib import Path

import pytest

from gpt2giga_harness.claude_handoff import (
    ClaudeHandoffAction,
    ClaudeHandoffError,
    ClaudeHandoffLaunchMode,
    claude_execution_surfaces_to_dict,
    claude_handoff_capability_to_dict,
    claude_handoff_plan_to_dict,
    load_claude_handoff_evidence,
    parse_claude_handoff_evidence,
    plan_claude_handoff,
    probe_claude_handoff,
)
from gpt2giga_harness.cli_capabilities import CliCapabilitySnapshot


def test_packaged_claude_handoff_evidence_is_strict_and_hashed():
    evidence = load_claude_handoff_evidence()

    assert evidence.reviewed_at == "2026-07-18"
    assert evidence.minimum_cli_version == "2.1.51"
    assert evidence.remote_control_url.endswith("/remote-control")
    assert evidence.command_reference_url.endswith("/commands")
    assert len(evidence.evidence_hash) == 64

    payload = {
        "schema_version": 2,
        "reviewed_at": "2026-07-18",
        "minimum_cli_version": "2.1.51",
        "sources": {},
    }
    with pytest.raises(ClaudeHandoffError, match="schema is unsupported"):
        parse_claude_handoff_evidence(payload)


def test_handoff_probe_requires_versioned_cli_and_both_remote_control_claims():
    ready = probe_claude_handoff(_cli_snapshot(), platform="darwin")

    assert ready.provider_ui_handoff is True
    assert ready.status == "supported"
    assert ready.available_actions == tuple(ClaudeHandoffAction)
    assert ready.queueable is False
    assert ready.durable is False
    assert ready.structured_events is False
    assert ready.live_approvals is False
    payload = claude_handoff_capability_to_dict(ready)
    assert payload["content_free"] is True
    assert "provider_url" not in payload

    for capabilities, blocker in (
        ({"--remote-control": True, "remote-control": False}, "command_unproven"),
        ({"--remote-control": False, "remote-control": True}, "flag_missing"),
    ):
        blocked = probe_claude_handoff(
            _cli_snapshot(capabilities=capabilities), platform="darwin"
        )
        assert blocked.provider_ui_handoff is False
        assert blocker in (blocked.blocker or "")

    unknown = probe_claude_handoff(
        _cli_snapshot(
            parsed_version="2.2.0",
            version_window_status="above_window",
            status="degraded",
        ),
        platform="darwin",
    )
    assert unknown.blocker == "cli_contract_unproven"


@pytest.mark.parametrize(
    ("action", "surface", "command", "external_process", "external_ui"),
    (
        (
            ClaudeHandoffAction.LAUNCH_NEW,
            "argv",
            ("/opt/homebrew/bin/claude", "--remote-control"),
            True,
            False,
        ),
        (
            ClaudeHandoffAction.ATTACH_CURRENT,
            "slash_command",
            ("/remote-control",),
            False,
            False,
        ),
        (
            ClaudeHandoffAction.OPEN_PROVIDER_UI,
            "slash_command",
            ("/desktop",),
            False,
            True,
        ),
        (
            ClaudeHandoffAction.DISCONNECT,
            "slash_command",
            ("/remote-control",),
            False,
            False,
        ),
        (
            ClaudeHandoffAction.STOP,
            "slash_command",
            ("/exit",),
            False,
            False,
        ),
    ),
)
def test_handoff_preview_is_exact_content_free_and_never_queueable(
    tmp_path, action, surface, command, external_process, external_ui
):
    plan = plan_claude_handoff(
        _cli_snapshot(command=("/opt/homebrew/bin/claude", "--token", "secret")),
        action=action,
        workspace=tmp_path,
        platform="darwin",
    )
    payload = claude_handoff_plan_to_dict(plan)

    assert plan.status == "ready"
    assert plan.surface == surface
    assert plan.command == command
    assert plan.external_process_may_open is external_process
    assert plan.external_ui_may_open is external_ui
    assert plan.machine_executable is False
    assert plan.ownership == "provider_owned"
    assert plan.transport == "provider_handoff"
    assert plan.runtime_ownership == "request_bound"
    assert plan.queueable is False
    assert plan.durable is False
    assert plan.resumable_by_harness is False
    assert plan.automatic_retry is False
    assert payload["workspace"] == str(tmp_path)
    assert payload["content_free"] is True
    assert "secret" not in json.dumps(payload)
    assert "session_url" not in payload
    assert "provider_session_id" not in payload


def test_launch_server_and_non_desktop_open_degrade_without_invented_automation(
    tmp_path,
):
    server = plan_claude_handoff(
        _cli_snapshot(),
        action=ClaudeHandoffAction.LAUNCH_NEW,
        launch_mode=ClaudeHandoffLaunchMode.SERVER,
        workspace=tmp_path,
        platform="linux",
    )
    desktop = plan_claude_handoff(
        _cli_snapshot(),
        action=ClaudeHandoffAction.OPEN_PROVIDER_UI,
        workspace=tmp_path,
        platform="linux",
    )

    assert server.command == ("/opt/homebrew/bin/claude", "remote-control")
    assert desktop.status == "manual_or_blocked"
    assert desktop.command == ()
    assert desktop.blocker == "claude_desktop_platform_unsupported"
    assert "Remote Control session list" in desktop.instruction


def test_execution_surfaces_keep_handoff_distinct_from_embedding_and_terminal():
    surfaces = claude_execution_surfaces_to_dict(
        probe_claude_handoff(_cli_snapshot(), platform="darwin")
    )
    by_id = {item["id"]: item for item in surfaces}

    assert set(by_id) == {
        "one_shot",
        "native_terminal",
        "provider_handoff",
        "native_structured_embedded",
    }
    assert by_id["provider_handoff"]["ownership"] == "provider_owned"
    assert by_id["provider_handoff"]["queueable"] is False
    assert by_id["native_structured_embedded"]["status"] == "blocked"
    assert "durable_approval" in by_id["native_structured_embedded"]["blocker"]


def test_handoff_preview_rejects_relative_or_missing_workspace(tmp_path):
    with pytest.raises(ClaudeHandoffError, match="existing directory"):
        plan_claude_handoff(
            _cli_snapshot(),
            action=ClaudeHandoffAction.LAUNCH_NEW,
            workspace=Path("relative"),
            platform="darwin",
        )
    with pytest.raises(ClaudeHandoffError, match="existing directory"):
        plan_claude_handoff(
            _cli_snapshot(),
            action=ClaudeHandoffAction.LAUNCH_NEW,
            workspace=tmp_path / "missing",
            platform="darwin",
        )


def _cli_snapshot(
    *,
    capabilities=None,
    command=("/opt/homebrew/bin/claude",),
    parsed_version="2.1.212",
    version_window_status="in_window",
    status="supported",
):
    return CliCapabilitySnapshot(
        harness_id="claude-code",
        status=status,
        version="2.1.212 (Claude Code)",
        parsed_version=parsed_version,
        command=command,
        capabilities=capabilities or {"--remote-control": True, "remote-control": True},
        event_schema="claude-stream-json-v1",
        history_schema="claude-project-jsonl-v1",
        warning=None,
        evidence="fixture",
        version_window_status=version_window_status,
        minimum_version="2.1.0",
        maximum_version_exclusive="2.2.0",
    )
