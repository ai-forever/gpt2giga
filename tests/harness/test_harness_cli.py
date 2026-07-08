import json

import pytest

from gpt2giga.harness import cli
from gpt2giga.harness.harnesses.claude_code import ClaudeCodeHarness
from gpt2giga.harness.harnesses.codex_cli import CodexCliHarness
from gpt2giga.harness.harnesses.direct_chat import DirectChatHarness
from gpt2giga.harness.harnesses.gemini_cli import GeminiCliHarness
from gpt2giga.harness.native.models import (
    NativeSessionRef,
    NativeSessionStatus,
    NativeTranscriptMessage,
)
from gpt2giga.harness.native.registry import NativeHistoryConnectorRegistry
from gpt2giga.harness.sessions import FilesystemHarnessSessionStore
from gpt2giga.harness.types import HarnessResult


def test_cli_harness_list_outputs_direct_chat(capsys):
    exit_code = cli.main(["harness", "list"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "direct-chat" in output


def test_cli_harness_list_json_shows_native_metadata(capsys):
    exit_code = cli.main(["harness", "list", "--json"])

    rows = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    by_id = {row["id"]: row for row in rows}
    assert by_id["codex-cli"]["native"] is True
    assert by_id["codex-cli"]["default_invocation_mode"] == "native"
    assert by_id["direct-chat"]["native"] is False


def test_cli_harness_inspect_json_shows_native_support(capsys):
    exit_code = cli.main(["harness", "inspect", "claude-code", "--json"])

    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["spec"]["supports_native_sessions"] is True
    assert payload["spec"]["supports_external_history"] is True
    assert payload["spec"]["default_invocation_mode"] == "native"


def test_cli_project_info_json_reports_workspace(capsys, tmp_path):
    exit_code = cli.main(["project", "info", "--workspace", str(tmp_path), "--json"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["project"]["root"] == str(tmp_path)
    assert output["project"]["name"] == tmp_path.name
    assert output["config"]["exists"] is False
    assert output["defaults"]["harness"] == "codex-cli"


def test_cli_init_alias_writes_project_config(capsys, tmp_path):
    exit_code = cli.main(
        [
            "init",
            "--workspace",
            str(tmp_path),
            "--name",
            "cli-demo",
            "--json",
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["project"]["name"] == "cli-demo"
    assert output["config"]["exists"] is True
    assert (tmp_path / ".giga" / "harness.toml").exists()


def test_cli_chat_passes_api_mode_and_model(monkeypatch, capsys):
    captured = {}

    def fake_run(self, request, context):
        captured["request"] = request
        captured["context"] = context
        return HarnessResult(ok=True, text="ok")

    monkeypatch.setattr(DirectChatHarness, "run", fake_run)

    exit_code = cli.main(
        [
            "chat",
            "--api-mode",
            "v1",
            "--model",
            "GigaChat-2-Max",
            "hello",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.strip() == "ok"
    assert captured["request"].api_mode.value == "v1"
    assert captured["request"].model == "GigaChat-2-Max"
    assert captured["request"].prompt == "hello"


def test_cli_no_start_proxy_override(monkeypatch, capsys):
    captured = {}

    def fake_run(self, request, context):
        captured["context"] = context
        return HarnessResult(ok=True, text="ok")

    monkeypatch.setattr(DirectChatHarness, "run", fake_run)

    exit_code = cli.main(["chat", "--no-start-proxy", "hello"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.strip() == "ok"
    assert captured["context"].auto_start_proxy is False


def test_cli_agent_alias_passes_workspace(monkeypatch, capsys, tmp_path):
    captured = {}

    def fake_run(self, request, context):
        captured["request"] = request
        captured["context"] = context
        return HarnessResult(ok=True, text="ok")

    monkeypatch.setattr(CodexCliHarness, "run", fake_run)

    exit_code = cli.main(
        [
            "run",
            "--agent",
            "codex",
            "--mode",
            "plan",
            "--workspace",
            str(tmp_path),
            "inspect",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.strip() == "ok"
    assert captured["request"].workspace == str(tmp_path.resolve())
    assert captured["request"].capability.value == "agent_cli"


def test_cli_agent_aliases_include_claude_and_gemini(monkeypatch, capsys):
    captured = []

    def fake_run(self, request, context):
        captured.append((type(self).__name__, request.prompt))
        return HarnessResult(ok=True, text="ok")

    monkeypatch.setattr(ClaudeCodeHarness, "run", fake_run)
    monkeypatch.setattr(GeminiCliHarness, "run", fake_run)

    assert cli.main(["run", "--agent", "claude", "inspect"]) == 0
    assert cli.main(["run", "--agent", "gemini", "inspect"]) == 0

    output = capsys.readouterr().out
    assert output.strip().splitlines() == ["ok", "ok"]
    assert captured == [
        ("ClaudeCodeHarness", "inspect"),
        ("GeminiCliHarness", "inspect"),
    ]


def test_cli_session_list_json_uses_configured_data_dir(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(tmp_path))
    store = FilesystemHarnessSessionStore(tmp_path)
    session = store.create_session(title="CLI session", default_harness_id="echo")

    exit_code = cli.main(["session", "list", "--json"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output[0]["id"] == session.id
    assert output[0]["title"] == "CLI session"


def test_cli_session_show_json(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(tmp_path))
    store = FilesystemHarnessSessionStore(tmp_path)
    session = store.create_session(title="CLI session", default_harness_id="echo")

    exit_code = cli.main(["session", "show", session.id, "--json"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["session"]["id"] == session.id
    assert output["messages"] == []


def test_cli_native_sync_list_and_import_json(monkeypatch, capsys, tmp_path):
    data_dir = tmp_path / "data"
    workspace = tmp_path / "repo"
    workspace.mkdir()
    ref = NativeSessionRef(
        id="native_fake_1",
        harness_id="fake-cli",
        native_session_id="native-session-1",
        title="Fake native session",
        workspace=str(workspace),
        source="external",
        status=NativeSessionStatus.EXTERNAL_NATIVE,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:01:00Z",
        message_count=3,
        can_preview=True,
        can_import=True,
        can_resume=False,
        metadata={"model": "GigaChat-2-Max", "api_mode": "v2"},
    )
    registry = NativeHistoryConnectorRegistry()
    registry.register(
        FakeNativeConnector(
            ref,
            import_messages=(
                NativeTranscriptMessage(role="user", content="native user"),
                NativeTranscriptMessage(role="model", content="native answer"),
                NativeTranscriptMessage(role="mystery", content="skip me"),
            ),
        )
    )
    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(data_dir))
    monkeypatch.setattr(
        cli,
        "create_default_native_registry",
        lambda *, data_dir: registry,
    )

    sync_code = cli.main(
        [
            "native",
            "sync",
            "--harness",
            "fake-cli",
            "--workspace",
            str(workspace),
            "--include-external",
            "--json",
        ]
    )
    sync_payload = json.loads(capsys.readouterr().out)

    assert sync_code == 0
    assert sync_payload["sessions"][0]["id"] == ref.id

    list_code = cli.main(
        [
            "native",
            "list",
            "--harness",
            "fake-cli",
            "--workspace",
            str(workspace),
            "--include-external",
            "--json",
        ]
    )
    list_payload = json.loads(capsys.readouterr().out)

    assert list_code == 0
    assert [item["id"] for item in list_payload] == [ref.id]

    import_code = cli.main(["native", "import", ref.id, "--json"])
    import_payload = json.loads(capsys.readouterr().out)

    assert import_code == 0
    assert import_payload["session"]["default_harness_id"] == "fake-cli"
    assert import_payload["imported_message_count"] == 2
    assert import_payload["skipped_item_count"] == 1
    assert [message["role"] for message in import_payload["messages"]] == [
        "user",
        "assistant",
    ]
    store = FilesystemHarnessSessionStore(data_dir)
    bundle = store.get_session_bundle(import_payload["session"]["id"])
    assert bundle.native_links[0].native_ref_id == ref.id
    assert bundle.events[0].type == "native_import_warning"


@pytest.mark.parametrize(
    ("harness_id", "forbidden"),
    (
        ("codex-cli", ("exec", "--ephemeral")),
        ("claude-code", ("-p", "--no-session-persistence")),
        ("gemini-cli", ("-p", "--skip-trust")),
    ),
)
def test_cli_native_dry_run_prints_command_plan_without_headless_run(
    harness_id,
    forbidden,
    monkeypatch,
    capsys,
    tmp_path,
):
    secret = "sk-native-cli-key-123"

    def fail_run(self, request, context):
        raise AssertionError("headless run should not be called for native dry-run")

    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GPT2GIGA_HARNESS_API_KEY", secret)
    monkeypatch.setattr(CodexCliHarness, "run", fail_run)
    monkeypatch.setattr(ClaudeCodeHarness, "run", fail_run)
    monkeypatch.setattr(GeminiCliHarness, "run", fail_run)

    exit_code = cli.main(
        [
            "harness",
            "run",
            harness_id,
            "--native",
            "--dry-run",
            "--prompt",
            "Inspect",
            "--model",
            "GigaChat-2-Max",
            "--api-mode",
            "v2",
            "--json",
        ]
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    command = payload["raw"]["native_command_plan"]["command"]

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["text"] == "native dry run"
    assert payload["raw"]["native_command_plan"]["metadata"]["managed"] is True
    for item in forbidden:
        assert item not in command
    assert secret not in output
    assert payload["raw"]["native_command_plan"]["env"] != {}


class FakeNativeConnector:
    harness_id = "fake-cli"

    def __init__(
        self,
        ref: NativeSessionRef,
        *,
        import_messages: tuple[NativeTranscriptMessage, ...],
    ) -> None:
        self.ref = ref
        self.import_messages = import_messages

    def discover(self, *, workspace, include_external):
        assert include_external is True
        return (self.ref,)

    def preview(self, ref, *, max_messages=20):
        return self.import_messages[:max_messages]

    def import_ref(self, ref):
        assert ref.id == self.ref.id
        return self.import_messages
