from __future__ import annotations

import pytest

from gpt2giga_harness.cli_capabilities import CliCapabilitySnapshot
from gpt2giga_harness.harnesses.codex_workbench import (
    CodexAppServerEventDecoder,
    admit_codex_workbench,
    codex_contextual_capabilities,
)
from gpt2giga_harness.native_cli_contracts import CapabilityState


def _snapshot(*, version: str, supported: bool = True, app_server: bool = True):
    return CliCapabilitySnapshot(
        harness_id="codex-cli",
        status="supported" if supported else "degraded",
        version=f"codex-cli {version}",
        parsed_version=version,
        command=("/fixture/codex",),
        capabilities={"app-server": app_server},
        event_schema="codex-exec-jsonl-v1",
        history_schema="codex-session-jsonl-v1",
    )


def test_codex_pack_admits_only_reviewed_app_server_window():
    assert admit_codex_workbench(_snapshot(version="0.144.5")).admitted is True
    assert admit_codex_workbench(_snapshot(version="0.145.0")).admitted is False
    assert (
        admit_codex_workbench(_snapshot(version="0.144.5", app_server=False)).admitted
        is False
    )


def test_codex_capabilities_are_contextual_and_fail_closed_on_policy():
    admitted = codex_contextual_capabilities(
        _snapshot(version="0.144.5"), session_generation=1, policy_allows=True
    )
    denied = codex_contextual_capabilities(
        _snapshot(version="0.144.5"), session_generation=1, policy_allows=False
    )

    assert {item.capability_id for item in admitted} >= {
        "session.resume.native",
        "session.fork.native",
        "turn.steer",
        "turn.cancel",
        "approval.decide",
    }
    assert all(item.state is CapabilityState.READY for item in admitted)
    assert all(item.state is CapabilityState.BLOCKED for item in denied)


def test_codex_decoder_discards_raw_provider_envelope_and_normalizes_events():
    decoder = CodexAppServerEventDecoder(
        session_id="sess_1", workspace_id="workspace_1"
    )
    raw = {
        "jsonrpc": "2.0",
        "method": "item/agentMessage/delta",
        "params": {
            "threadId": "thread_1",
            "turnId": "turn_1",
            "itemId": "item_1",
            "delta": "hello",
            "providerSecret": "must-not-pass",
        },
    }

    draft = decoder.decode(raw)

    assert draft.payload_type == "message.delta"
    assert dict(draft.payload) == {"role": "assistant", "delta": "hello"}
    assert "jsonrpc" not in repr(draft)
    assert "providerSecret" not in repr(draft)


def test_codex_decoder_rejects_unknown_provider_semantics():
    decoder = CodexAppServerEventDecoder(
        session_id="sess_1", workspace_id="workspace_1"
    )

    with pytest.raises(ValueError, match="unsupported Codex"):
        decoder.decode({"method": "future/provider/event", "params": {}})
