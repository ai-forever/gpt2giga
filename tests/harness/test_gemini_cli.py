import json
import sys

from gpt2giga_harness import proxy
from gpt2giga_harness.harnesses.agent_cli import (
    executable_availability,
    run_command,
    run_streaming_command,
)
from gpt2giga_harness.harnesses.gemini_cli import (
    GeminiCliHarness,
    _GeminiStreamParser,
)
from gpt2giga_harness.types import (
    Availability,
    AvailabilityStatus,
    GigaChatApiMode,
    HarnessContext,
    HarnessEvent,
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
    assert env["GEMINI_CLI_CUSTOM_HEADERS"] == (
        "X-GPT2GIGA-Harness-Model:GigaChat-2-Max,X-GPT2GIGA-Pass-Model:false"
    )
    assert env["GEMINI_CLI_TRUST_WORKSPACE"] == "true"


def test_gemini_cli_preserves_custom_headers_and_encodes_pinned_model():
    env = GeminiCliHarness().build_env(
        HarnessRequest(prompt="inspect", model="team/model,preview"),
        HarnessContext(
            proxy_url="http://127.0.0.1:8090",
            extra_env={"GEMINI_CLI_CUSTOM_HEADERS": "X-Existing:value"},
        ),
    )

    assert env["GEMINI_CLI_CUSTOM_HEADERS"] == (
        "X-Existing:value,"
        "X-GPT2GIGA-Harness-Model:team%2Fmodel%2Cpreview,"
        "X-GPT2GIGA-Pass-Model:false"
    )


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


def test_gemini_cli_stream_command_uses_stream_json():
    harness = GeminiCliHarness()
    command = harness.build_command(
        HarnessRequest(prompt="x", stream=True),
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
    )

    assert harness.spec().supports_streaming is True
    assert command[command.index("--output-format") + 1] == "stream-json"


def test_gemini_stream_parser_normalizes_message_tool_and_usage():
    parser = _GeminiStreamParser()
    payloads = (
        {
            "type": "message",
            "role": "assistant",
            "content": "Hello",
            "delta": True,
        },
        {
            "type": "tool_use",
            "tool_name": "read_file",
            "tool_id": "tool-1",
            "parameters": {"path": "README.md"},
        },
        {
            "type": "tool_result",
            "tool_id": "tool-1",
            "status": "success",
            "output": "contents",
        },
        {
            "type": "result",
            "status": "success",
            "stats": {
                "input_tokens": 11,
                "output_tokens": 5,
                "total_tokens": 16,
            },
        },
    )

    events = [event for payload in payloads for event in parser(payload)]

    assert [event.type for event in events] == [
        "message_delta",
        "tool_call_started",
        "tool_call_finished",
        "usage",
    ]
    assert events[0].payload["delta"] == "Hello"
    assert events[1].payload["arguments"] == {"path": "README.md"}
    assert events[2].payload["name"] == "read_file"
    assert events[2].payload["arguments"] == {"path": "README.md"}
    assert events[2].payload["result"] == "contents"
    assert events[-1].payload == {
        "input_tokens": 11,
        "output_tokens": 5,
        "total_tokens": 16,
    }


def test_gemini_stream_parser_tails_nested_subagent_tools(tmp_path):
    parser = _GeminiStreamParser(home=tmp_path)
    parent_id = "invoke_agent__parent"

    parent_events = parser(
        {
            "type": "tool_use",
            "tool_name": "invoke_agent",
            "tool_id": parent_id,
            "parameters": {"agent_name": "codebase_investigator"},
        }
    )

    checkpoint = (
        tmp_path
        / ".gemini"
        / "tmp"
        / "project"
        / "chats"
        / "parent-session"
        / "child-session.jsonl"
    )
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text(
        json.dumps({"$set": {"kind": "subagent"}})
        + "\n"
        + json.dumps(
            {
                "type": "gemini",
                "toolCalls": [
                    {
                        "id": "read_file__child",
                        "name": "read_file",
                        "status": "success",
                        "args": {"file_path": "README.md"},
                        "result": [
                            {
                                "functionResponse": {
                                    "name": "read_file",
                                    "response": {"output": "README contents"},
                                }
                            }
                        ],
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    child_events = parser.poll_events()

    assert parent_events[0].payload["tool_call_id"] == parent_id
    assert [event.type for event in child_events] == [
        "tool_call_started",
        "tool_call_finished",
    ]
    assert child_events[0].payload == {
        "tool_call_id": "read_file__child",
        "name": "read_file",
        "status": "running",
        "parent_tool_call_id": parent_id,
        "source": "gemini-subagent-checkpoint",
        "arguments": {"file_path": "README.md"},
    }
    assert child_events[1].payload["parent_tool_call_id"] == parent_id
    assert child_events[1].payload["result"] == "README contents"
    assert parser.poll_events() == ()


def test_streaming_runner_polls_parser_side_channel():
    class PollingParser:
        terminal_outcome = None
        recognized_payloads = 0

        def __init__(self):
            self.emitted = False

        def __call__(self, payload):
            self.recognized_payloads += 1
            return ()

        def poll_events(self) -> list[HarnessEvent]:
            if self.emitted:
                return []
            self.emitted = True
            return [
                HarnessEvent(
                    type="tool_call_started",
                    message="Nested tool started.",
                    payload={
                        "tool_call_id": "child",
                        "parent_tool_call_id": "parent",
                        "name": "read_file",
                    },
                )
            ]

    script = """
import json
import time
print(json.dumps({"type": "init"}), flush=True)
time.sleep(0.1)
"""

    result = run_streaming_command(
        label="Gemini CLI",
        command=(sys.executable, "-u", "-c", script),
        env={},
        cwd=None,
        timeout_seconds=5,
        request=HarnessRequest(prompt="inspect", stream=True),
        parse_payload=PollingParser(),
    )

    assert result.ok is True
    assert result.raw["tool_calls"] == [
        {
            "tool_call_id": "child",
            "name": "read_file",
        }
    ]


def test_gemini_streaming_runner_emits_nested_checkpoint_tools(tmp_path):
    emitted = []
    script = """
import json
from pathlib import Path
import sys
import time

home = Path(sys.argv[1])
parent_id = "invoke_agent__parent"
print(json.dumps({
    "type": "tool_use",
    "tool_name": "invoke_agent",
    "tool_id": parent_id,
    "parameters": {"agent_name": "investigator"},
}), flush=True)
time.sleep(0.1)
checkpoint = home / ".gemini/tmp/project/chats/parent/child.jsonl"
checkpoint.parent.mkdir(parents=True)
checkpoint.write_text(json.dumps({
    "type": "gemini",
    "toolCalls": [{
        "id": "list_directory__child",
        "name": "list_directory",
        "status": "success",
        "args": {"dir_path": "."},
        "result": [{"functionResponse": {
            "name": "list_directory",
            "response": {"output": "README.md"},
        }}],
    }],
}) + "\\n", encoding="utf-8")
time.sleep(0.15)
print(json.dumps({
    "type": "tool_result",
    "tool_id": parent_id,
    "status": "success",
    "output": "done",
}), flush=True)
print(json.dumps({"type": "result", "status": "success"}), flush=True)
"""

    result = run_streaming_command(
        label="Gemini CLI",
        command=(sys.executable, "-u", "-c", script, str(tmp_path)),
        env={},
        cwd=None,
        timeout_seconds=5,
        request=HarnessRequest(
            prompt="inspect",
            stream=True,
            event_sink=emitted.append,
        ),
        parse_payload=_GeminiStreamParser(home=tmp_path),
    )

    tool_events = [event for event in emitted if event.type.startswith("tool_call_")]
    assert result.ok is True
    assert [event.type for event in tool_events] == [
        "tool_call_started",
        "tool_call_started",
        "tool_call_finished",
        "tool_call_finished",
    ]
    assert tool_events[1].payload["parent_tool_call_id"] == "invoke_agent__parent"
    assert tool_events[2].payload["result"] == "README.md"


def test_gemini_stream_parser_marks_structured_failures_terminal():
    failures = (
        ({"type": "error", "message": "request rejected"}, "request rejected"),
        (
            {"type": "result", "status": "error", "message": "model failed"},
            "model failed",
        ),
        (
            {"type": "result", "status": "failed", "error": {"message": "boom"}},
            "boom",
        ),
    )

    for payload, expected_error in failures:
        parser = _GeminiStreamParser()

        events = parser(payload)

        assert parser.terminal_outcome is not None
        assert parser.terminal_outcome.ok is False
        assert parser.terminal_outcome.error == expected_error
        assert events[0].type == "stderr_delta"


def test_gemini_stream_exit_zero_with_error_event_is_failure():
    script = """
import json
print(json.dumps({"type": "error", "message": "provider unavailable"}))
"""

    result = run_streaming_command(
        label="Gemini CLI",
        command=(sys.executable, "-u", "-c", script),
        env={},
        cwd=None,
        timeout_seconds=5,
        request=HarnessRequest(prompt="inspect", stream=True),
        parse_payload=_GeminiStreamParser(),
    )

    assert result.raw["exit_code"] == 0
    assert result.ok is False
    assert result.error == "provider unavailable"


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
        "gpt2giga_harness.harnesses.agent_cli.subprocess.run",
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
        "gpt2giga_harness.harnesses.agent_cli.subprocess.run",
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
        "gpt2giga_harness.harnesses.gemini_cli.run_command",
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
        "gpt2giga_harness.harnesses.agent_cli.subprocess.run",
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
    assert result.raw["usage"] == {"total_tokens": 12}
    assert result.events[0].type == "usage"
    assert result.events[0].payload == {"total_tokens": 12}


def test_gemini_cli_stream_run_uses_streaming_runner(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        GeminiCliHarness,
        "availability",
        lambda self: Availability.available("gemini available"),
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
        "gpt2giga_harness.harnesses.gemini_cli.run_streaming_command",
        fake_streaming_runner,
    )
    request = HarnessRequest(prompt="inspect", stream=True)

    result = GeminiCliHarness().run(
        request,
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
    )

    assert result.text == "streamed"
    assert captured["request"] is request
    assert "stream-json" in captured["command"]
    assert isinstance(captured["parse_payload"], _GeminiStreamParser)
