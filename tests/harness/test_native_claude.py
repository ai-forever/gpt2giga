import json
from dataclasses import replace
from pathlib import Path

import pytest

from gpt2giga_harness.harness_model import signed_harness_model_headers
from gpt2giga_harness.native.base import native_command_plan_to_dict
from gpt2giga_harness.native.claude import ClaudeNativeHistoryConnector
from gpt2giga_harness.native.models import NativeSessionStatus
from gpt2giga_harness.project import project_id_for_root
from gpt2giga_harness.types import (
    GigaChatApiMode,
    HarnessCapability,
    HarnessContext,
    HarnessRequest,
    REDACTED,
)


def test_claude_native_discovery_lists_managed_before_external(tmp_path):
    workspace = tmp_path / "repo"
    data_dir = tmp_path / "data"
    external_home = tmp_path / "external" / ".claude"
    workspace.mkdir()
    project_id = project_id_for_root(workspace)
    managed_file = (
        data_dir
        / "native"
        / "claude"
        / "homes"
        / project_id
        / ".claude"
        / "projects"
        / "repo"
        / "gpt2giga-sess-fix.jsonl"
    )
    external_file = external_home / "projects" / "repo" / "external.jsonl"
    _write_jsonl(
        managed_file,
        (
            {
                "sessionId": "managed-claude-id",
                "session_name": "gpt2giga-sess-fix",
                "timestamp": "2026-07-09T10:00:00Z",
                "type": "user",
                "message": {"content": "Fix harness UI"},
            },
        ),
    )
    _write_jsonl(
        external_file,
        (
            {
                "sessionId": "external-claude-id",
                "timestamp": "2026-07-09T11:00:00Z",
                "message": {"role": "user", "content": "Old review"},
            },
        ),
    )
    connector = ClaudeNativeHistoryConnector(
        data_dir=data_dir,
        external_claude_home=external_home,
        executable="claude",
    )

    managed_only = connector.discover(
        workspace=str(workspace),
        include_external=False,
    )
    all_refs = connector.discover(workspace=str(workspace), include_external=True)

    assert [ref.native_session_id for ref in managed_only] == ["gpt2giga-sess-fix"]
    assert [ref.native_session_id for ref in all_refs] == [
        "gpt2giga-sess-fix",
        "external-claude-id",
    ]
    assert all_refs[0].status is NativeSessionStatus.MANAGED_NATIVE
    assert all_refs[0].can_resume is True
    assert all_refs[0].metadata["project_id"] == project_id
    assert all_refs[0].metadata["source_kind"] == "managed"
    assert all_refs[0].metadata["native_home"] == str(
        data_dir / "native" / "claude" / "homes" / project_id
    )
    assert all_refs[1].status is NativeSessionStatus.EXTERNAL_NATIVE
    assert all_refs[1].can_resume is False
    assert "external Claude sessions" in (all_refs[1].resume_reason or "")
    assert "messages" not in all_refs[0].metadata
    assert "transcript" not in all_refs[0].metadata


def test_claude_native_preview_and_import_tolerate_unknown_jsonl(tmp_path):
    workspace = tmp_path / "repo"
    data_dir = tmp_path / "data"
    external_home = tmp_path / ".claude"
    workspace.mkdir()
    session_file = external_home / "projects" / "repo" / "external.jsonl"
    session_file.parent.mkdir(parents=True)
    session_file.write_text(
        "\n".join(
            (
                "{bad json",
                json.dumps({"type": "summary", "summary": "ignored metadata"}),
                json.dumps(
                    {
                        "sessionId": "external-session",
                        "timestamp": "2026-07-09T10:00:00Z",
                        "type": "user",
                        "message": {
                            "content": [{"text": "first"}, {"text": "second"}],
                        },
                    }
                ),
                json.dumps(
                    {
                        "uuid": "assistant-message-id",
                        "timestamp": "2026-07-09T10:01:00Z",
                        "message": {"role": "assistant", "content": "done"},
                    }
                ),
            )
        ),
        encoding="utf-8",
    )
    connector = ClaudeNativeHistoryConnector(
        data_dir=data_dir,
        external_claude_home=external_home,
    )
    (ref,) = connector.discover(workspace=str(workspace), include_external=True)

    preview = connector.preview(ref, max_messages=1)
    imported = connector.import_ref(ref)

    assert ref.message_count == 2
    assert preview[0].role == "user"
    assert preview[0].content == "first\nsecond"
    assert [message.role for message in imported] == ["user", "assistant"]
    assert imported[1].content == "done"
    assert imported[1].metadata["native_message_id"] == "assistant-message-id"


