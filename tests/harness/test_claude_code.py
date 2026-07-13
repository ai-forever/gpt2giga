import json
import sys

from gpt2giga_harness import proxy
from gpt2giga_harness.harnesses.agent_cli import run_command, run_streaming_command
from gpt2giga_harness.harnesses.claude_code import (
    ClaudeCodeHarness,
    _ClaudeStreamParser,
)
from gpt2giga_harness.types import (
    Availability,
    GigaChatApiMode,
    HarnessContext,
    HarnessRequest,
    HarnessResult,
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
    assert env["ANTHROPIC_CUSTOM_HEADERS"] == (
        "X-GPT2GIGA-Harness-Model:GigaChat\nX-GPT2GIGA-Pass-Model:false"
    )
    assert env["GPT2GIGA_HARNESS_API_MODE"] == "v1"


def test_claude_code_preserves_custom_headers_and_encodes_pinned_model():
    env = ClaudeCodeHarness().build_env(
        HarnessRequest(prompt="inspect", model="team/model,preview"),
        HarnessContext(
            proxy_url="http://127.0.0.1:8090",
            extra_env={"ANTHROPIC_CUSTOM_HEADERS": "X-Team:blue"},
        ),
    )

    assert env["ANTHROPIC_CUSTOM_HEADERS"] == (
        "X-Team:blue\n"
        "X-GPT2GIGA-Harness-Model:team%2Fmodel%2Cpreview\n"
        "X-GPT2GIGA-Pass-Model:false"
    )


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


def test_claude_code_stream_command_uses_partial_stream_json():
    harness = ClaudeCodeHarness()
    command = harness.build_command(
        HarnessRequest(prompt="x", stream=True),
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
    )

    assert harness.spec().supports_streaming is True
    assert command[command.index("--output-format") + 1] == "stream-json"
    assert "--include-partial-messages" in command
    assert "--include-hook-events" not in command


def test_claude_stream_parser_normalizes_partial_text_tools_and_usage():
    parser = _ClaudeStreamParser()
    payloads = (
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": "Hel"},
            },
        },
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "lo"},
            },
        },
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "index": 1,
                "content_block": {
                    "type": "tool_use",
                    "id": "tool-1",
                    "name": "Bash",
                    "input": {},
                },
            },
        },
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "input_json_delta", "partial_json": '{"cmd":"pwd"}'},
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-1",
                        "content": "/tmp",
                        "is_error": False,
                    }
                ]
            },
        },
        {
            "type": "result",
            "result": "Hello",
            "usage": {"input_tokens": 9, "output_tokens": 4},
        },
    )

    events = [event for payload in payloads for event in parser(payload)]

    assert [event.type for event in events] == [
        "message_delta",
        "message_delta",
        "tool_call_started",
        "tool_call_delta",
        "tool_call_finished",
        "usage",
    ]
    assert (
        "".join(
            event.payload["delta"] for event in events if event.type == "message_delta"
        )
        == "Hello"
    )
    assert events[2].payload["name"] == "Bash"
    assert "arguments" not in events[2].payload
    assert events[3].payload["arguments_delta"] == '{"cmd":"pwd"}'
    assert events[4].payload["result"] == "/tmp"
    assert events[-1].payload["total_tokens"] == 13


def test_claude_stream_empty_initial_tool_input_assembles_valid_json():
    payloads = (
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "tool-1",
                    "name": "Bash",
                    "input": {},
                },
            },
        },
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '{"cmd":"pwd"}',
                },
            },
        },
    )
    script = "\n".join(
        f"print({json.dumps(json.dumps(payload))})" for payload in payloads
    )

    result = run_streaming_command(
        label="Claude Code",
        command=(sys.executable, "-u", "-c", script),
        env={},
        cwd=None,
        timeout_seconds=5,
        request=HarnessRequest(prompt="inspect", stream=True),
        parse_payload=_ClaudeStreamParser(),
    )

    arguments = result.raw["tool_calls"][0]["arguments"]
    assert arguments == '{"cmd":"pwd"}'
    assert json.loads(arguments) == {"cmd": "pwd"}


def test_claude_stream_parser_marks_failed_results_terminal():
    failures = (
        (
            {"type": "result", "is_error": True, "result": "execution failed"},
            "execution failed",
        ),
        (
            {"type": "result", "errors": ["first", "second"], "result": ""},
            "first; second",
        ),
        (
            {"type": "result", "error": {"message": "bad response"}},
            "bad response",
        ),
    )

    for payload, expected_error in failures:
        parser = _ClaudeStreamParser()

        events = parser(payload)

        assert parser.terminal_outcome is not None
        assert parser.terminal_outcome.ok is False
        assert parser.terminal_outcome.error == expected_error
        assert events[0].type == "stderr_delta"


def test_claude_stream_exit_zero_with_is_error_result_is_failure():
    script = """
import json
print(json.dumps({"type": "result", "is_error": True, "errors": ["denied"]}))
"""

    result = run_streaming_command(
        label="Claude Code",
        command=(sys.executable, "-u", "-c", script),
        env={},
        cwd=None,
        timeout_seconds=5,
        request=HarnessRequest(prompt="inspect", stream=True),
        parse_payload=_ClaudeStreamParser(),
    )

    assert result.raw["exit_code"] == 0
    assert result.ok is False
    assert result.error == "denied"


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
        "gpt2giga_harness.harnesses.claude_code.run_command",
        fail_run_command,
    )

    result = ClaudeCodeHarness().run(
        HarnessRequest(prompt="inspect"),
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
    )

    assert result.ok is False
    assert result.error == "missing GigaChat credentials"


def test_claude_code_json_output_uses_result_as_text(monkeypatch):
    class Completed:
        returncode = 0
        stdout = (
            '{"type":"result","result":"Привет! Все хорошо.",'
            '"usage":{"input_tokens":7,"output_tokens":3}}'
        )
        stderr = ""

    monkeypatch.setattr(
        "gpt2giga_harness.harnesses.agent_cli.subprocess.run",
        lambda *args, **kwargs: Completed(),
    )

    result = run_command(
        label="Claude Code",
        command=("claude",),
        env={},
        cwd=None,
        timeout_seconds=1,
    )

    assert result.ok is True
    assert result.text == "Привет! Все хорошо."
    assert result.raw["stdout"].startswith('{"type":"result"')
    assert result.raw["usage"] == {
        "input_tokens": 7,
        "output_tokens": 3,
        "total_tokens": 10,
    }
    assert result.events[0].type == "usage"
    assert result.events[0].payload["total_tokens"] == 10


def test_claude_code_stream_run_uses_streaming_runner(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        ClaudeCodeHarness,
        "availability",
        lambda self: Availability.available("claude available"),
    )
    monkeypatch.setattr(
        proxy,
        "ensure_proxy_available",
        lambda context, api_mode: proxy.ProxyStartup(ok=True, api_key="proxy-key"),
    )

    def fake_streaming_runner(**kwargs):
        captured.update(kwargs)
        return HarnessResult(ok=True, text="streamed", command=kwargs["command"])

    monkeypatch.setattr(
        "gpt2giga_harness.harnesses.claude_code.run_streaming_command",
        fake_streaming_runner,
    )
    request = HarnessRequest(prompt="inspect", stream=True)

    result = ClaudeCodeHarness().run(
        request,
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
    )

    assert result.text == "streamed"
    assert captured["request"] is request
    assert "stream-json" in captured["command"]
    assert isinstance(captured["parse_payload"], _ClaudeStreamParser)
