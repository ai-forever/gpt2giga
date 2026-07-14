import json
from pathlib import Path
import sys

import pytest

from gpt2giga_harness.cli_capabilities import (
    cli_capability_snapshot_to_dict,
    invalidate_cli_probe_cache,
    probe_cli_capabilities,
)
from gpt2giga_harness.executables import ExecutableResolution
from gpt2giga_harness.harnesses.agent_cli import run_streaming_command
from gpt2giga_harness.harnesses.claude_code import _ClaudeStreamParser
from gpt2giga_harness.harnesses.codex_cli import _CodexStreamParser
from gpt2giga_harness.harnesses.gemini_cli import _GeminiStreamParser
from gpt2giga_harness.native import claude, codex, gemini
from gpt2giga_harness.types import HarnessRequest

FIXTURES = Path(__file__).parents[1] / "fixtures" / "harness_cli"


@pytest.fixture(autouse=True)
def clear_probe_cache():
    invalidate_cli_probe_cache()
    yield
    invalidate_cli_probe_cache()


@pytest.mark.parametrize(
    ("harness_id", "version", "help_output", "expected_schema"),
    (
        (
            "codex-cli",
            "codex-cli 0.144.3",
            "exec --json --sandbox --ephemeral --image --config --strict-config",
            "codex-exec-jsonl-v1",
        ),
        (
            "claude-code",
            "2.1.197 (Claude Code)",
            "--output-format stream-json --permission-mode "
            "--no-session-persistence --include-partial-messages --resume "
            "--effort --allowedTools --disallowedTools",
            "claude-stream-json-v1",
        ),
        (
            "gemini-cli",
            "0.46.0",
            "--output-format stream-json --approval-mode --skip-trust "
            "--prompt-interactive --list-sessions --resume",
            "gemini-stream-json-v1",
        ),
    ),
)
def test_probe_proves_required_contract_and_caches_by_command_version(
    monkeypatch, harness_id, version, help_output, expected_schema
):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        output = version if command[-1] == "--version" else help_output
        return _Completed(stdout=output)

    monkeypatch.setattr(
        "gpt2giga_harness.cli_capabilities.subprocess.run",
        fake_run,
    )
    resolution = ExecutableResolution(
        harness_id=harness_id,
        command_name="fixture",
        executable="/tmp/fixture",
        source="user_config",
        argv=("/tmp/wrapper", "--profile", "safe"),
    )

    first = probe_cli_capabilities(resolution, harness_id)
    second = probe_cli_capabilities(resolution, harness_id)
    invalidate_cli_probe_cache()
    third = probe_cli_capabilities(resolution, harness_id)

    assert first == second
    assert third == first
    assert first.compatible is True
    assert first.parsed_version is not None
    assert first.event_schema == expected_schema
    assert calls[0][0:3] == ("/tmp/wrapper", "--profile", "safe")
    assert len(calls) == 5  # cached call only refreshes the version cache key
    assert cli_capability_snapshot_to_dict(first)["warning"] is None


def test_probe_rejects_present_binary_without_required_contract(monkeypatch):
    outputs = iter(("gemini 0.1.0", "usage: gemini"))
    monkeypatch.setattr(
        "gpt2giga_harness.cli_capabilities.subprocess.run",
        lambda *args, **kwargs: _Completed(stdout=next(outputs)),
    )
    resolution = ExecutableResolution(
        harness_id="gemini-cli",
        command_name="gemini",
        executable="/tmp/gemini",
        source="path",
        argv=("/tmp/gemini",),
    )

    snapshot = probe_cli_capabilities(resolution, "gemini-cli")

    assert snapshot.status == "unsupported"
    assert snapshot.compatible is False
    assert "--output-format" in (snapshot.warning or "")
    assert "usage: gemini" not in json.dumps(cli_capability_snapshot_to_dict(snapshot))


@pytest.mark.parametrize(
    ("fixture", "parser", "expected"),
    (
        ("codex/0.144/exec.jsonl", _CodexStreamParser, "Codex fixture"),
        ("claude/2.1/stream.jsonl", _ClaudeStreamParser, "Claude fixture"),
        ("gemini/0.46/stream.jsonl", _GeminiStreamParser, "Gemini fixture"),
    ),
)
def test_versioned_headless_fixtures_allow_unknown_additive_fields(
    fixture, parser, expected
):
    instance = parser()
    messages = []
    for line in (FIXTURES / fixture).read_text(encoding="utf-8").splitlines():
        messages.extend(instance(json.loads(line)))

    assert instance.recognized_payloads > 0
    assert expected in "".join(
        str(event.payload.get("delta") or "")
        for event in messages
        if event.type == "message_delta"
    )


def test_versioned_native_history_fixtures_remain_parseable():
    codex_messages = tuple(
        codex._iter_messages(FIXTURES / "codex/0.144/history.jsonl", max_messages=None)
    )
    claude_messages = tuple(
        claude._iter_session_messages(
            FIXTURES / "claude/2.1/history.jsonl", max_messages=None
        )
    )
    gemini_messages = tuple(
        gemini._iter_messages(FIXTURES / "gemini/0.46/history.json", max_messages=None)
    )

    assert [message.role for message in codex_messages] == ["user", "assistant"]
    assert [message.role for message in claude_messages] == ["user", "assistant"]
    assert [message.role for message in gemini_messages] == ["user", "assistant"]


def test_structured_stream_fails_when_required_event_contract_is_absent():
    parser = _GeminiStreamParser()
    result = run_streaming_command(
        label="Gemini CLI",
        command=(
            sys.executable,
            "-c",
            'print(r\'{"type":"future_additive_event","value":1}\')',
        ),
        env={},
        cwd=None,
        timeout_seconds=5,
        request=HarnessRequest(prompt="fixture"),
        parse_payload=parser,
    )

    assert result.ok is False
    assert result.error == (
        "Structured CLI output did not contain a recognized event contract"
    )


class _Completed:
    def __init__(self, *, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
