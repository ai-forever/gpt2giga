import sys
from pathlib import Path

from gpt2giga_harness import proxy
from gpt2giga_harness.cli_capabilities import CliCapabilitySnapshot
from gpt2giga_harness.harnesses.agent_cli import run_streaming_command
from gpt2giga_harness.harnesses.codex_cli import (
    CodexCliHarness,
    _CodexStreamParser,
    _upload_gigachat_attachments,
    _write_codex_config,
)
from gpt2giga_harness.native import HarnessInvocationMode
from gpt2giga_harness.types import (
    Availability,
    GigaChatApiMode,
    HarnessChatMessage,
    HarnessContext,
    HarnessRequest,
    HarnessResult,
)


def test_codex_cli_defaults_to_structured_headless_chat():
    assert (
        CodexCliHarness.spec().default_invocation_mode is HarnessInvocationMode.HEADLESS
    )


def test_codex_cli_includes_harness_chat_history_in_ephemeral_turn():
    request = HarnessRequest(
        prompt="What about the tests?",
        messages=(
            HarnessChatMessage(role="user", content="Explain the parser"),
            HarnessChatMessage(role="assistant", content="It parses JSONL events."),
            HarnessChatMessage(role="user", content="What about the tests?"),
        ),
    )

    command = CodexCliHarness().build_command(
        request,
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
    )

    prompt = command[-1]
    assert "CONVERSATION HISTORY" in prompt
    assert "[USER]\nExplain the parser" in prompt
    assert "[ASSISTANT]\nIt parses JSONL events." in prompt
    assert prompt.endswith("CURRENT USER REQUEST\nWhat about the tests?")


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


def test_codex_cli_dry_run_reports_workspace_without_validating(tmp_path):
    missing_workspace = tmp_path / "missing"

    result = CodexCliHarness().run(
        HarnessRequest(
            prompt="inspect",
            workspace=str(missing_workspace),
            extra={"dry_run": True},
        ),
        HarnessContext(proxy_url="http://127.0.0.1:8090", api_key="proxy-key"),
    )

    assert result.ok is True
    assert result.raw["workspace"] == str(missing_workspace)


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


def test_codex_cli_stream_command_uses_json_events():
    harness = CodexCliHarness()
    command = harness.build_command(
        HarnessRequest(prompt="x", stream=True),
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
    )

    assert harness.spec().supports_streaming is True
    assert "--json" in command
    assert "--json" not in harness.build_command(
        HarnessRequest(prompt="x"),
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
    )


def test_codex_cli_applies_fixed_agent_reasoning_config(tmp_path):
    home = tmp_path / ".codex"

    _write_codex_config(
        home,
        HarnessRequest(
            prompt="inspect",
            extra={"agent_adapter_options": {"reasoning_effort": "high"}},
        ),
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
    )

    assert 'model_reasoning_effort = "high"' in (home / "config.toml").read_text()


def test_codex_cli_config_sends_uploaded_file_ids_as_provider_header(tmp_path):
    home = tmp_path / ".codex"

    _write_codex_config(
        home,
        HarnessRequest(prompt="inspect"),
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
        attachment_file_ids=("file-pdf-1",),
    )

    config = (home / "config.toml").read_text()
    assert 'http_headers = { "x-gpt2giga-attachment-ids" = "file-pdf-1" }' in config


def test_codex_cli_uploads_planned_document_before_execution(tmp_path, monkeypatch):
    document = tmp_path / "report.pdf"
    document.write_bytes(b"%PDF-1.7\nfixture")
    uploads = []

    def fake_upload_file(*args, **kwargs):
        uploads.append((args, kwargs))
        return {"id": "file-pdf-1"}

    monkeypatch.setattr(proxy, "upload_file", fake_upload_file)
    request = HarnessRequest(
        prompt="Read it",
        attachments=(
            {
                "id": "att-pdf",
                "filename": "report.pdf",
                "mime_type": "application/pdf",
                "storage_path": str(document),
            },
        ),
        attachment_render_plan={
            "metadata": {
                "deliveries": [
                    {
                        "attachment_id": "att-pdf",
                        "transport": "gigachat_file_upload",
                    }
                ]
            }
        },
    )

    file_ids, events, error = _upload_gigachat_attachments(
        request,
        HarnessContext(
            proxy_url="http://127.0.0.1:8090",
            api_key="proxy-key",
        ),
    )

    assert error is None
    assert file_ids == ("file-pdf-1",)
    assert uploads[0][1]["content"] == b"%PDF-1.7\nfixture"
    assert uploads[0][1]["content_type"] == "application/pdf"
    assert events[0].type == "attachment_uploaded"


