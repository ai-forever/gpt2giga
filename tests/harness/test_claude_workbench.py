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
from gpt2giga_harness.harnesses.claude_workbench import (
    ClaudeOneShotEventDecoder,
    admit_claude_workbench,
    claude_contextual_capabilities,
)
from gpt2giga_harness.native_cli_contracts import CapabilityState
from gpt2giga_harness.native_cli_contracts import CapabilityLevel
from gpt2giga_harness.native_cli_contracts import NativeCommandClass
from gpt2giga_harness.native_cli_contracts import classify_native_route
from gpt2giga_harness.terminal_intent import parse_native_tui_launch_intent


def _snapshot(
    *, version: str = "2.1.212", supported: bool = True, stream_json: bool = True
) -> CliCapabilitySnapshot:
    return CliCapabilitySnapshot(
        harness_id="claude-code",
        status="supported" if supported else "degraded",
        version=f"{version} (Claude Code)",
        parsed_version=version,
        command=("/fixture/claude",),
        capabilities={"stream-json": stream_json},
        event_schema="claude-stream-json-v1",
        history_schema="claude-project-jsonl-v1",
    )


def test_claude_pack_admits_only_one_shot_and_preserves_negative_sdk_decision():
    admitted = admit_claude_workbench(_snapshot())
    drifted = admit_claude_workbench(_snapshot(version="2.2.0", supported=False))

    assert admitted.native_handoff is True
    assert admitted.structured_one_shot is True
    assert admitted.durable_embedded is False
    assert admitted.reason == "one_shot_admitted"
    assert drifted.native_handoff is True
    assert drifted.structured_one_shot is False
    assert drifted.durable_embedded is False
    assert drifted.reason == "one_shot_above_window"


def test_claude_capabilities_keep_provider_terminal_and_one_shot_owners_distinct():
    terminal = claude_contextual_capabilities(
        _snapshot(),
        transport="provider-terminal",
        process_owner="provider",
        session_generation=1,
        policy_allows=True,
    )
    one_shot = claude_contextual_capabilities(
        _snapshot(),
        transport="one-shot",
        process_owner="harness",
        session_generation=1,
        policy_allows=True,
    )
    terminal_by_id = {item.capability_id: item for item in terminal}
    one_shot_by_id = {item.capability_id: item for item in one_shot}

    assert terminal_by_id["session.continue.native"].state is CapabilityState.DEGRADED
    assert terminal_by_id["session.resume.native"].state is CapabilityState.DEGRADED
    assert terminal_by_id["session.fork.native"].state is CapabilityState.DEGRADED
    assert terminal_by_id["approval.provider_owned"].state is CapabilityState.READY
    assert terminal_by_id["one_shot.events.decode"].state is CapabilityState.BLOCKED
    assert one_shot_by_id["one_shot.events.decode"].state is CapabilityState.READY
    assert one_shot_by_id["session.resume.native"].state is CapabilityState.BLOCKED


