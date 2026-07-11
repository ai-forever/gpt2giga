import os
import sys
import threading
import time

import pytest

from gpt2giga_harness.harnesses.agent_cli import (
    STREAM_QUEUE_MAX_ITEMS,
    message_delta_event,
    run_streaming_command,
    tool_call_event,
    usage_event,
)
from gpt2giga_harness.types import HarnessEvent, HarnessRequest


def test_streaming_command_emits_jsonl_events_and_normalizes_raw_output():
    script = """
import json
import sys

events = [
    {"type": "message", "delta": "Hello "},
    {"type": "tool_start", "id": "tool-1", "name": "shell", "arguments": ""},
    {"type": "tool_delta", "id": "tool-1", "arguments_delta": "{\\\"cmd\\\":"},
    {"type": "tool_delta", "id": "tool-1", "arguments_delta": "\\\"pwd\\\"}"},
    {"type": "tool_finish", "id": "tool-1", "result": "/tmp", "status": "success"},
    {"type": "message", "delta": "world"},
    {"type": "usage", "input_tokens": 7, "output_tokens": 3, "total_tokens": 10},
]
for event in events:
    print(json.dumps(event), flush=True)
print("proxy-key", file=sys.stderr, flush=True)
"""
    received: list[HarnessEvent] = []
    request = HarnessRequest(
        prompt="hello",
        stream=True,
        event_sink=received.append,
    )

    result = run_streaming_command(
        label="Fixture CLI",
        command=(sys.executable, "-u", "-c", script),
        env={"GEMINI_API_KEY": "proxy-key"},
        cwd=None,
        timeout_seconds=5,
        request=request,
        parse_payload=_fixture_parser,
    )

    assert result.ok is True
    assert result.text == "Hello world"
    assert result.raw["usage"] == {
        "input_tokens": 7,
        "output_tokens": 3,
        "total_tokens": 10,
    }
    assert result.raw["tool_calls"] == [
        {
            "tool_call_id": "tool-1",
            "name": "shell",
            "arguments": '{"cmd":"pwd"}',
            "result": "/tmp",
            "status": "success",
        }
    ]
    assert "proxy-key" not in result.raw["stderr"]
    assert "<redacted>" in result.raw["stderr"]
    assert [event.type for event in received if event.type != "stderr_delta"] == [
        "message_delta",
        "tool_call_started",
        "tool_call_delta",
        "tool_call_delta",
        "tool_call_finished",
        "message_delta",
        "usage",
    ]
    assert any(event.type == "stderr_delta" for event in received)
    assert result.events == ()


def test_streaming_command_returns_events_without_live_sink():
    result = run_streaming_command(
        label="Fixture CLI",
        command=(
            sys.executable,
            "-u",
            "-c",
            'print(\'{"type":"message","delta":"kept"}\')',
        ),
        env={},
        cwd=None,
        timeout_seconds=5,
        request=HarnessRequest(prompt="hello", stream=True),
        parse_payload=_fixture_parser,
    )

    assert result.ok is True
    assert result.text == "kept"
    assert [event.type for event in result.events] == ["message_delta"]
    assert result.events[0].payload == {"delta": "kept"}


def test_streaming_command_uses_bounded_queue_and_coalesces_message_deltas():
    script = """
import json
for _ in range(80):
    print(json.dumps({"type": "message", "delta": "x"}), flush=True)
"""
    received: list[HarnessEvent] = []

    result = run_streaming_command(
        label="Fixture CLI",
        command=(sys.executable, "-u", "-c", script),
        env={},
        cwd=None,
        timeout_seconds=5,
        request=HarnessRequest(
            prompt="hello",
            stream=True,
            event_sink=received.append,
        ),
        parse_payload=_fixture_parser,
    )

    message_events = [event for event in received if event.type == "message_delta"]
    assert STREAM_QUEUE_MAX_ITEMS == 256
    assert result.text == "x" * 80
    assert 0 < len(message_events) < 80
    assert "".join(event.payload["delta"] for event in message_events) == "x" * 80


def test_streaming_command_treats_non_json_stdout_as_delta():
    received: list[HarnessEvent] = []
    request = HarnessRequest(prompt="hello", stream=True, event_sink=received.append)

    result = run_streaming_command(
        label="Fixture CLI",
        command=(sys.executable, "-u", "-c", 'print("plain output")'),
        env={},
        cwd=None,
        timeout_seconds=5,
        request=request,
        parse_payload=lambda payload: (),
    )

    assert result.ok is True
    assert result.text == "plain output"
    assert received[0].type == "stdout_delta"
    assert received[0].payload["delta"] == "plain output\n"


