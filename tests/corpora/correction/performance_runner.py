"""Hermetic identical-workload runner for corrective performance evidence."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import json
import math
from time import monotonic_ns
import tracemalloc
from typing import Any


@dataclass(frozen=True)
class PerformanceSample:
    """One bounded latency and peak-memory sample set."""

    workload_id: str
    workload_fingerprint: str
    latencies_ns: tuple[int, ...]
    peak_memory_bytes: int

    def __post_init__(self) -> None:
        if not self.latencies_ns:
            raise ValueError("latencies_ns must not be empty")
        if any(value < 0 for value in self.latencies_ns):
            raise ValueError("latencies_ns must be non-negative")
        if self.peak_memory_bytes < 0:
            raise ValueError("peak_memory_bytes must be non-negative")

    @property
    def p50_ns(self) -> int:
        return percentile(self.latencies_ns, 50)

    @property
    def p95_ns(self) -> int:
        return percentile(self.latencies_ns, 95)


@dataclass(frozen=True)
class PerformanceComparison:
    """Comparable before/after evidence for one exact workload."""

    workload_id: str
    workload_fingerprint: str
    before_p50_ns: int
    after_p50_ns: int
    before_p95_ns: int
    after_p95_ns: int
    p50_ratio: float
    p95_ratio: float
    peak_memory_delta_bytes: int


def workload_fingerprint(workload: Mapping[str, Any]) -> str:
    """Return a stable digest that makes workload drift explicit."""
    canonical = json.dumps(
        workload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def percentile(values: tuple[int, ...], percent: int) -> int:
    """Calculate a deterministic nearest-rank percentile."""
    if not values:
        raise ValueError("values must not be empty")
    if not 0 < percent <= 100:
        raise ValueError("percent must be in (0, 100]")
    ordered = sorted(values)
    rank = max(1, math.ceil(percent / 100 * len(ordered)))
    return ordered[rank - 1]


def measure_sync(
    workload_id: str,
    workload: Mapping[str, Any],
    operation: Callable[[], Any],
    *,
    iterations: int,
    warmup_iterations: int,
) -> PerformanceSample:
    """Measure one synchronous hermetic operation with bounded retention."""
    if iterations <= 0 or warmup_iterations < 0:
        raise ValueError("iteration counts must be positive and bounded")
    for _ in range(warmup_iterations):
        operation()

    latencies: list[int] = []
    tracemalloc.start()
    try:
        for _ in range(iterations):
            started = monotonic_ns()
            operation()
            latencies.append(monotonic_ns() - started)
        _, peak_memory = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    return PerformanceSample(
        workload_id=workload_id,
        workload_fingerprint=workload_fingerprint(workload),
        latencies_ns=tuple(latencies),
        peak_memory_bytes=peak_memory,
    )


def compare_samples(
    before: PerformanceSample,
    after: PerformanceSample,
) -> PerformanceComparison:
    """Compare only samples produced from the same exact workload."""
    if before.workload_id != after.workload_id:
        raise ValueError("workload IDs differ")
    if before.workload_fingerprint != after.workload_fingerprint:
        raise ValueError("workload fingerprints differ")
    return PerformanceComparison(
        workload_id=before.workload_id,
        workload_fingerprint=before.workload_fingerprint,
        before_p50_ns=before.p50_ns,
        after_p50_ns=after.p50_ns,
        before_p95_ns=before.p95_ns,
        after_p95_ns=after.p95_ns,
        p50_ratio=_ratio(after.p50_ns, before.p50_ns),
        p95_ratio=_ratio(after.p95_ns, before.p95_ns),
        peak_memory_delta_bytes=(after.peak_memory_bytes - before.peak_memory_bytes),
    )


def _ratio(after: int, before: int) -> float:
    if before == 0:
        return 1.0 if after == 0 else math.inf
    return after / before
