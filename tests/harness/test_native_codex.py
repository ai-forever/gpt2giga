import json
from dataclasses import replace

import pytest

from gpt2giga_harness.native.base import native_command_plan_to_dict
from gpt2giga_harness.native.codex import CodexNativeHistoryConnector
from gpt2giga_harness.native.models import NativeSessionStatus
from gpt2giga_harness.project import project_id_for_root
from gpt2giga_harness.types import (
    GigaChatApiMode,
    HarnessCapability,
    HarnessContext,
    HarnessRequest,
    REDACTED,
)


def test_codex_native_discovery_lists_managed_before_external(tmp_path):
    workspace = tmp_path / "repo"
    data_dir = tmp_path / "data"
    external_home = tmp_path / "external" / ".codex"
    workspace.mkdir()
    project_id = project_id_for_root(workspace)
    managed_file = (
        data_dir
        / "native"
        / "codex"
        / "homes"
        / project_id
        / "sessions"
        / "2026"
        / "managed.jsonl"
    )
    external_file = external_home / "sessions" / "2026" / "external.jsonl"
    _write_jsonl(
        managed_file,
        (
            {
                "session_id": "managed-session",
                "timestamp": "2026-07-09T10:00:00Z",
                "role": "user",
                "content": "Fix harness UI",
            },
        ),
    )
    _write_jsonl(
        external_file,
        (
            {
                "session_id": "external-session",
                "timestamp": "2026-07-09T11:00:00Z",
                "message": {"role": "user", "content": "Old review"},
            },
        ),
    )
    connector = CodexNativeHistoryConnector(
        data_dir=data_dir,
        external_codex_home=external_home,
        executable="codex",
    )

    managed_only = connector.discover(
        workspace=str(workspace),
        include_external=False,
    )
    all_refs = connector.discover(workspace=str(workspace), include_external=True)

    assert [ref.native_session_id for ref in managed_only] == ["managed-session"]
    assert [ref.native_session_id for ref in all_refs] == [
        "managed-session",
        "external-session",
    ]
    assert all_refs[0].status is NativeSessionStatus.MANAGED_NATIVE
    assert all_refs[0].can_resume is True
    assert all_refs[0].metadata["project_id"] == project_id
    assert all_refs[0].metadata["source_kind"] == "managed"
    assert all_refs[0].metadata["native_home"] == str(managed_file.parents[2])
    assert all_refs[1].status is NativeSessionStatus.EXTERNAL_NATIVE
    assert all_refs[1].can_resume is False
    assert "external Codex sessions" in (all_refs[1].resume_reason or "")
    assert "messages" not in all_refs[0].metadata
    assert "transcript" not in all_refs[0].metadata


def test_codex_native_preview_and_import_tolerate_unknown_jsonl(tmp_path):
    workspace = tmp_path / "repo"
    data_dir = tmp_path / "data"
    external_home = tmp_path / ".codex"
    workspace.mkdir()
    session_file = external_home / "sessions" / "session.jsonl"
    session_file.parent.mkdir(parents=True)
    session_file.write_text(
        "\n".join(
            (
                "{bad json",
                json.dumps({"event": "ignored"}),
                json.dumps(
                    {
                        "session_id": "external-session",
                        "created_at": "2026-07-09T10:00:00Z",
                        "message": {
                            "role": "user",
                            "content": [{"text": "first"}, {"text": "second"}],
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-07-09T10:01:00Z",
                        "role": "assistant",
                        "text": "done",
                    }
                ),
            )
        ),
        encoding="utf-8",
    )
    connector = CodexNativeHistoryConnector(
        data_dir=data_dir,
        external_codex_home=external_home,
    )
    (ref,) = connector.discover(workspace=str(workspace), include_external=True)

    preview = connector.preview(ref, max_messages=1)
    imported = connector.import_ref(ref)

    assert ref.message_count == 2
    assert preview[0].role == "user"
    assert preview[0].content == "first\nsecond"
    assert [message.role for message in imported] == ["user", "assistant"]
    assert imported[1].content == "done"


def test_codex_native_start_command_uses_managed_home_and_redacts_key(
    tmp_path,
    monkeypatch,
):
    secret = "sk-native-proxy-key-123"
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "upstream-secret")
    workspace = tmp_path / "repo"
    data_dir = tmp_path / "data"
    workspace.mkdir()
    connector = CodexNativeHistoryConnector(data_dir=data_dir, executable="codex")
    request = HarnessRequest(
        prompt="Inspect this project",
        model="GigaChat-2-Max",
        api_mode=GigaChatApiMode.V2,
        capability=HarnessCapability.AGENT_CLI,
        mode="edit",
        workspace=str(workspace),
    )
    context = HarnessContext(
        proxy_url="http://127.0.0.1:8090",
        api_key=secret,
        default_model="GigaChat-2-Max",
    )

    plan = connector.build_start_command(request, context)
    payload = native_command_plan_to_dict(plan)
    config_text = (
        (data_dir / "native")
        .joinpath(
            "codex",
            "homes",
            project_id_for_root(workspace),
            "config.toml",
        )
        .read_text(encoding="utf-8")
    )

    assert "exec" not in plan.command
    assert "--ephemeral" not in plan.command
    assert plan.command[:3] == ("codex", "--ask-for-approval", "on-request")
    assert "--sandbox" in plan.command
    assert "workspace-write" in plan.command
    assert plan.command[-1] == "Inspect this project"
    assert "GIGACHAT_CREDENTIALS" not in plan.env
    assert plan.env["GPT2GIGA_API_KEY"] == secret
    assert plan.env["CODEX_HOME"] == plan.native_home
    assert 'base_url = "http://127.0.0.1:8090/v2"' in config_text
    assert "sk-native" not in config_text
    assert secret not in str(payload)
    assert REDACTED in str(payload)


