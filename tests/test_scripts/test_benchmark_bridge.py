"""Tests for the hermetic normalized bridge benchmark."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "benchmark_bridge.py"
SPEC = importlib.util.spec_from_file_location("benchmark_bridge", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_percentile_uses_nearest_rank() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert MODULE.percentile(values, 0.50) == 3.0
    assert MODULE.percentile(values, 0.95) == 5.0


def test_selected_workloads_are_measured_and_mechanism_checked() -> None:
    report = MODULE.run_benchmarks(
        samples=2,
        iterations=1,
        warmups=1,
        workload_names=(
            "responses_stream_first_event",
            "alias_profile_admission",
            "capabilities_endpoint",
        ),
        label="test",
    )

    assert report["schema_version"] == MODULE.REPORT_SCHEMA_VERSION
    assert report["label"] == "test"
    assert [item["name"] for item in report["workloads"]] == [
        "responses_stream_first_event",
        "alias_profile_admission",
        "capabilities_endpoint",
    ]
    for result in report["workloads"]:
        assert result["p50_us"] > 0
        assert result["p95_us"] >= result["p50_us"]
        assert result["mechanism"]


def test_report_comparison_uses_negative_percent_for_improvement() -> None:
    baseline = {
        "schema_version": MODULE.REPORT_SCHEMA_VERSION,
        "workloads": [{"name": "route", "p50_us": 10.0, "p95_us": 20.0}],
    }
    candidate = {
        "schema_version": MODULE.REPORT_SCHEMA_VERSION,
        "workloads": [{"name": "route", "p50_us": 8.0, "p95_us": 15.0}],
    }

    assert MODULE.compare_reports(baseline, candidate) == [
        {
            "name": "route",
            "p50_change_percent": -20.0,
            "p95_change_percent": -25.0,
        }
    ]


def test_unknown_workload_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown workloads"):
        MODULE.run_benchmarks(workload_names=("missing",))
