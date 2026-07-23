from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys

import pytest

from gpt2giga_harness.cli_capabilities import CliCapabilitySnapshot
from gpt2giga_harness.harnesses.gemini_workbench import (
    GeminiAcpEventDecoder,
    GeminiOneShotEventDecoder,
    admit_gemini_workbench,
    gemini_contextual_capabilities,
)
from gpt2giga_harness.native_cli_contracts import (
    CapabilityLevel,
    CapabilityState,
    NativeCommandClass,
    classify_native_route,
)
from gpt2giga_harness.terminal_intent import parse_native_tui_launch_intent


def _snapshot(
    *,
    version: str = "0.46.0",
    supported: bool = True,
    stream_json: bool = True,
    acp: bool = True,
) -> CliCapabilitySnapshot:
    return CliCapabilitySnapshot(
        harness_id="gemini-cli",
        status="supported" if supported else "degraded",
        version=version,
        parsed_version=version,
        command=("/fixture/gemini",),
        capabilities={
            "stream-json": stream_json,
            "--acp": acp,
            "--experimental-acp": acp,
        },
        event_schema="gemini-stream-json-v1",
        history_schema="gemini-checkpoint-jsonl-v1",
    )


def test_gemini_pack_admits_only_reviewed_stream_and_acp_window():
    admitted = admit_gemini_workbench(_snapshot())
    drifted = admit_gemini_workbench(_snapshot(version="0.47.0", supported=False))
    incomplete = admit_gemini_workbench(_snapshot(acp=False))

    assert admitted.native_handoff is True
    assert admitted.structured_one_shot is True
    assert admitted.structured_acp is True
    assert admitted.reason == "acp_admitted"
    assert drifted.structured_one_shot is False
    assert drifted.structured_acp is False
    assert drifted.reason == "acp_above_window"
    assert incomplete.structured_acp is False
    assert incomplete.reason == "acp_capability_unproven"


def test_gemini_capabilities_keep_acp_and_native_controls_distinct():
    acp = gemini_contextual_capabilities(
        _snapshot(),
        transport="acp",
        process_owner="harness",
        session_generation=1,
        policy_allows=True,
    )
    terminal = gemini_contextual_capabilities(
        _snapshot(),
        transport="provider-terminal",
        process_owner="provider",
        session_generation=1,
        policy_allows=True,
    )
    one_shot = gemini_contextual_capabilities(
        _snapshot(),
        transport="one-shot",
        process_owner="harness",
        session_generation=1,
        policy_allows=True,
    )
    acp_by_id = {item.capability_id: item for item in acp}
    terminal_by_id = {item.capability_id: item for item in terminal}
    one_shot_by_id = {item.capability_id: item for item in one_shot}

    assert acp_by_id["session.resume.native"].state is CapabilityState.EXPERIMENTAL
    assert acp_by_id["approval.decide"].state is CapabilityState.EXPERIMENTAL
    assert acp_by_id["structured.events.decode"].state is CapabilityState.READY
    assert acp_by_id["one_shot.events.decode"].state is CapabilityState.BLOCKED
    assert acp_by_id["control.approval.set"].state is CapabilityState.BLOCKED
    assert acp_by_id["control.policy.set"].state is CapabilityState.BLOCKED
    assert acp_by_id["control.sandbox.set"].state is CapabilityState.BLOCKED
    assert terminal_by_id["control.approval.set"].state is CapabilityState.DEGRADED
    assert terminal_by_id["control.policy.set"].state is CapabilityState.DEGRADED
    assert terminal_by_id["control.sandbox.set"].state is CapabilityState.DEGRADED
    assert terminal_by_id["approval.decide"].state is CapabilityState.BLOCKED
    assert one_shot_by_id["one_shot.events.decode"].state is CapabilityState.READY


def test_gemini_acp_decoder_normalizes_events_without_provider_envelope():
    decoder = GeminiAcpEventDecoder(session_id="sess_1", workspace_id="workspace_1")
    message = decoder.decode(
        {
            "type": "output_delta",
            "payload": {
                "session_id": "provider-session-must-not-be-adopted",
                "content": {"type": "text", "text": "hello"},
                "providerSecret": "must-not-pass",
            },
            "generation": 3,
            "synthetic": False,
        }
    )
    tool = decoder.decode(
        {
            "type": "tool_completed",
            "payload": {
                "tool_call_id": "tool_1",
                "title": "read_file",
                "status": "completed",
                "content": [{"type": "content", "content": "must-not-pass"}],
            },
            "generation": 3,
        }
    )

    assert message.payload_type == "message.delta"
    assert dict(message.payload) == {"role": "assistant", "delta": "hello"}
    assert message.session_id == "sess_1"
    assert tool.payload_type == "tool.updated"
    assert dict(tool.payload) == {
        "id": "tool_1",
        "kind": "read_file",
        "status": "completed",
    }
    assert "provider-session-must-not-be-adopted" not in repr(message)
    assert "providerSecret" not in repr(message)
    assert "must-not-pass" not in repr(tool)