def test_claude_native_discovery_does_not_stamp_unknown_external_workspace(tmp_path):
    requested_workspace = tmp_path / "requested"
    actual_workspace = tmp_path / "actual"
    external_home = tmp_path / ".claude"
    requested_workspace.mkdir()
    actual_workspace.mkdir()
    known = external_home / "projects" / "known.jsonl"
    unknown = external_home / "projects" / "unknown.jsonl"
    _write_jsonl(
        known,
        (
            {
                "sessionId": "known-session",
                "cwd": str(actual_workspace),
                "type": "user",
                "message": {"content": "known"},
            },
        ),
    )
    _write_jsonl(
        unknown,
        (
            {
                "sessionId": "unknown-session",
                "type": "user",
                "message": {"content": "unknown"},
            },
        ),
    )
    connector = ClaudeNativeHistoryConnector(
        data_dir=tmp_path / "data",
        external_claude_home=external_home,
    )

    refs = connector.discover(
        workspace=str(requested_workspace),
        include_external=True,
    )
    by_session = {ref.native_session_id: ref for ref in refs}

    assert by_session["known-session"].workspace == str(actual_workspace.resolve())
    assert by_session["known-session"].metadata["workspace_evidence"] == "history.cwd"
    assert by_session["unknown-session"].workspace is None
    assert by_session["unknown-session"].metadata["workspace_reason"] == "not_recorded"
    assert "project_id" not in by_session["unknown-session"].metadata


def test_claude_native_import_normalizes_tool_calls_and_results(tmp_path):
    workspace = tmp_path / "repo"
    data_dir = tmp_path / "data"
    external_home = tmp_path / ".claude"
    workspace.mkdir()
    session_file = external_home / "projects" / "repo" / "external.jsonl"
    _write_jsonl(
        session_file,
        (
            {
                "uuid": "tool-call-message",
                "timestamp": "2026-07-13T19:28:18Z",
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_read",
                            "name": "Read",
                            "input": {"file_path": "/repo/README.md"},
                        }
                    ],
                },
            },
            {
                "uuid": "tool-result-message",
                "timestamp": "2026-07-13T19:28:19Z",
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_read",
                            "content": "README contents",
                        }
                    ],
                },
            },
            {
                "timestamp": "2026-07-13T19:28:20Z",
                "role": "assistant",
                "tools_state_id": "toolu_glob",
                "content": [
                    {
                        "function_call": {
                            "name": "Glob",
                            "arguments": {"pattern": "**/*.py"},
                        }
                    }
                ],
            },
            {
                "timestamp": "2026-07-13T19:28:21Z",
                "role": "tool",
                "tools_state_id": "toolu_glob",
                "content": [
                    {
                        "function_result": {
                            "name": "Glob",
                            "result": {"result": "a.py\nb.py"},
                        }
                    }
                ],
            },
        ),
    )
    connector = ClaudeNativeHistoryConnector(
        data_dir=data_dir,
        external_claude_home=external_home,
    )
    (ref,) = connector.discover(workspace=str(workspace), include_external=True)

    imported = connector.import_ref(ref)

    assert [message.role for message in imported] == [
        "assistant",
        "tool",
        "assistant",
        "tool",
    ]
    assert [message.content for message in imported] == ["", "", "", ""]
    assert imported[0].metadata["tool_calls"] == [
        {
            "tool_call_id": "toolu_read",
            "name": "Read",
            "arguments": {"file_path": "/repo/README.md"},
            "status": "running",
        }
    ]
    assert imported[1].metadata["tool_results"] == [
        {
            "tool_call_id": "toolu_read",
            "result": "README contents",
            "status": "completed",
        }
    ]
    assert imported[2].metadata["tool_calls"][0]["tool_call_id"] == "toolu_glob"
    assert imported[2].metadata["tool_calls"][0]["name"] == "Glob"
    assert imported[3].metadata["tool_results"] == [
        {
            "tool_call_id": "toolu_glob",
            "name": "Glob",
            "result": {"result": "a.py\nb.py"},
            "status": "completed",
        }
    ]