def test_codex_stream_parser_normalizes_message_tool_and_usage():
    parser = _CodexStreamParser()
    payloads = (
        {
            "type": "item.started",
            "item": {
                "id": "tool-1",
                "type": "command_execution",
                "command": "pwd",
                "status": "in_progress",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "tool-1",
                "type": "command_execution",
                "command": "pwd",
                "aggregated_output": "/tmp",
                "status": "completed",
            },
        },
        {
            "type": "item.updated",
            "item": {"id": "message-1", "type": "agent_message", "text": "Hel"},
        },
        {
            "type": "item.completed",
            "item": {
                "id": "message-1",
                "type": "agent_message",
                "text": "Hello",
            },
        },
        {
            "type": "turn.completed",
            "usage": {"input_tokens": 8, "output_tokens": 2},
        },
    )

    events = [event for payload in payloads for event in parser(payload)]

    assert [event.type for event in events] == [
        "tool_call_started",
        "tool_call_finished",
        "command_completed",
        "message_delta",
        "message_delta",
        "usage",
    ]
    assert (
        "".join(
            event.payload["delta"] for event in events if event.type == "message_delta"
        )
        == "Hello"
    )
    assert events[0].payload["name"] == "shell"
    assert events[1].payload["result"] == "/tmp"
    assert events[2].payload == {
        "artifact_id": "tool-1",
        "artifact_type": "command",
        "command": "pwd",
        "status": "completed",
    }
    assert events[-1].payload == {
        "input_tokens": 8,
        "output_tokens": 2,
        "total_tokens": 10,
    }


def test_codex_stream_parser_marks_structured_failures_terminal():
    failures = (
        ({"type": "error", "message": "request rejected"}, "request rejected"),
        (
            {"type": "turn.failed", "error": {"message": "turn exploded"}},
            "turn exploded",
        ),
        (
            {
                "type": "item.failed",
                "item": {"id": "item-1", "type": "agent_message"},
            },
            "Codex CLI item failed",
        ),
    )

    for payload, expected_error in failures:
        parser = _CodexStreamParser()

        events = parser(payload)

        assert parser.terminal_outcome is not None
        assert parser.terminal_outcome.ok is False
        assert parser.terminal_outcome.error == expected_error
        assert events[-1].type == "stderr_delta"


def test_codex_stream_parser_explains_failed_tool_without_output():
    parser = _CodexStreamParser()

    events = parser(
        {
            "type": "item.failed",
            "item": {
                "id": "command-1",
                "type": "command_execution",
                "command": "rg missing",
                "status": "failed",
                "exit_code": 1,
                "aggregated_output": "",
            },
        }
    )

    tool_event = next(event for event in events if event.type == "tool_call_finished")
    assert tool_event.payload["status"] == "failed"
    assert tool_event.payload["result"] == (
        "Command exited with code 1 and produced no output."
    )
    command_event = next(event for event in events if event.type == "command_completed")
    assert command_event.payload["exit_code"] == 1
    assert command_event.payload["status"] == "failed"


def test_codex_stream_parser_preserves_update_plan_payload():
    parser = _CodexStreamParser()
    plan = [
        {
            "status": "in_progress",
            "step": "Render update_plan as a structured plan card.",
        }
    ]

    events = parser(
        {
            "type": "item.completed",
            "item": {
                "id": "plan-1",
                "type": "dynamic_tool_call",
                "name": "update_plan",
                "arguments": {"explanation": "Rendering the plan.", "plan": plan},
                "output": "Plan updated",
                "status": "completed",
            },
        }
    )

    assert len(events) == 1
    assert events[0].type == "tool_call_finished"
    assert events[0].payload["name"] == "update_plan"
    assert events[0].payload["arguments"] == {
        "explanation": "Rendering the plan.",
        "plan": plan,
    }


def test_codex_stream_parser_preserves_collab_agent_identity_and_prompt():
    events = _CodexStreamParser()(
        {
            "type": "item.completed",
            "item": {
                "id": "spawn-1",
                "type": "collab_tool_call",
                "tool": "spawn_agent",
                "sender_thread_id": "thread-parent",
                "receiver_thread_ids": ["019f6cc0-2125-70e1-93bf-7c5bec2694a2"],
                "prompt": "Inspect the repository configuration",
                "agents_states": {
                    "019f6cc0-2125-70e1-93bf-7c5bec2694a2": {
                        "status": "completed",
                        "message": "Found three files",
                    }
                },
                "status": "completed",
            },
        }
    )

    assert len(events) == 1
    assert events[0].type == "tool_call_finished"
    assert events[0].payload["name"] == "spawn_agent"
    assert events[0].payload["arguments"] == {
        "prompt": "Inspect the repository configuration",
        "subagents": [
            {
                "id": "019f6cc0-2125-70e1-93bf-7c5bec2694a2",
                "name": "019f6cc0",
                "status": "completed",
                "message": "Found three files",
            }
        ],
    }


