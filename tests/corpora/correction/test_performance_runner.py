"""Reproducibility contracts for corrective before/after performance evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from performance_runner import (
    PerformanceSample,
    compare_samples,
    measure_sync,
    percentile,
    workload_fingerprint,
)


CORPUS = Path(__file__).parent / "v1" / "performance_workloads.json"


def _load() -> dict:
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def test_performance_corpus_closes_every_required_workload() -> None:
    corpus = _load()

    assert {case["id"] for case in corpus["workloads"]} == {
        "capability-resolution",
        "catalog-concurrent-refresh",
        "catalog-memory-growth",
        "models-cold",
        "models-warm",
        "responses-native-admission",
        "responses-normalized-admission",
    }
    assert corpus["rules"] == {
        "clock": "monotonic_ns",
        "identical_workload_fingerprint_required": True,
        "live_provider_traffic": False,
        "memory_meter": "tracemalloc_peak",
        "percentiles": [50, 95],
    }


def test_corpus_forbids_claims_until_the_integrated_correction_is_measured() -> None:
    corpus = _load()

    assert corpus["baseline_sha"] == ("e14fc5d4d547da57745bbc1b47dfa8dcf1dd3d25")
    assert corpus["measurement_status"] == "awaiting_integrated_correction"
    assert corpus["performance_claim_allowed"] is False


def test_workload_fingerprint_is_stable_and_detects_any_parameter_drift() -> None:
    first = {"iterations": 50, "model_count": 128, "parallelism": 1}
    reordered = {"parallelism": 1, "model_count": 128, "iterations": 50}
    drifted = {**first, "parallelism": 2}

    assert workload_fingerprint(first) == workload_fingerprint(reordered)
    assert workload_fingerprint(first) != workload_fingerprint(drifted)


def test_percentiles_and_comparison_use_identical_nearest_rank_samples() -> None:
    fingerprint = workload_fingerprint({"case": "fixture"})
    before = PerformanceSample(
        "fixture",
        fingerprint,
        (100, 200, 300, 400, 500),
        1024,
    )
    after = PerformanceSample(
        "fixture",
        fingerprint,
        (110, 220, 330, 440, 550),
        1280,
    )

    comparison = compare_samples(before, after)

    assert percentile(before.latencies_ns, 50) == 300
    assert percentile(before.latencies_ns, 95) == 500
    assert comparison.before_p50_ns == 300
    assert comparison.after_p50_ns == 330
    assert comparison.before_p95_ns == 500
    assert comparison.after_p95_ns == 550
    assert comparison.p50_ratio == pytest.approx(1.1)
    assert comparison.p95_ratio == pytest.approx(1.1)
    assert comparison.peak_memory_delta_bytes == 256


def test_comparison_rejects_non_identical_workloads() -> None:
    before = PerformanceSample("fixture", "before", (100,), 0)
    after = PerformanceSample("fixture", "after", (100,), 0)

    with pytest.raises(ValueError, match="fingerprints differ"):
        compare_samples(before, after)


def test_runner_collects_bounded_latency_and_peak_memory_samples() -> None:
    calls = 0

    def operation() -> int:
        nonlocal calls
        calls += 1
        return sum(range(32))

    sample = measure_sync(
        "fixture",
        {"iterations": 5, "warmup_iterations": 2},
        operation,
        iterations=5,
        warmup_iterations=2,
    )

    assert calls == 7
    assert len(sample.latencies_ns) == 5
    assert all(value >= 0 for value in sample.latencies_ns)
    assert sample.peak_memory_bytes >= 0


def test_every_workload_has_explicit_bounded_guardrails() -> None:
    for case in _load()["workloads"]:
        workload = case["workload"]
        guardrails = case["guardrails"]
        assert 0 < workload["iterations"] <= 5000
        assert 0 <= workload["warmup_iterations"] <= 500
        assert 1 <= workload["parallelism"] <= 32
        assert 1.0 <= guardrails["max_p95_regression_ratio"] <= 1.20
        if case["id"] == "catalog-memory-growth":
            assert workload["model_counts"] == [0, 64, 256, 1024]
            assert guardrails["max_peak_bytes_per_model"] == 4096
            assert guardrails["max_fixed_peak_bytes"] == 2 * 1024 * 1024
        else:
            assert guardrails["max_p95_ms"] > 0


def test_performance_corpus_is_hermetic_and_bounded() -> None:
    raw = CORPUS.read_bytes()

    assert 0 < len(raw) < 32 * 1024
    assert raw.endswith(b"\n")
    assert b"Bearer " not in raw
    assert b"sk-" not in raw
