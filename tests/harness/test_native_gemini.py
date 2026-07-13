import json
from dataclasses import replace

import pytest

from gpt2giga_harness.native.base import native_command_plan_to_dict
from gpt2giga_harness.native.gemini import (
    GeminiNativeHistoryConnector,
    project_hash_for_workspace,
)
from gpt2giga_harness.native.models import NativeSessionStatus
from gpt2giga_harness.project import project_id_for_root
from gpt2giga_harness.types import (
    GigaChatApiMode,
    HarnessCapability,
    HarnessContext,
    HarnessRequest,
    REDACTED,
)


def test_gemini_native_discovery_parses_cli_list_sessions_output(tmp_path):
    workspace = tmp_path / "repo"
    data_dir = tmp_path / "data"
    workspace.mkdir()
    calls = []

    class Completed:
        returncode = 0
        stdout = json.dumps(
            {
                "sessions": [
                    {
                        "id": "gemini-session-1",
                        "title": "UI branch",
                        "updated_at": "2026-07-09T11:00:00Z",
                        "message_count": 4,
                    }
                ]
            }
        )
        stderr = ""

    def list_sessions(command, env, cwd):
        calls.append({"command": command, "env": env, "cwd": cwd})
        return Completed()

    connector = GeminiNativeHistoryConnector(
        data_dir=data_dir,
        external_gemini_home=tmp_path / "empty-external-home",
        executable="gemini",
        list_sessions_runner=list_sessions,
    )

    refs = connector.discover(workspace=str(workspace), include_external=True)

    assert calls[0]["command"] == ("gemini", "--list-sessions")
    assert calls[0]["cwd"] == str(workspace)
    assert [ref.native_session_id for ref in refs] == ["gemini-session-1"]
    assert refs[0].title == "UI branch"
    assert refs[0].message_count == 4
    assert refs[0].status is NativeSessionStatus.EXTERNAL_NATIVE
    assert refs[0].can_preview is False
    assert refs[0].can_import is False
    assert refs[0].can_resume is False
    assert refs[0].metadata["source_kind"] == "cli_list"
    assert refs[0].metadata["project_id"] == project_id_for_root(workspace)


