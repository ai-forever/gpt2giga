from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from gpt2giga_harness.sessions import FilesystemHarnessSessionStore


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "harness_p2_5_baseline.py"
LEGACY_BASELINE_PATH = (
    REPO_ROOT / "benchmarks" / "harness_p2_5" / "legacy-baseline.json"
)


def _load_script():
    spec = importlib.util.spec_from_file_location("harness_p2_5_baseline", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


baseline = _load_script()


def test_frozen_profile_matches_p2_5_reference_contract() -> None:
    assert baseline.validate_profile() == {
        "profile_id": "gpt2giga-harness-p2.5-v1",
        "reference_sessions": 1000,
        "reference_messages": 5000,
        "reference_events": 50000,
        "required_signals": sorted(baseline.REQUIRED_SIGNALS),
        "budget_count": 20,
        "viewports": ["desktop", "mobile-390"],
    }


def test_smoke_fixture_is_hermetic_bounded_and_reinspectable(tmp_path) -> None:
    destination = tmp_path / "fixture"

    summary = baseline.prepare_fixture(destination, workload="smoke")

    assert summary == {
        "valid": True,
        "profile_id": "gpt2giga-harness-p2.5-v1",
        "workload": "smoke",
        "sessions": 10,
        "messages": 50,
        "events": 500,
        "artifact_bytes_each": 65536,
        "sustained_sse_events": 20,
        "burst_sse_events": 50,
        "sqlite_contention_rows": 100,
    }
    assert baseline.inspect_fixture(destination) == summary
    assert not (destination / ".git").exists()
    bundle = FilesystemHarnessSessionStore(destination / "data").get_session_bundle(
        "sess_ref_hot"
    )
    assert len(bundle.messages) == 50
    assert len(bundle.events) == 500
    assert bundle.runs[0].capability.value == "chat_completions"
    with pytest.raises(baseline.BaselineContractError, match="already exists"):
        baseline.prepare_fixture(destination, workload="smoke")


def test_result_requires_complete_measured_or_explained_signal_set(tmp_path) -> None:
    signals = {
        signal: {
            "status": "measured",
            "values": {"p50": 1.0, "p95": 2.0, "p99": 3.0},
        }
        for signal in baseline.REQUIRED_SIGNALS
    }
    signals["event_loop_lag"] = {
        "status": "unavailable",
        "reason": "Legacy UI has no event-loop lag instrumentation.",
    }
    result = {
        "schema_version": 1,
        "profile_id": "gpt2giga-harness-p2.5-v1",
        "environment": {
            "captured_at": "2026-07-15T12:00:00Z",
            "os": "test-os",
            "architecture": "test-arch",
            "python": "3.13.0",
            "browser": "test-browser",
            "commit": "a" * 40,
        },
        "signals": signals,
        "viewports": [
            {"id": "desktop", "width": 1440, "height": 900},
            {"id": "mobile-390", "width": 390, "height": 844},
        ],
        "scenarios": {
            scenario: {"status": "recorded"}
            for scenario in (
                "cold_boot",
                "large_history",
                "large_artifacts",
                "sustained_and_burst_sse",
                "native_output",
                "sqlite_contention",
                "disconnect_reconnect",
                "soak",
            )
        },
    }
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps(result), encoding="utf-8")

    summary = baseline.validate_result(result_path)

    assert summary["valid"] is True
    assert summary["measured_signals"] == len(baseline.REQUIRED_SIGNALS) - 1
    assert summary["unavailable_signals"] == 1

    result["signals"]["event_loop_lag"] = {"status": "unavailable"}
    result_path.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(baseline.BaselineContractError, match="requires a reason"):
        baseline.validate_result(result_path)


def test_recorded_legacy_baseline_is_complete_and_truthful() -> None:
    summary = baseline.validate_result(LEGACY_BASELINE_PATH)
    payload = json.loads(LEGACY_BASELINE_PATH.read_text(encoding="utf-8"))

    assert summary["valid"] is True
    assert summary["measured_signals"] == 2
    assert summary["unavailable_signals"] == 9
    assert (
        payload["signals"]["payload_bytes"]["values"]["large_session_bundle"]
        == 17_419_992
    )
    assert payload["viewports"][1]["width"] == 390
    assert payload["scenarios"]["soak"]["status"] == "fixture_ready"