def test_streaming_command_honors_cancellation():
    cancel_event = threading.Event()
    timer = threading.Timer(0.1, cancel_event.set)
    timer.start()
    try:
        result = run_streaming_command(
            label="Fixture CLI",
            command=(
                sys.executable,
                "-u",
                "-c",
                'import time; print("started", flush=True); time.sleep(10)',
            ),
            env={},
            cwd=None,
            timeout_seconds=5,
            request=HarnessRequest(
                prompt="hello",
                stream=True,
                cancel_event=cancel_event,
            ),
            parse_payload=lambda payload: (),
        )
    finally:
        timer.cancel()

    assert result.ok is False
    assert result.error == "Fixture CLI canceled"
    assert result.raw["exit_code"] != 0


def test_streaming_command_enforces_timeout():
    result = run_streaming_command(
        label="Fixture CLI",
        command=(sys.executable, "-u", "-c", "import time; time.sleep(10)"),
        env={},
        cwd=None,
        timeout_seconds=0.1,
        request=HarnessRequest(prompt="hello", stream=True),
        parse_payload=lambda payload: (),
    )

    assert result.ok is False
    assert result.error == "Fixture CLI timed out after 0.1 seconds"
    assert result.raw["timeout_seconds"] == 0.1


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group regression")
def test_streaming_timeout_stops_descendant_process_group(tmp_path):
    marker = tmp_path / "descendant-terminated"
    child_script = """
import pathlib
import signal
import sys
import time

marker = pathlib.Path(sys.argv[1])

def terminate(signum, frame):
    marker.write_text("terminated", encoding="utf-8")
    raise SystemExit(0)

signal.signal(signal.SIGTERM, terminate)
print("child ready", flush=True)
time.sleep(30)
"""
    parent_script = f"""
import subprocess
import sys
import time

subprocess.Popen(
    [sys.executable, "-u", "-c", {child_script!r}, {str(marker)!r}],
)
time.sleep(0.3)
print("parent ready", flush=True)
time.sleep(30)
"""

    result = run_streaming_command(
        label="Fixture CLI",
        command=(sys.executable, "-u", "-c", parent_script),
        env={},
        cwd=None,
        timeout_seconds=0.5,
        request=HarnessRequest(prompt="hello", stream=True),
        parse_payload=lambda payload: (),
    )

    assert result.ok is False
    assert result.error == "Fixture CLI timed out after 0.5 seconds"
    assert marker.read_text(encoding="utf-8") == "terminated"


@pytest.mark.skipif(os.name != "posix", reason="POSIX inherited-pipe regression")
def test_streaming_command_bounds_inherited_pipe_drain_after_parent_exit():
    script = """
import json
import subprocess
import sys

subprocess.Popen([sys.executable, "-c", "import time; time.sleep(8)"])
print(json.dumps({"type": "message", "delta": "done"}), flush=True)
"""
    started_at = time.monotonic()

    result = run_streaming_command(
        label="Fixture CLI",
        command=(sys.executable, "-u", "-c", script),
        env={},
        cwd=None,
        timeout_seconds=10,
        request=HarnessRequest(prompt="hello", stream=True),
        parse_payload=_fixture_parser,
    )

    assert result.ok is True
    assert result.text == "done"
    assert time.monotonic() - started_at < 6


def _fixture_parser(payload):
    event_type = payload.get("type")
    if event_type == "message":
        event = message_delta_event(payload.get("delta"))
        return (event,) if event is not None else ()
    if event_type == "tool_start":
        return (
            tool_call_event(
                "tool_call_started",
                tool_call_id=payload.get("id"),
                name=payload.get("name"),
                arguments=payload.get("arguments"),
                status="running",
            ),
        )
    if event_type == "tool_finish":
        return (
            tool_call_event(
                "tool_call_finished",
                tool_call_id=payload.get("id"),
                result=payload.get("result"),
                status=payload.get("status"),
            ),
        )
    if event_type == "tool_delta":
        return (
            tool_call_event(
                "tool_call_delta",
                tool_call_id=payload.get("id"),
                arguments=payload.get("arguments_delta"),
                status="running",
            ),
        )
    if event_type == "usage":
        event = usage_event(payload)
        return (event,) if event is not None else ()
    return ()