def test_gemini_native_checkpoint_scanner_and_preview_import(tmp_path):
    workspace = tmp_path / "repo"
    data_dir = tmp_path / "data"
    external_home = tmp_path / "external-home"
    workspace.mkdir()
    project_id = project_id_for_root(workspace)
    project_hash = project_hash_for_workspace(workspace)
    managed_file = (
        data_dir
        / "native"
        / "gemini"
        / "homes"
        / project_id
        / ".gemini"
        / "tmp"
        / project_hash
        / "managed.json"
    )
    external_file = external_home / ".gemini" / "tmp" / project_hash / "external.jsonl"
    managed_file.parent.mkdir(parents=True)
    managed_file.write_text(
        json.dumps(
            {
                "id": "managed-gemini-session",
                "model": "GigaChat-2-Max",
                "messages": [
                    {
                        "createdAt": "2026-07-09T10:00:00Z",
                        "role": "user",
                        "parts": [{"text": "Fix checkpoint"}],
                    },
                    {
                        "createdAt": "2026-07-09T10:01:00Z",
                        "role": "model",
                        "parts": [{"text": "done"}],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        external_file,
        (
            {
                "session_id": "external-gemini-session",
                "timestamp": "2026-07-09T11:00:00Z",
                "role": "user",
                "content": "External chat",
            },
        ),
    )
    connector = GeminiNativeHistoryConnector(
        data_dir=data_dir,
        external_gemini_home=external_home,
    )

    managed_only = connector.discover(
        workspace=str(workspace),
        include_external=False,
    )
    all_refs = connector.discover(workspace=str(workspace), include_external=True)
    preview = connector.preview(managed_only[0], max_messages=1)
    imported = connector.import_ref(managed_only[0])

    assert [ref.native_session_id for ref in managed_only] == ["managed-gemini-session"]
    assert [ref.native_session_id for ref in all_refs] == [
        "managed-gemini-session",
        "external-gemini-session",
    ]
    assert managed_only[0].status is NativeSessionStatus.MANAGED_NATIVE
    assert managed_only[0].can_resume is True
    assert managed_only[0].metadata["native_home"] == str(
        data_dir / "native" / "gemini" / "homes" / project_id
    )
    assert all_refs[1].status is NativeSessionStatus.EXTERNAL_NATIVE
    assert all_refs[1].can_resume is False
    assert "external Gemini sessions" in (all_refs[1].resume_reason or "")
    assert preview[0].role == "user"
    assert preview[0].content == "Fix checkpoint"
    assert [message.role for message in imported] == ["user", "assistant"]
    assert imported[1].content == "done"


def test_gemini_native_start_command_uses_managed_home_and_redacts_key(
    tmp_path,
    monkeypatch,
):
    secret = "sk-native-proxy-key-789"
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "upstream-secret")
    workspace = tmp_path / "repo"
    data_dir = tmp_path / "data"
    workspace.mkdir()
    connector = GeminiNativeHistoryConnector(
        data_dir=data_dir,
        executable="gemini",
        capability_probe_runner=_supported_prompt_probe,
    )
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
    settings_path = (
        data_dir
        / "native"
        / "gemini"
        / "homes"
        / project_id_for_root(workspace)
        / ".gemini"
        / "settings.json"
    )

    assert plan.command[:1] == ("gemini",)
    assert "-m" in plan.command
    assert "GigaChat-2-Max" in plan.command
    assert plan.command[-2:] == (
        "--prompt-interactive",
        "Inspect this project",
    )
    assert plan.display_command[-1] == "<initial-prompt>"
    assert "-p" not in plan.command
    assert "--skip-trust" not in plan.command
    assert "GIGACHAT_CREDENTIALS" not in plan.env
    assert plan.env["GOOGLE_GEMINI_BASE_URL"] == "http://127.0.0.1:8090/v2"
    assert plan.env["GEMINI_API_KEY"] == secret
    assert plan.env["GEMINI_MODEL"] == "GigaChat-2-Max"
    assert plan.env["HOME"] == plan.native_home
    assert json.loads(settings_path.read_text(encoding="utf-8")) == {
        "security": {"auth": {"selectedType": "gemini-api-key"}}
    }
    assert secret not in str(payload)
    assert REDACTED in str(payload)
    assert "Inspect this project" not in str(payload)
    assert payload["prompt_delivery"]["status"] == "pending"


def test_gemini_native_start_command_delivers_attachment_prompt_without_trimming(
    tmp_path,
):
    workspace = tmp_path / "repo"
    data_dir = tmp_path / "data"
    workspace.mkdir()
    connector = GeminiNativeHistoryConnector(
        data_dir=data_dir,
        executable="gemini",
        capability_probe_runner=_supported_prompt_probe,
    )
    request = HarnessRequest(
        prompt="Inspect this project\n",
        model="GigaChat-2-Max",
        api_mode=GigaChatApiMode.V2,
        capability=HarnessCapability.AGENT_CLI,
        mode="plan",
        workspace=str(workspace),
        attachments=(
            {
                "id": "att_log",
                "filename": "debug.log",
                "kind": "workspace_file",
                "mime_type": "text/plain",
                "size_bytes": 64,
            },
        ),
        attachment_render_plan={
            "prompt_prefix": "Attachments:\n- @logs/debug.log",
            "warnings": [
                "Gemini CLI will receive this image as a path reference only."
            ],
            "metadata": {"transport": "at_file_reference"},
        },
    )
    context = HarnessContext(proxy_url="http://127.0.0.1:8090", api_key="proxy-key")

    plan = connector.build_start_command(request, context)

    assert "-p" not in plan.command
    assert plan.command[-2:] == (
        "--prompt-interactive",
        "Attachments:\n- @logs/debug.log\n\nInspect this project\n",
    )
    assert "initial_prompt" not in plan.metadata
    assert "initial_prompt_present" not in plan.metadata
    assert plan.prompt_delivery is not None
    assert plan.prompt_delivery.byte_count == len(plan.command[-1].encode("utf-8"))
    assert plan.metadata["attachment_render_plan"]["metadata"]["transport"] == (
        "at_file_reference"
    )
    assert plan.metadata["attachment_warnings"] == [
        "Gemini CLI will receive this image as a path reference only."
    ]


def test_gemini_native_start_rejects_cli_without_prompt_interactive(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()

    def unsupported_probe(command, env, cwd):
        del command, env, cwd

        class Completed:
            returncode = 0
            stdout = "Usage: gemini [query]"
            stderr = ""

        return Completed()

    connector = GeminiNativeHistoryConnector(
        data_dir=tmp_path / "data",
        executable="gemini",
        capability_probe_runner=unsupported_probe,
    )

    with pytest.raises(ValueError, match="does not support safe native initial"):
        connector.build_start_command(
            HarnessRequest(
                prompt="Inspect",
                api_mode=GigaChatApiMode.V2,
                workspace=str(workspace),
            ),
            HarnessContext(proxy_url="http://127.0.0.1:8090"),
        )


def test_gemini_native_resume_command_requires_managed_ref(tmp_path):
    workspace = tmp_path / "repo"
    data_dir = tmp_path / "data"
    workspace.mkdir()
    project_id = project_id_for_root(workspace)
    project_hash = project_hash_for_workspace(workspace)
    connector = GeminiNativeHistoryConnector(
        data_dir=data_dir,
        executable="gemini",
        capability_probe_runner=_supported_prompt_probe,
    )
    context = HarnessContext(proxy_url="http://127.0.0.1:8090", api_key="proxy-key")
    start_plan = connector.build_start_command(
        HarnessRequest(
            prompt="start",
            model="GigaChat-2-Max",
            api_mode=GigaChatApiMode.V1,
            mode="plan",
            workspace=str(workspace),
        ),
        context,
    )
    connector.record_start_snapshot(start_plan)
    session_file = (
        data_dir
        / "native"
        / "gemini"
        / "homes"
        / project_id
        / ".gemini"
        / "tmp"
        / project_hash
        / "managed.jsonl"
    )
    _write_jsonl(
        session_file,
        (
            {
                "session_id": "managed-gemini-session",
                "timestamp": "2026-07-09T10:00:00Z",
                "model": "GigaChat-2-Max",
                "role": "user",
                "content": "resume me",
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

    assert plan.command == ("gemini", "--resume", "managed-gemini-session")
    assert "-p" not in plan.command
    assert "--skip-trust" not in plan.command
    assert plan.env["HOME"] == managed.metadata["native_home"]
    assert managed.execution_snapshot == start_plan.execution_snapshot
    assert plan.execution_snapshot == start_plan.execution_snapshot
    assert plan.env["GOOGLE_GEMINI_BASE_URL"] == "http://127.0.0.1:8090/v1"
    assert plan.env["GEMINI_MODEL"] == "GigaChat-2-Max"
    with pytest.raises(ValueError, match="Only managed"):
        connector.build_resume_command(external, context)


def test_gemini_native_missing_executable_still_discovers_managed_files(
    tmp_path,
    monkeypatch,
):
    workspace = tmp_path / "repo"
    data_dir = tmp_path / "data"
    workspace.mkdir()
    project_id = project_id_for_root(workspace)
    project_hash = project_hash_for_workspace(workspace)
    session_file = (
        data_dir
        / "native"
        / "gemini"
        / "homes"
        / project_id
        / ".gemini"
        / "tmp"
        / project_hash
        / "managed.jsonl"
    )
    _write_jsonl(
        session_file,
        (
            {
                "session_id": "managed-gemini-session",
                "timestamp": "2026-07-09T10:00:00Z",
                "role": "user",
                "content": "managed without executable",
            },
        ),
    )

    def fail_list_sessions(command, env, cwd):
        raise AssertionError("gemini --list-sessions should not run")

    monkeypatch.setattr(
        "gpt2giga_harness.executables.shutil.which",
        lambda executable: None,
    )
    connector = GeminiNativeHistoryConnector(
        data_dir=data_dir,
        external_gemini_home=tmp_path / "empty-external-home",
        list_sessions_runner=fail_list_sessions,
    )

    refs = connector.discover(workspace=str(workspace), include_external=True)

    assert [ref.native_session_id for ref in refs] == ["managed-gemini-session"]


def _supported_prompt_probe(command, env, cwd):
    del env, cwd

    class Completed:
        returncode = 0
        stdout = "--prompt-interactive Execute prompt and continue interactively"
        stderr = ""

    assert command[-1] == "--help"
    return Completed()


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