def test_codex_native_start_command_applies_attachment_plan(tmp_path):
    workspace = tmp_path / "repo"
    data_dir = tmp_path / "data"
    workspace.mkdir()
    connector = CodexNativeHistoryConnector(data_dir=data_dir, executable="codex")
    request = HarnessRequest(
        prompt="Inspect this project",
        model="GigaChat-2-Max",
        api_mode=GigaChatApiMode.V2,
        capability=HarnessCapability.AGENT_CLI,
        mode="plan",
        workspace=str(workspace),
        attachments=(
            {
                "id": "att_file",
                "filename": "app.py",
                "kind": "workspace_file",
                "mime_type": "text/x-python",
                "size_bytes": 42,
            },
        ),
        attachment_render_plan={
            "prompt_prefix": "Attachments:\n- @src/app.py",
            "cli_args": ["--image", "/tmp/screenshot.png"],
            "warnings": ["image attachments use path references only."],
            "metadata": {"transport": "cli_image_flag_and_prompt_path_reference"},
        },
    )
    context = HarnessContext(proxy_url="http://127.0.0.1:8090", api_key="proxy-key")

    plan = connector.build_start_command(request, context)

    image_index = plan.command.index("--image")
    assert plan.command[image_index + 1] == "/tmp/screenshot.png"
    assert plan.command[-2] == "--"
    assert plan.command[-1] == "Attachments:\n- @src/app.py\n\nInspect this project"
    assert plan.metadata["attachment_render_plan"]["metadata"]["transport"] == (
        "cli_image_flag_and_prompt_path_reference"
    )
    assert plan.metadata["attachment_warnings"] == [
        "image attachments use path references only."
    ]


def test_codex_native_resume_command_requires_managed_ref(tmp_path):
    workspace = tmp_path / "repo"
    data_dir = tmp_path / "data"
    workspace.mkdir()
    project_id = project_id_for_root(workspace)
    session_file = (
        data_dir
        / "native"
        / "codex"
        / "homes"
        / project_id
        / "sessions"
        / "managed.jsonl"
    )
    _write_jsonl(
        session_file,
        (
            {
                "session_id": "managed-session",
                "timestamp": "2026-07-09T10:00:00Z",
                "role": "user",
                "content": "resume me",
            },
        ),
    )
    connector = CodexNativeHistoryConnector(data_dir=data_dir, executable="codex")
    context = HarnessContext(proxy_url="http://127.0.0.1:8090", api_key="proxy-key")
    (managed,) = connector.discover(workspace=str(workspace), include_external=False)

    plan = connector.build_resume_command(managed, context)
    external = replace(
        managed,
        status=NativeSessionStatus.EXTERNAL_NATIVE,
        can_resume=False,
    )

    assert plan.command == ("codex", "resume", "managed-session")
    assert "exec" not in plan.command
    assert "--ephemeral" not in plan.command
    assert plan.env["CODEX_HOME"] == managed.metadata["native_home"]
    assert 'base_url = "http://127.0.0.1:8090/v2"' in (
        session_file.parents[1] / "config.toml"
    ).read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="Only managed"):
        connector.build_resume_command(external, context)


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