def test_codex_stream_parser_emits_explicit_test_artifact():
    events = _CodexStreamParser()(
        {
            "type": "item.completed",
            "item": {
                "id": "test-1",
                "type": "test_result",
                "name": "pytest",
                "status": "passed",
            },
        }
    )

    artifact = next(event for event in events if event.type == "test_completed")
    assert artifact.payload == {
        "artifact_id": "test-1",
        "artifact_type": "test",
        "name": "pytest",
        "status": "passed",
    }


def test_codex_stream_parser_maps_todo_list_to_update_plan():
    parser = _CodexStreamParser()
    payloads = (
        {
            "type": "item.started",
            "item": {
                "id": "todo-1",
                "type": "todo_list",
                "items": [
                    {"text": "Inspect the repository", "completed": True},
                    {"text": "Fix plan rendering", "completed": False},
                    {"text": "Verify the UI", "completed": False},
                ],
            },
        },
        {
            "type": "item.updated",
            "item": {
                "id": "todo-1",
                "type": "todo_list",
                "items": [
                    {"text": "Inspect the repository", "completed": True},
                    {"text": "Fix plan rendering", "completed": True},
                    {"text": "Verify the UI", "completed": False},
                ],
            },
        },
    )

    events = [event for payload in payloads for event in parser(payload)]

    assert [event.type for event in events] == [
        "tool_call_started",
        "tool_call_delta",
    ]
    assert all(event.payload["name"] == "update_plan" for event in events)
    assert events[0].payload["arguments"] == {
        "plan": [
            {"step": "Inspect the repository", "status": "completed"},
            {"step": "Fix plan rendering", "status": "in_progress"},
            {"step": "Verify the UI", "status": "pending"},
        ]
    }
    assert events[1].payload["arguments"] == {
        "plan": [
            {"step": "Inspect the repository", "status": "completed"},
            {"step": "Fix plan rendering", "status": "completed"},
            {"step": "Verify the UI", "status": "in_progress"},
        ]
    }


def test_codex_stream_exit_zero_with_failed_turn_is_failure():
    script = """
import json
print(json.dumps({"type": "turn.failed", "error": {"message": "bad turn"}}))
"""

    result = run_streaming_command(
        label="Codex CLI",
        command=(sys.executable, "-u", "-c", script),
        env={},
        cwd=None,
        timeout_seconds=5,
        request=HarnessRequest(prompt="inspect", stream=True),
        parse_payload=_CodexStreamParser(),
    )

    assert result.raw["exit_code"] == 0
    assert result.ok is False
    assert result.error == "bad turn"


def test_codex_cli_reports_missing_workspace(tmp_path):
    missing_workspace = tmp_path / "missing"

    result = CodexCliHarness().run(
        HarnessRequest(prompt="x", workspace=str(missing_workspace)),
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
    )

    assert result.ok is False
    assert result.error == f"Workspace does not exist: {missing_workspace}"


def test_codex_cli_autostart_uses_generated_proxy_key(monkeypatch):
    captured = {}

    def fake_ensure_proxy_available(context, api_mode):
        captured["api_mode"] = api_mode
        return proxy.ProxyStartup(
            ok=True,
            started=True,
            api_key="generated-proxy-key",
            pid=123,
            detail="started",
        )

    def fake_run_command(*, label, command, env, cwd, timeout_seconds):
        captured["env"] = env
        return HarnessResult(ok=True, text="ok", command=command)

    monkeypatch.setattr(
        proxy,
        "ensure_proxy_available",
        fake_ensure_proxy_available,
    )
    monkeypatch.setattr(
        CodexCliHarness,
        "availability",
        lambda self: Availability.available("codex available"),
    )
    monkeypatch.setattr(
        "gpt2giga_harness.harnesses.codex_cli.run_command",
        fake_run_command,
    )

    result = CodexCliHarness().run(
        HarnessRequest(prompt="inspect", api_mode=GigaChatApiMode.V2),
        HarnessContext(
            proxy_url="http://127.0.0.1:8090",
            auto_start_proxy=True,
        ),
    )

    assert result.ok is True
    assert captured["api_mode"] == GigaChatApiMode.V2
    assert captured["env"]["GPT2GIGA_API_KEY"] == "generated-proxy-key"
    assert result.events[0].type == "proxy_sidecar"
    assert result.events[0].payload["pid"] == 123


