from gpt2giga.harness import proxy
from gpt2giga.harness.harnesses.claude_code import ClaudeCodeHarness
from gpt2giga.harness.types import (
    Availability,
    GigaChatApiMode,
    HarnessContext,
    HarnessRequest,
)


def test_claude_code_sanitizes_env(monkeypatch):
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "secret")
    monkeypatch.setenv("GIGACHAT_ACCESS_TOKEN", "token")
    monkeypatch.setenv("PATH", "/usr/bin")

    env = ClaudeCodeHarness().build_env(
        HarnessRequest(prompt="inspect", api_mode=GigaChatApiMode.V1),
        HarnessContext(proxy_url="http://127.0.0.1:8090", api_key="proxy-key"),
    )

    assert "GIGACHAT_CREDENTIALS" not in env
    assert "GIGACHAT_ACCESS_TOKEN" not in env
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8090/v1"
    assert env["ANTHROPIC_API_KEY"] == "proxy-key"
    assert env["GPT2GIGA_HARNESS_API_MODE"] == "v1"


def test_claude_code_dry_run_redacts_proxy_key(monkeypatch):
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "secret")

    result = ClaudeCodeHarness().run(
        HarnessRequest(prompt="inspect", extra={"dry_run": True}),
        HarnessContext(proxy_url="http://127.0.0.1:8090", api_key="proxy-key"),
    )

    assert result.ok is True
    assert "GIGACHAT_CREDENTIALS" not in result.raw["env"]
    assert "proxy-key" not in str(result.raw)
    assert "secret" not in str(result.raw)


def test_claude_code_mode_mapping_plan_read_edit():
    harness = ClaudeCodeHarness()
    context = HarnessContext(proxy_url="http://127.0.0.1:8090")

    expected = {
        "plan": "plan",
        "read": "plan",
        "edit": "default",
    }
    for mode, permission_mode in expected.items():
        command = harness.build_command(HarnessRequest(prompt="x", mode=mode), context)
        assert command[command.index("--permission-mode") + 1] == permission_mode
        assert "--dangerously-skip-permissions" not in command


def test_claude_code_reports_missing_workspace(tmp_path):
    missing_workspace = tmp_path / "missing"

    result = ClaudeCodeHarness().run(
        HarnessRequest(prompt="x", workspace=str(missing_workspace)),
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
    )

    assert result.ok is False
    assert result.error == f"Workspace does not exist: {missing_workspace}"


def test_claude_code_proxy_preflight_failure_prevents_cli_run(monkeypatch):
    def fail_run_command(*args, **kwargs):
        raise AssertionError("Claude Code should not run when proxy preflight fails")

    monkeypatch.setattr(
        ClaudeCodeHarness,
        "availability",
        lambda self: Availability.available("claude available"),
    )
    monkeypatch.setattr(
        proxy,
        "ensure_proxy_available",
        lambda context, api_mode: proxy.ProxyStartup(
            ok=False,
            error="missing GigaChat credentials",
        ),
    )
    monkeypatch.setattr(
        "gpt2giga.harness.harnesses.claude_code.run_command",
        fail_run_command,
    )

    result = ClaudeCodeHarness().run(
        HarnessRequest(prompt="inspect"),
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
    )

    assert result.ok is False
    assert result.error == "missing GigaChat credentials"
