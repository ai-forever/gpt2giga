from gpt2giga.harness.harnesses.codex_cli import CodexCliHarness
from gpt2giga.harness.types import GigaChatApiMode, HarnessContext, HarnessRequest


def test_codex_cli_sanitizes_env(monkeypatch):
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "secret")
    monkeypatch.setenv("GIGACHAT_ACCESS_TOKEN", "token")
    monkeypatch.setenv("PATH", "/usr/bin")

    env = CodexCliHarness().build_env(
        HarnessRequest(prompt="inspect", api_mode=GigaChatApiMode.V2),
        HarnessContext(proxy_url="http://127.0.0.1:8090", api_key="proxy-key"),
        codex_home="/tmp/codex-home",
    )

    assert "GIGACHAT_CREDENTIALS" not in env
    assert "GIGACHAT_ACCESS_TOKEN" not in env
    assert env["GPT2GIGA_API_KEY"] == "proxy-key"
    assert env["CODEX_HOME"] == "/tmp/codex-home"


def test_codex_cli_does_not_include_gigachat_credentials(monkeypatch):
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "secret")

    result = CodexCliHarness().run(
        HarnessRequest(prompt="inspect", extra={"dry_run": True}),
        HarnessContext(proxy_url="http://127.0.0.1:8090", api_key="proxy-key"),
    )

    assert result.ok is True
    assert "GIGACHAT_CREDENTIALS" not in result.raw["env"]
    assert "secret" not in str(result.raw)


def test_codex_cli_mode_mapping_plan_read_edit():
    harness = CodexCliHarness()
    context = HarnessContext(proxy_url="http://127.0.0.1:8090")

    expected = {
        "plan": "read-only",
        "read": "read-only",
        "edit": "workspace-write",
    }
    for mode, sandbox in expected.items():
        command = harness.build_command(HarnessRequest(prompt="x", mode=mode), context)
        assert command[command.index("--sandbox") + 1] == sandbox


def test_codex_cli_uses_top_level_approval_flag():
    command = CodexCliHarness().build_command(
        HarnessRequest(prompt="x"),
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
    )

    assert "--approval-policy" not in command
    assert command[1:4] == ("--ask-for-approval", "on-request", "exec")