def test_claude_one_shot_decoder_normalizes_reviewed_stream_without_session_claim():
    decoder = ClaudeOneShotEventDecoder(session_id="sess_1", workspace_id="workspace_1")
    message = decoder.decode(
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "hello"},
            },
            "providerSecret": "must-not-pass",
        }
    )
    result = decoder.decode(
        {
            "type": "result",
            "subtype": "success",
            "result": "hello",
            "usage": {"input_tokens": 3, "output_tokens": 2},
            "session_id": "provider-session-must-not-be-adopted",
        }
    )

    assert [(draft.payload_type, dict(draft.payload)) for draft in message] == [
        ("message.delta", {"role": "assistant", "delta": "hello"})
    ]
    assert [(draft.payload_type, dict(draft.payload)) for draft in result] == [
        (
            "usage.updated",
            {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
        )
    ]
    assert all(draft.session_id == "sess_1" for draft in (*message, *result))
    assert "providerSecret" not in repr(message)
    assert "provider-session-must-not-be-adopted" not in repr(result)


@pytest.mark.parametrize(
    ("suffix", "pattern", "selector", "operation"),
    (
        ((), "claude.root", None, None),
        (("inspect",), "claude.prompt", None, None),
        (("-c",), "claude.continue", None, "continue"),
        (("--continue",), "claude.continue", None, "continue"),
        (("-r", "migration-review"), "claude.resume", "migration-review", "resume"),
        (
            ("--resume", "11111111-1111-4111-8111-111111111111"),
            "claude.resume",
            "11111111-1111-4111-8111-111111111111",
            "resume",
        ),
        (
            ("--fork-session", "-r", "fixture-session"),
            "claude.resume",
            "fixture-session",
            "fork",
        ),
    ),
)
def test_claude_human_intents_are_affirmative_and_remain_provider_native(
    suffix, pattern, selector, operation
):
    decision = classify_native_route("claude", suffix, version="2.1.212")
    intent = parse_native_tui_launch_intent("claude", suffix, decision)

    assert decision.level is CapabilityLevel.MANAGED_HANDOFF
    assert decision.intent_pattern_id == pattern
    assert intent is not None
    assert intent.persistence == "provider_native"
    assert intent.native_session_selector == selector
    assert intent.session_operation == operation
    assert intent.provider_transport is None


@pytest.mark.parametrize(
    "suffix",
    (
        ("-c", "-p", "continue headless"),
        ("-r", "fixture-session", "-p", "resume headless"),
        ("--fork-session", "-r", "fixture-session", "-p", "fork headless"),
        ("exec", "fixture-job"),
        ("background", "list"),
        ("remote-control", "--help"),
    ),
)
def test_claude_headless_jobs_and_handoffs_are_never_harness_resume(suffix):
    decision = classify_native_route("claude", suffix, version="2.1.212")

    assert decision.level is CapabilityLevel.NATIVE_PASSTHROUGH
    assert decision.intent_pattern_id is None
    assert decision.command_class in {
        NativeCommandClass.HEADLESS,
        NativeCommandClass.ADMINISTRATION,
        NativeCommandClass.EXTERNAL_UI,
        NativeCommandClass.METADATA,
    }


@pytest.mark.skipif(os.name == "nt", reason="POSIX facade parity contract")
@pytest.mark.parametrize(
    "suffix",
    (
        ("-p", "inspect", "--output-format", "text"),
        ("-p", "inspect", "--output-format", "json"),
        ("-p", "inspect", "--output-format", "stream-json"),
        ("-c", "-p", "continue headless"),
        ("-r", "fixture-session", "-p", "resume headless"),
        ("--json-schema", "{}", "-p", "schema"),
        ("--permission-mode", "plan", "-p", "provider approval"),
        ("mcp", "list"),
        ("plugin", "list"),
        ("remote-control", "--help"),
        ("--help",),
        ("--version",),
        ("-p", "exit", "--fixture-exit=23"),
    ),
)
def test_direct_and_prefixed_claude_l0_match_in_isolated_home(tmp_path, suffix):
    executable = _make_claude_fixture(tmp_path / "claude")
    isolated_home = tmp_path / "home"
    isolated_home.mkdir()
    environment = {
        **os.environ,
        "PATH": os.fspath(tmp_path),
        "HOME": os.fspath(isolated_home),
        "CLAUDE_CONFIG_DIR": os.fspath(isolated_home / ".claude"),
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
            "claude",
            *suffix,
        ),
        env=environment,
        input=stdin,
        capture_output=True,
        check=False,
    )

    assert prefixed.returncode == direct.returncode
    assert prefixed.stdout == direct.stdout
    assert prefixed.stderr == direct.stderr
    payload = json.loads(prefixed.stdout)
    assert payload["argv"] == list(suffix)
    assert payload["stdin"] == "fixture stdin"
    assert payload["home"] == os.fspath(isolated_home)


@pytest.mark.skipif(os.name == "nt", reason="POSIX facade signal contract")
def test_prefixed_claude_headless_interruption_reaches_provider(tmp_path):
    _make_claude_fixture(tmp_path / "claude")
    process = subprocess.Popen(
        (
            sys.executable,
            "-c",
            "from gpt2giga_harness.entrypoint import main; raise SystemExit(main())",
            "claude",
            "-p",
            "--fixture-wait",
        ),
        env={**os.environ, "PATH": os.fspath(tmp_path)},
        stdout=subprocess.PIPE,
    )
    assert process.stdout is not None
    assert process.stdout.read(5) == b"ready"
    process.send_signal(signal.SIGINT)
    assert process.wait(timeout=5) == 41


def _make_claude_fixture(path: Path) -> Path:
    path.write_text(
        f"#!{sys.executable}\n"
        "import json, os, signal, sys, time\n"
        "if '--fixture-wait' in sys.argv:\n"
        "    signal.signal(signal.SIGINT, lambda *_: os._exit(41))\n"
        "    os.write(1, b'ready')\n"
        "    time.sleep(10)\n"
        "payload = {'argv': sys.argv[1:], 'stdin': os.read(0, 1000).decode(), "
        "'home': os.environ.get('HOME')}\n"
        "os.write(1, json.dumps(payload, sort_keys=True).encode())\n"
        "os.write(2, b'fixture-stderr')\n"
        "raise SystemExit(23 if '--fixture-exit=23' in sys.argv else 0)\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path
