from gpt2giga.harness import proxy
from gpt2giga.harness.harnesses.agent_cli import executable_availability, run_command
from gpt2giga.harness.harnesses.gemini_cli import GeminiCliHarness
from gpt2giga.harness.types import (
    Availability,
    AvailabilityStatus,
    GigaChatApiMode,
    HarnessContext,
    HarnessRequest,
    HarnessResult,
)


def test_gemini_cli_sanitizes_env(monkeypatch):
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "secret")
    monkeypatch.setenv("GIGACHAT_ACCESS_TOKEN", "token")
    monkeypatch.setenv("PATH", "/usr/bin")

    env = GeminiCliHarness().build_env(
        HarnessRequest(
            prompt="inspect",
            model="GigaChat-2-Max",
            api_mode=GigaChatApiMode.V2,
        ),
        HarnessContext(proxy_url="http://127.0.0.1:8090", api_key="proxy-key"),
        home="/tmp/gemini-home",
    )

    assert "GIGACHAT_CREDENTIALS" not in env
    assert "GIGACHAT_ACCESS_TOKEN" not in env
    assert env["HOME"] == "/tmp/gemini-home"
    assert env["GOOGLE_GEMINI_BASE_URL"] == "http://127.0.0.1:8090/v2"
    assert env["GEMINI_API_KEY"] == "proxy-key"
    assert env["GEMINI_MODEL"] == "GigaChat-2-Max"
    assert env["GEMINI_CLI_TRUST_WORKSPACE"] == "true"


def test_gemini_cli_dry_run_redacts_proxy_key(monkeypatch):
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "secret")

    result = GeminiCliHarness().run(
        HarnessRequest(prompt="inspect", extra={"dry_run": True}),
        HarnessContext(proxy_url="http://127.0.0.1:8090", api_key="proxy-key"),
    )

    assert result.ok is True
    assert "GIGACHAT_CREDENTIALS" not in result.raw["env"]
    assert "proxy-key" not in str(result.raw)
    assert "secret" not in str(result.raw)


def test_gemini_cli_mode_mapping_plan_read_edit():
    harness = GeminiCliHarness()
    context = HarnessContext(proxy_url="http://127.0.0.1:8090")

    for mode in ("plan", "read"):
        command = harness.build_command(HarnessRequest(prompt="x", mode=mode), context)
        assert "--approval-mode=plan" in command
        assert "--approval-mode=yolo" not in command

    edit_command = harness.build_command(
        HarnessRequest(prompt="x", mode="edit"),
        context,
    )
    assert "--approval-mode=plan" not in edit_command
    assert "--approval-mode=yolo" not in edit_command


def test_gemini_cli_reports_missing_workspace(tmp_path):
    missing_workspace = tmp_path / "missing"

    result = GeminiCliHarness().run(
        HarnessRequest(prompt="x", workspace=str(missing_workspace)),
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
    )

    assert result.ok is False
    assert result.error == f"Workspace does not exist: {missing_workspace}"


def test_agent_cli_executable_availability_reports_broken_binary(monkeypatch):
    def fake_run(*args, **kwargs):
        raise OSError("bad interpreter")

    monkeypatch.setattr(
        "gpt2giga.harness.harnesses.agent_cli.subprocess.run",
        fake_run,
    )

    availability = executable_availability(
        executable="/tmp/gemini",
        executable_name="gemini",
        install_hint="install gemini",
    )

    assert availability.status == AvailabilityStatus.ERROR
    assert availability.reason == "gemini executable failed to run"


def test_agent_cli_run_command_redacts_known_proxy_keys(monkeypatch):
    class Completed:
        returncode = 1
        stdout = "failed with proxy-key"
        stderr = "stderr proxy-key"

    monkeypatch.setattr(
        "gpt2giga.harness.harnesses.agent_cli.subprocess.run",
        lambda *args, **kwargs: Completed(),
    )

    result = run_command(
        label="Gemini CLI",
        command=("gemini",),
        env={"GEMINI_API_KEY": "proxy-key"},
        cwd=None,
        timeout_seconds=1,
    )

    assert "proxy-key" not in result.text
    assert "proxy-key" not in result.raw["stdout"]
    assert "proxy-key" not in result.raw["stderr"]


def test_gemini_cli_autostart_uses_generated_proxy_key(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        GeminiCliHarness,
        "availability",
        lambda self: Availability.available("gemini available"),
    )
    monkeypatch.setattr(
        proxy,
        "ensure_proxy_available",
        lambda context, api_mode: proxy.ProxyStartup(
            ok=True,
            started=True,
            api_key="generated-proxy-key",
            pid=456,
            detail="started",
        ),
    )

    def fake_run_command(*, label, command, env, cwd, timeout_seconds):
        captured["env"] = env
        return HarnessResult(ok=True, text="ok", command=command)

    monkeypatch.setattr(
        "gpt2giga.harness.harnesses.gemini_cli.run_command",
        fake_run_command,
    )

    result = GeminiCliHarness().run(
        HarnessRequest(prompt="inspect", api_mode=GigaChatApiMode.V1),
        HarnessContext(
            proxy_url="http://127.0.0.1:8090",
            auto_start_proxy=True,
        ),
    )

    assert result.ok is True
    assert captured["env"]["GEMINI_API_KEY"] == "generated-proxy-key"
    assert captured["env"]["GOOGLE_GEMINI_BASE_URL"] == "http://127.0.0.1:8090/v1"
    assert result.events[0].payload["pid"] == 456


def test_gemini_cli_json_output_uses_response_as_text(monkeypatch):
    class Completed:
        returncode = 0
        stdout = (
            '{"session_id":"abc","response":"Привет! Готов к работе.",'
            '"stats":{"tokens":{"total":12}}}'
        )
        stderr = ""

    monkeypatch.setattr(
        "gpt2giga.harness.harnesses.agent_cli.subprocess.run",
        lambda *args, **kwargs: Completed(),
    )

    result = run_command(
        label="Gemini CLI",
        command=("gemini",),
        env={},
        cwd=None,
        timeout_seconds=1,
    )

    assert result.ok is True
    assert result.text == "Привет! Готов к работе."
    assert '"stats"' in result.raw["stdout"]
