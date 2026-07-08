import json

from gpt2giga.harness import cli
from gpt2giga.harness.harnesses.claude_code import ClaudeCodeHarness
from gpt2giga.harness.harnesses.codex_cli import CodexCliHarness
from gpt2giga.harness.harnesses.direct_chat import DirectChatHarness
from gpt2giga.harness.harnesses.gemini_cli import GeminiCliHarness
from gpt2giga.harness.sessions import FilesystemHarnessSessionStore
from gpt2giga.harness.types import HarnessResult


def test_cli_harness_list_outputs_direct_chat(capsys):
    exit_code = cli.main(["harness", "list"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "direct-chat" in output


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