def test_claude_native_import_includes_subagent_tool_activity(tmp_path):
    workspace = tmp_path / "repo"
    data_dir = tmp_path / "data"
    external_home = tmp_path / ".claude"
    workspace.mkdir()
    session_file = external_home / "projects" / "repo" / "external.jsonl"
    _write_jsonl(
        session_file,
        (
            {
                "uuid": "root-agent-call",
                "sessionId": "external-session",
                "timestamp": "2026-07-13T19:28:18Z",
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_agent",
                            "name": "Agent",
                            "input": {"subagent_type": "Explore"},
                        }
                    ],
                },
            },
            {
                "uuid": "root-agent-result",
                "timestamp": "2026-07-13T19:28:22Z",
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_agent",
                            "content": "exploration complete",
                        }
                    ],
                },
            },
        ),
    )
    subagent_file = (
        session_file.parent / session_file.stem / "subagents" / "agent-explore.jsonl"
    )
    _write_jsonl(
        subagent_file,
        (
            {
                "uuid": "nested-read-call",
                "timestamp": "2026-07-13T19:28:19Z",
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_read",
                            "name": "Read",
                            "input": {"file_path": "/repo/README.md"},
                        }
                    ],
                },
            },
            {
                "uuid": "nested-read-result",
                "timestamp": "2026-07-13T19:28:20Z",
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_read",
                            "content": "README contents",
                        }
                    ],
                },
            },
            {
                "uuid": "nested-answer",
                "timestamp": "2026-07-13T19:28:21Z",
                "type": "assistant",
                "message": {"role": "assistant", "content": "private summary"},
            },
        ),
    )
    subagent_file.with_suffix(".meta.json").write_text(
        json.dumps(
            {
                "toolUseId": "toolu_agent",
                "agentType": "Explore",
                "description": "Inspect repository structure",
                "spawnDepth": 1,
            }
        ),
        encoding="utf-8",
    )
    connector = ClaudeNativeHistoryConnector(
        data_dir=data_dir,
        external_claude_home=external_home,
    )

    refs = connector.discover(workspace=str(workspace), include_external=True)
    imported = connector.import_ref(refs[0])

    assert len(refs) == 1
    assert [message.created_at for message in imported] == [
        "2026-07-13T19:28:18Z",
        "2026-07-13T19:28:19Z",
        "2026-07-13T19:28:20Z",
        "2026-07-13T19:28:22Z",
    ]
    nested_call = imported[1].metadata["tool_calls"][0]
    nested_result = imported[2].metadata["tool_results"][0]
    assert nested_call == {
        "tool_call_id": "toolu_read",
        "name": "Read",
        "arguments": {"file_path": "/repo/README.md"},
        "status": "running",
        "parent_tool_call_id": "toolu_agent",
        "subagent_id": "agent-explore",
        "subagent_type": "Explore",
        "subagent_description": "Inspect repository structure",
        "subagent_depth": 1,
    }
    assert nested_result["parent_tool_call_id"] == "toolu_agent"
    assert nested_result["subagent_type"] == "Explore"
    assert imported[1].metadata["native_message_id"] == (
        "agent-explore:nested-read-call"
    )
    assert all(message.content != "private summary" for message in imported)
    assert connector.preview(refs[0], max_messages=2) == imported[:2]


def test_claude_native_start_command_uses_managed_home_and_redacts_key(
    tmp_path,
    monkeypatch,
):
    secret = "sk-native-proxy-key-456"
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "upstream-secret")
    workspace = tmp_path / "repo"
    data_dir = tmp_path / "data"
    workspace.mkdir()
    connector = ClaudeNativeHistoryConnector(data_dir=data_dir, executable="claude")
    request = HarnessRequest(
        prompt="Inspect this project",
        model="GigaChat-2-Max",
        api_mode=GigaChatApiMode.V1,
        capability=HarnessCapability.AGENT_CLI,
        mode="edit",
        workspace=str(workspace),
        session_id="sess_abcdef123456",
    )
    context = HarnessContext(
        proxy_url="http://127.0.0.1:8090",
        api_key=secret,
        harness_model_key="model-key",
        default_model="GigaChat-2-Max",
    )

    plan = connector.build_start_command(request, context)
    payload = native_command_plan_to_dict(plan)

    assert plan.command[:5] == (
        "claude",
        "--permission-mode",
        "default",
        "-n",
        plan.metadata["session_name"],
    )
    assert str(plan.metadata["session_name"]).startswith("gpt2giga-sess-abcdef")
    assert "--model" in plan.command
    assert "GigaChat-2-Max" in plan.command
    assert plan.command[-1] == "Inspect this project"
    assert "-p" not in plan.command
    assert "--no-session-persistence" not in plan.command
    assert "GIGACHAT_CREDENTIALS" not in plan.env
    assert plan.env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8090/v1"
    assert plan.env["ANTHROPIC_AUTH_TOKEN"] == secret
    assert plan.env["ANTHROPIC_CUSTOM_HEADERS"] == "\n".join(
        f"{name}:{value}"
        for name, value in signed_harness_model_headers(
            protocol="anthropic",
            model="GigaChat-2-Max",
            key="model-key",
        )
    )
    assert "ANTHROPIC_API_KEY" not in plan.env
    assert plan.env["HOME"] == plan.native_home
    assert secret not in str(payload)
    assert REDACTED in str(payload)
    startup = json.loads((Path(plan.native_home) / ".claude.json").read_text())
    assert startup["hasCompletedOnboarding"] is True
    assert (
        startup["projects"][str(workspace.resolve())]["hasTrustDialogAccepted"] is True
    )


