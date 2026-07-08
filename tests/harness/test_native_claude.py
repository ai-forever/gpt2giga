import json
from dataclasses import replace

import pytest

from gpt2giga.harness.native.base import native_command_plan_to_dict
from gpt2giga.harness.native.claude import ClaudeNativeHistoryConnector
from gpt2giga.harness.native.models import NativeSessionStatus
from gpt2giga.harness.project import project_id_for_root
from gpt2giga.harness.types import (
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
        default_model="GigaChat-2-Max",
    )

    plan = connector.build_start_command(request, context)
    payload = native_command_plan_to_dict(plan)

    assert plan.command[:3] == ("claude", "-n", plan.metadata["session_name"])
    assert str(plan.metadata["session_name"]).startswith("gpt2giga-sess-abcdef")
    assert "--model" in plan.command
    assert "GigaChat-2-Max" in plan.command
    assert plan.command[-1] == "Inspect this project"
    assert "-p" not in plan.command
    assert "--no-session-persistence" not in plan.command
    assert "GIGACHAT_CREDENTIALS" not in plan.env
    assert plan.env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8090/v1"
    assert plan.env["ANTHROPIC_API_KEY"] == secret
    assert plan.env["HOME"] == plan.native_home
    assert secret not in str(payload)
    assert REDACTED in str(payload)


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
    context = HarnessContext(proxy_url="http://127.0.0.1:8090", api_key="proxy-key")

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
    session_file = (
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
    _write_jsonl(
        session_file,
        (
            {
                "sessionId": "managed-claude-id",
                "session_name": "gpt2giga-sess-fix",
                "timestamp": "2026-07-09T10:00:00Z",
                "type": "user",
                "message": {"content": "resume me"},
            },
        ),
    )
    connector = ClaudeNativeHistoryConnector(data_dir=data_dir, executable="claude")
    context = HarnessContext(proxy_url="http://127.0.0.1:8090", api_key="proxy-key")
    (managed,) = connector.discover(workspace=str(workspace), include_external=False)

    plan = connector.build_resume_command(managed, context)
    external = replace(
        managed,
        status=NativeSessionStatus.EXTERNAL_NATIVE,
        can_resume=False,
    )

    assert plan.command == ("claude", "--resume", "gpt2giga-sess-fix")
    assert "-p" not in plan.command
    assert "--no-session-persistence" not in plan.command
    assert plan.env["HOME"] == managed.metadata["native_home"]
    assert plan.env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8090/v2"
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