def test_gemini_one_shot_decoder_uses_common_events_without_native_wrapping():
    decoder = GeminiOneShotEventDecoder(session_id="sess_1", workspace_id="workspace_1")
    message = decoder.decode(
        {
            "type": "message",
            "role": "assistant",
            "content": "hello",
            "session_id": "provider-session-must-not-be-adopted",
        }
    )
    usage = decoder.decode(
        {
            "type": "result",
            "status": "success",
            "stats": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
        }
    )

    assert [(draft.payload_type, dict(draft.payload)) for draft in message] == [
        ("message.delta", {"role": "assistant", "delta": "hello"})
    ]
    assert [(draft.payload_type, dict(draft.payload)) for draft in usage] == [
        (
            "usage.updated",
            {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
        )
    ]
    assert all(draft.session_id == "sess_1" for draft in (*message, *usage))
    assert "provider-session-must-not-be-adopted" not in repr(message)


@pytest.mark.parametrize(
    ("suffix", "pattern", "selector"),
    (
        ((), "gemini.root", None),
        (("inspect",), "gemini.prompt", None),
        (("-i", "inspect"), "gemini.interactive", None),
        (("--prompt-interactive", "inspect"), "gemini.interactive", None),
        (("-r", "latest"), "gemini.resume", "latest"),
        (("--resume", "2"), "gemini.resume", "2"),
        (
            ("-r", "11111111-1111-4111-8111-111111111111"),
            "gemini.resume",
            "11111111-1111-4111-8111-111111111111",
        ),
    ),
)
def test_gemini_human_intents_are_affirmative_and_preserve_native_identity(
    suffix, pattern, selector
):
    decision = classify_native_route("gemini", suffix, version="0.46.0")
    intent = parse_native_tui_launch_intent("gemini", suffix, decision)

    assert decision.level is CapabilityLevel.STRUCTURED_WORKBENCH
    assert decision.intent_pattern_id == pattern
    assert intent is not None
    assert intent.persistence == "provider_native"
    assert intent.native_session_selector == selector
    assert intent.session_operation == ("resume" if selector else None)
    assert intent.provider_transport == "acp"


@pytest.mark.parametrize(
    ("suffix", "stdin_tty", "stdout_tty", "command_class"),
    (
        (("inspect",), False, True, NativeCommandClass.HEADLESS),
        (("inspect",), True, False, NativeCommandClass.HEADLESS),
        (("-p", "headless"), True, True, NativeCommandClass.HEADLESS),
        (
            ("-i", "interactive", "-p", "headless"),
            True,
            True,
            NativeCommandClass.HEADLESS,
        ),
        (("--list-sessions",), True, True, NativeCommandClass.ADMINISTRATION),
        (
            ("--delete-session", "fixture-id"),
            True,
            True,
            NativeCommandClass.ADMINISTRATION,
        ),
        (("mcp", "list"), True, True, NativeCommandClass.ADMINISTRATION),
        (("extensions", "list"), True, True, NativeCommandClass.ADMINISTRATION),
        (("skills", "list"), True, True, NativeCommandClass.ADMINISTRATION),
        (("update",), True, True, NativeCommandClass.ADMINISTRATION),
    ),
)
def test_gemini_native_precedence_and_admin_paths_stay_provider_owned(
    suffix, stdin_tty, stdout_tty, command_class
):
    decision = classify_native_route(
        "gemini",
        suffix,
        version="0.46.0",
        stdin_is_tty=stdin_tty,
        stdout_is_tty=stdout_tty,
    )

    assert decision.level is CapabilityLevel.NATIVE_PASSTHROUGH
    assert decision.intent_pattern_id is None
    assert decision.command_class is command_class


@pytest.mark.skipif(os.name == "nt", reason="POSIX facade parity contract")
@pytest.mark.parametrize(
    ("suffix", "exit_code"),
    (
        (("-p", "inspect", "--output-format", "text"), 0),
        (("-p", "inspect", "--output-format", "json"), 0),
        (("-p", "inspect", "--output-format", "stream-json"), 0),
        (("--approval-mode", "plan", "-p", "approval"), 0),
        (("--policy", "fixture-policy", "-p", "policy"), 42),
        (("--sandbox", "fixture-sandbox", "-p", "sandbox"), 0),
        (("--worktree", "fixture-tree", "-p", "worktree"), 0),
        (("--list-sessions",), 0),
        (("--delete-session", "fixture-session"), 0),
        (("mcp", "list"), 0),
        (("extensions", "list"), 0),
        (("skills", "list"), 0),
        (("update",), 0),
        (("--help",), 0),
        (("--version",), 0),
        (("-p", "failure", "--fixture-exit=1"), 1),
        (("-p", "failure", "--fixture-exit=53"), 53),
    ),
)
def test_direct_and_prefixed_gemini_l0_match_in_isolated_home(
    tmp_path, suffix, exit_code
):
    executable = _make_gemini_fixture(tmp_path / "gemini")
    isolated_home = tmp_path / "home"
    isolated_home.mkdir()
    environment = {
        **os.environ,
        "PATH": os.fspath(tmp_path),
        "HOME": os.fspath(isolated_home),
        "GEMINI_CLI_HOME": os.fspath(isolated_home / ".gemini"),
    }
    stdin = b"fixture stdin"
    direct = subprocess.run(
        (os.fspath(executable), *suffix),
        env=environment,
        input=stdin,
        capture_output=True,
        check=False,
    )
    prefixed = subprocess.run(
        (
            sys.executable,
            "-c",
            "from gpt2giga_harness.entrypoint import main; raise SystemExit(main())",
            "gemini",
            *suffix,
        ),
        env=environment,
        input=stdin,
        capture_output=True,
        check=False,
    )

    assert direct.returncode == exit_code
    assert prefixed.returncode == direct.returncode
    assert prefixed.stdout == direct.stdout
    assert prefixed.stderr == direct.stderr
    if "--output-format" in suffix and suffix[-1] == "stream-json":
        assert len(prefixed.stdout.splitlines()) == 2
        assert all(json.loads(line) for line in prefixed.stdout.splitlines())
    elif "--output-format" in suffix and suffix[-1] == "json":
        assert isinstance(json.loads(prefixed.stdout), dict)


@pytest.mark.skipif(os.name == "nt", reason="POSIX facade signal contract")
def test_prefixed_gemini_headless_interruption_reaches_provider(tmp_path):
    _make_gemini_fixture(tmp_path / "gemini")
    process = subprocess.Popen(
        (
            sys.executable,
            "-c",
            "from gpt2giga_harness.entrypoint import main; raise SystemExit(main())",
            "gemini",
            "-p",
            "--fixture-wait",
        ),
        env={**os.environ, "PATH": os.fspath(tmp_path)},
        stdout=subprocess.PIPE,
    )
    assert process.stdout is not None
    assert process.stdout.read(5) == b"ready"
    process.send_signal(signal.SIGINT)
    assert process.wait(timeout=5) == 42


def _make_gemini_fixture(path: Path) -> Path:
    path.write_text(
        f"#!{sys.executable}\n"
        "import json, os, signal, sys, time\n"
        "if '--fixture-wait' in sys.argv:\n"
        "    signal.signal(signal.SIGINT, lambda *_: os._exit(42))\n"
        "    os.write(1, b'ready')\n"
        "    time.sleep(10)\n"
        "args = sys.argv[1:]\n"
        "payload = {'argv': args, 'stdin': os.read(0, 1000).decode(), "
        "'home': os.environ.get('HOME')}\n"
        "output_format = args[args.index('--output-format') + 1] "
        "if '--output-format' in args else 'text'\n"
        "if output_format == 'stream-json':\n"
        '    os.write(1, b\'{"type":"init"}\\n{"type":"result"}\\n\')\n'
        "else:\n"
        "    os.write(1, json.dumps(payload, sort_keys=True).encode())\n"
        "os.write(2, b'fixture-stderr')\n"
        "exit_code = 42 if '--policy' in args else 0\n"
        "for token in args:\n"
        "    if token.startswith('--fixture-exit='):\n"
        "        exit_code = int(token.split('=', 1)[1])\n"
        "raise SystemExit(exit_code)\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path