def test_claude_native_start_command_applies_attachment_plan(tmp_path):
    workspace = tmp_path / "repo"
    data_dir = tmp_path / "data"
    workspace.mkdir()
    connector = ClaudeNativeHistoryConnector(data_dir=data_dir, executable="claude")
    request = HarnessRequest(
        prompt="Inspect this project",
        model="GigaChat-2-Max",
        api_mode=GigaChatApiMode.V2,
        capability=HarnessCapability.AGENT_CLI,
        mode="plan",
        workspace=str(workspace),
        session_id="sess_native_attach",
        attachments=(
            {
                "id": "att_doc",
                "filename": "notes.md",
                "kind": "workspace_file",
                "mime_type": "text/markdown",
                "size_bytes": 24,
            },
        ),
        attachment_render_plan={
            "prompt_prefix": "Attachments:\n- @docs/notes.md",
            "warnings": [
                "Claude Code will receive this attachment as a path reference."
            ],
            "metadata": {"transport": "at_file_reference"},
        },
    )
    context = HarnessContext(
        proxy_url="http://127.0.0.1:8090",
        api_key="proxy-key",
    )

    plan = connector.build_start_command(request, context)

    assert plan.command[-1] == "Attachments:\n- @docs/notes.md\n\nInspect this project"
    assert plan.metadata["attachment_render_plan"]["metadata"]["transport"] == (
        "at_file_reference"
    )
    assert plan.metadata["attachment_warnings"] == [
        "Claude Code will receive this attachment as a path reference."
    ]


def test_claude_native_resume_command_requires_managed_ref(tmp_path):
    workspace = tmp_path / "repo"
    data_dir = tmp_path / "data"
    workspace.mkdir()
    project_id = project_id_for_root(workspace)
    connector = ClaudeNativeHistoryConnector(data_dir=data_dir, executable="claude")
    context = HarnessContext(
        proxy_url="http://127.0.0.1:8090",
        api_key="proxy-key",
        harness_model_key="model-key",
    )
    start_plan = connector.build_start_command(
        HarnessRequest(
            prompt="start",
            model="GigaChat-2-Max",
            api_mode=GigaChatApiMode.V1,
            mode="read",
            workspace=str(workspace),
            session_id="sess_resume_contract",
        ),
        context,
    )
    session_name = str(start_plan.metadata["session_name"])
    connector.record_start_snapshot(start_plan)
    session_file = (
        data_dir
        / "native"
        / "claude"
        / "homes"
        / project_id
        / ".claude"
        / "projects"
        / "repo"
        / "managed-claude-id.jsonl"
    )
    _write_jsonl(
        session_file,
        (
            {
                "type": "custom-title",
                "customTitle": session_name,
                "sessionId": "managed-claude-id",
            },
            {
                "sessionId": "managed-claude-id",
                "timestamp": "2026-07-09T10:00:00Z",
                "type": "user",
                "message": {"content": "resume me"},
            },
        ),
    )
    (managed,) = connector.discover(workspace=str(workspace), include_external=False)

    plan = connector.build_resume_command(managed, context)
    external = replace(
        managed,
        status=NativeSessionStatus.EXTERNAL_NATIVE,
        can_resume=False,
    )

    assert plan.command == (
        "claude",
        "--permission-mode",
        "plan",
        "--resume",
        session_name,
    )
    assert plan.metadata["permission_enforcement"]["read_only"] is True
    assert "-p" not in plan.command
    assert "--no-session-persistence" not in plan.command
    assert plan.env["HOME"] == managed.metadata["native_home"]
    assert managed.execution_snapshot == start_plan.execution_snapshot
    assert plan.execution_snapshot == start_plan.execution_snapshot
    assert plan.env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8090/v1"
    assert plan.env["ANTHROPIC_AUTH_TOKEN"] == "proxy-key"
    assert plan.env["ANTHROPIC_CUSTOM_HEADERS"] == "\n".join(
        f"{name}:{value}"
        for name, value in signed_harness_model_headers(
            protocol="anthropic",
            model="GigaChat-2-Max",
            key="model-key",
        )
    )
    with pytest.raises(ValueError, match="Only managed"):
        connector.build_resume_command(external, context)


def test_claude_native_discovery_handles_missing_dirs(tmp_path):
    connector = ClaudeNativeHistoryConnector(
        data_dir=tmp_path / "missing-data",
        external_claude_home=tmp_path / "missing-claude",
    )

    refs = connector.discover(workspace=str(tmp_path / "repo"), include_external=True)

    assert refs == ()


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