def test_codex_pdf_turn_uses_ephemeral_exec_instead_of_sticky_app_server(
    tmp_path,
    monkeypatch,
):
    document = tmp_path / "report.pdf"
    document.write_bytes(b"%PDF-1.7\nfixture")
    captured = {}
    snapshot = CliCapabilitySnapshot(
        harness_id="codex-cli",
        status="supported",
        version="fixture 1.0",
        parsed_version="1.0",
        command=("/tmp/codex-fixture",),
        capabilities={"app-server": True},
        event_schema="fixture",
        history_schema="fixture",
    )
    monkeypatch.setattr(
        CodexCliHarness,
        "availability",
        lambda self: Availability.available("codex available"),
    )
    monkeypatch.setattr(
        CodexCliHarness,
        "capability_probe",
        lambda self: snapshot,
    )
    monkeypatch.setattr(
        proxy,
        "ensure_proxy_available",
        lambda context, api_mode: proxy.ProxyStartup(ok=True, api_key="proxy-key"),
    )
    monkeypatch.setattr(
        proxy,
        "upload_file",
        lambda *args, **kwargs: {"id": "file-pdf-1"},
    )

    def fake_run_command(*, label, command, env, cwd, timeout_seconds):
        captured["command"] = command
        captured["config"] = (Path(env["CODEX_HOME"]) / "config.toml").read_text()
        return HarnessResult(ok=True, text="ok", command=command)

    monkeypatch.setattr(
        "gpt2giga_harness.harnesses.codex_cli.run_command",
        fake_run_command,
    )
    request = HarnessRequest(
        prompt="$pdf\n\nWhat is in this file?",
        attachments=(
            {
                "id": "att-pdf",
                "filename": "report.pdf",
                "mime_type": "application/pdf",
                "storage_path": str(document),
            },
        ),
        attachment_render_plan={
            "metadata": {
                "deliveries": [
                    {
                        "attachment_id": "att-pdf",
                        "transport": "gigachat_file_upload",
                        "surfaces": ["headless_one_shot"],
                    }
                ]
            }
        },
        extra={"continuation": {"strategy": "structured_thread"}},
    )

    result = CodexCliHarness().run(
        request,
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
    )

    assert result.ok is True
    assert "exec" in captured["command"]
    assert "app-server" not in captured["command"]
    assert 'x-gpt2giga-attachment-ids" = "file-pdf-1' in captured["config"]
    assert any(event.type == "attachment_transport" for event in result.events)


def test_codex_image_turn_uses_ephemeral_exec_with_image_flag(monkeypatch):
    captured = {}
    snapshot = CliCapabilitySnapshot(
        harness_id="codex-cli",
        status="supported",
        version="fixture 1.0",
        parsed_version="1.0",
        command=("/tmp/codex-fixture",),
        capabilities={"app-server": True, "--image": True},
        event_schema="fixture",
        history_schema="fixture",
    )
    monkeypatch.setattr(
        CodexCliHarness,
        "availability",
        lambda self: Availability.available("codex available"),
    )
    monkeypatch.setattr(
        CodexCliHarness,
        "capability_probe",
        lambda self: snapshot,
    )
    monkeypatch.setattr(
        proxy,
        "ensure_proxy_available",
        lambda context, api_mode: proxy.ProxyStartup(ok=True, api_key="proxy-key"),
    )

    def fake_run_command(*, label, command, env, cwd, timeout_seconds):
        captured["command"] = command
        return HarnessResult(ok=True, text="ok", command=command)

    monkeypatch.setattr(
        "gpt2giga_harness.harnesses.codex_cli.run_command",
        fake_run_command,
    )
    request = HarnessRequest(
        prompt="What is in the image?",
        attachment_render_plan={
            "cli_args": ["--image", "/tmp/screenshot.png"],
            "metadata": {
                "deliveries": [
                    {
                        "attachment_id": "att-image",
                        "transport": "cli_image_flag",
                        "required_cli_capabilities": ["--image"],
                        "surfaces": ["headless_one_shot", "native"],
                    }
                ]
            },
        },
        extra={"continuation": {"strategy": "structured_thread"}},
    )

    result = CodexCliHarness().run(
        request,
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
    )

    assert result.ok is True
    assert "exec" in captured["command"]
    assert "app-server" not in captured["command"]
    image_index = captured["command"].index("--image")
    assert captured["command"][image_index + 1] == "/tmp/screenshot.png"
    transport_event = next(
        event for event in result.events if event.type == "attachment_transport"
    )
    assert transport_event.payload["transports"] == ["cli_image_flag"]


def test_codex_cli_stream_run_uses_streaming_runner(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        CodexCliHarness,
        "availability",
        lambda self: Availability.available("codex available"),
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
        "gpt2giga_harness.harnesses.codex_cli.run_streaming_command",
        fake_streaming_runner,
    )
    request = HarnessRequest(prompt="inspect", stream=True)

    result = CodexCliHarness().run(
        request,
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
    )

    assert result.text == "streamed"
    assert captured["request"] is request
    assert "--json" in captured["command"]
    assert isinstance(captured["parse_payload"], _CodexStreamParser)
