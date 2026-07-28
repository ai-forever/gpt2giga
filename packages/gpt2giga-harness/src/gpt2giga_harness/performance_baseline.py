"""Content-free performance baselines for the local Harness product."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sqlite3
import statistics
import sys
import tempfile
import time
from typing import Any, Final

try:
    import resource
except ModuleNotFoundError:  # pragma: no cover - exercised on Windows
    resource = None

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.ui.app import create_app


SCHEMA_VERSION: Final[str] = "gigaloom.performance-baseline.v2"
FIXTURE_SET_VERSION: Final[str] = "g6-03.v1"
REGRESSION_BASELINE_ID: Final[str] = "gigaloom.performance-regression.g6-03.v1"
DEFAULT_SMOKE_SAMPLES: Final[int] = 5
MAX_SAMPLES: Final[int] = 100

# Only deterministic in-memory projections are allowed to fail pull-request CI.
CI_SMOKE_BUDGETS_MS: Final[dict[str, float]] = {
    "session_projection_1": 100.0,
    "session_projection_10": 150.0,
    "session_projection_100": 500.0,
    "long_transcript_projection": 750.0,
}

# These loose bounds remain visible in detailed reports but are deliberately
# excluded from pull-request pass/fail because runner I/O and process startup
# are environment-sensitive.
DETAIL_REFERENCE_BUDGETS_MS: Final[dict[str, float]] = {
    **CI_SMOKE_BUDGETS_MS,
    "filesystem_roundtrip": 250.0,
    "sqlite_transaction": 500.0,
    "tui_interaction": 10_000.0,
    "worker_queue_claim_cancel": 2_000.0,
    "web_api_defaults": 10_000.0,
}

REPORT_ARTIFACT_MAX_BYTES: Final[dict[str, int]] = {
    "ci-smoke": 64 * 1024,
    "local-detail": 512 * 1024,
    "tui-detail": 2 * 1024 * 1024,
    "runtime-detail": 2 * 1024 * 1024,
}
REPORT_RETENTION_DAYS: Final[dict[str, int]] = {
    "ci-smoke": 7,
    "local-detail": 14,
    "tui-detail": 14,
    "runtime-detail": 14,
}

REQUIRED_WORKLOADS: Final[tuple[dict[str, Any], ...]] = (
    {
        "id": "tui_startup",
        "variants": ("cold", "warm", "first_input"),
        "required_metrics": ("wall_ms", "cpu_ms", "rss_bytes"),
        "future_gate": "G5-00",
    },
    {
        "id": "tui_paint",
        "variants": ("keypress", "event", "stream", "cancel"),
        "required_percentiles": ("p50", "p95", "p99"),
        "future_gate": "G5-00",
    },
    {
        "id": "session_scale",
        "variants": (1, 10, 100, "long_transcript"),
        "required_metrics": ("wall_ms", "cpu_ms", "rss_bytes"),
        "future_gate": "G5-00",
    },
    {
        "id": "worker_runtime",
        "variants": (
            "idle",
            "active",
            "queue_claim",
            "scheduled_wake",
            "retry_reconcile",
            "cancellation",
            "recovery",
        ),
        "required_metrics": (
            "wall_ms",
            "cpu_ms",
            "rss_bytes",
            "wakeups",
            "sqlite_writes",
        ),
        "future_gate": "G6-00",
    },
    {
        "id": "web_pipeline",
        "variants": (
            "request",
            "sse_attach",
            "sse_resnapshot",
            "database",
            "filesystem",
            "provider_adapter",
        ),
        "required_metrics": (
            "wall_ms",
            "cpu_ms",
            "io_wait_ms",
            "database_ms",
            "filesystem_ms",
            "provider_ms",
        ),
        "future_gate": "G6-00",
    },
)


@dataclass(frozen=True)
class _Sample:
    wall_ms: float
    cpu_ms: float
    rss_bytes: int
    input_blocks: int
    output_blocks: int
    stages_ms: Mapping[str, float]


def run_performance_baseline(
    *,
    samples: int = DEFAULT_SMOKE_SAMPLES,
    profile: str = "ci-smoke",
) -> dict[str, Any]:
    """Run bounded, hermetic probes and return a content-free JSON report."""
    if profile not in {
        "ci-smoke",
        "local-detail",
        "tui-detail",
        "runtime-detail",
    }:
        raise ValueError(
            "profile must be ci-smoke, local-detail, tui-detail, or runtime-detail"
        )
    if not 1 <= samples <= MAX_SAMPLES:
        raise ValueError(f"samples must be between 1 and {MAX_SAMPLES}")
    if profile == "tui-detail":
        from gpt2giga_harness.tui_performance_profile import (
            run_tui_performance_profile,
        )

        return _finalize_report(run_tui_performance_profile(samples=samples))
    if profile == "runtime-detail":
        from gpt2giga_harness.runtime_performance_profile import (
            run_runtime_performance_profile,
        )

        return _finalize_report(run_runtime_performance_profile(samples=samples))

    with tempfile.TemporaryDirectory(prefix="gigaloom-perf-") as raw_root:
        root = Path(raw_root)
        probes: dict[str, Callable[[], Mapping[str, float]]] = {
            "filesystem_roundtrip": lambda: _probe_filesystem(root),
            "sqlite_transaction": lambda: _probe_sqlite(root),
            "session_projection_1": lambda: _probe_session_projection(1),
            "session_projection_10": lambda: _probe_session_projection(10),
            "session_projection_100": lambda: _probe_session_projection(100),
            "long_transcript_projection": _probe_long_transcript,
            "tui_interaction": _probe_tui_interaction,
            "worker_queue_claim_cancel": lambda: _probe_worker_runtime(root),
            "web_api_defaults": lambda: _probe_web_api(root),
        }
        selected = (
            tuple(CI_SMOKE_BUDGETS_MS)
            if profile == "ci-smoke"
            else tuple(DETAIL_REFERENCE_BUDGETS_MS)
        )
        results = [
            _summarize_probe(
                name,
                probes[name],
                samples=samples,
                include_samples=profile == "local-detail",
            )
            for name in selected
        ]

    failed = [
        result["id"]
        for result in results
        if result["regression_gate"]["blocking"]
        and result["percentiles_ms"]["p95"]
        > result["regression_gate"]["budget_ms"]["p95"]
    ]
    return _finalize_report(
        {
            "schema_version": SCHEMA_VERSION,
            "fixture_set_version": FIXTURE_SET_VERSION,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "profile": profile,
            "samples_per_probe": samples,
            "environment": {
                "python": platform.python_version(),
                "implementation": platform.python_implementation(),
                "platform": platform.platform(),
            },
            "privacy": {
                "content_captured": False,
                "secrets_captured": False,
                "native_homes_accessed": False,
                "provider_traffic": False,
                "network_accessed": False,
                "temporary_state_only": True,
            },
            "measurement_contract": {
                "required_workloads": list(REQUIRED_WORKLOADS),
                "unavailable_metrics_are_null": True,
                "optimization_targets_require_explicit_review": True,
                "detailed_traces_are_opt_in": True,
                "ci_gate_metrics": list(CI_SMOKE_BUDGETS_MS),
                "detail_only_metrics": sorted(
                    set(DETAIL_REFERENCE_BUDGETS_MS) - set(CI_SMOKE_BUDGETS_MS)
                ),
                "provider_or_external_network_latency_is_blocking": False,
            },
            "results": results,
            "status": "failed" if failed else "passed",
            "failed_budgets": failed,
        }
    )


def write_performance_report(path: str | Path, report: Mapping[str, Any]) -> None:
    """Atomically write a private canonical JSON report."""
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode()
    policy = report.get("artifact_policy")
    max_bytes = (
        policy.get("max_bytes")
        if isinstance(policy, Mapping)
        else max(REPORT_ARTIFACT_MAX_BYTES.values())
    )
    if not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("performance report artifact limit is invalid")
    if len(payload) > max_bytes:
        raise ValueError(
            f"performance report is {len(payload)} bytes; limit is {max_bytes}"
        )
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _summarize_probe(
    name: str,
    probe: Callable[[], Mapping[str, float]],
    *,
    samples: int,
    include_samples: bool,
) -> dict[str, Any]:
    observations = [_measure(probe) for _ in range(samples)]
    wall = sorted(sample.wall_ms for sample in observations)
    cpu = sorted(sample.cpu_ms for sample in observations)
    stages = sorted({key for sample in observations for key in sample.stages_ms})
    blocking = name in CI_SMOKE_BUDGETS_MS
    budget = (
        CI_SMOKE_BUDGETS_MS[name] if blocking else DETAIL_REFERENCE_BUDGETS_MS[name]
    )
    summary = {
        "id": name,
        "percentiles_ms": {
            "p50": _percentile(wall, 50),
            "p95": _percentile(wall, 95),
            "p99": _percentile(wall, 99),
        },
        "cpu_ms": {
            "mean": round(statistics.fmean(cpu), 3),
            "p95": _percentile(cpu, 95),
        },
        "rss_bytes": max(sample.rss_bytes for sample in observations),
        "io": {
            "input_blocks": sum(sample.input_blocks for sample in observations),
            "output_blocks": sum(sample.output_blocks for sample in observations),
            "io_wait_ms": None,
        },
        "stages_ms": {
            stage: {
                "p50": _percentile(
                    sorted(sample.stages_ms.get(stage, 0.0) for sample in observations),
                    50,
                ),
                "p95": _percentile(
                    sorted(sample.stages_ms.get(stage, 0.0) for sample in observations),
                    95,
                ),
                "p99": _percentile(
                    sorted(sample.stages_ms.get(stage, 0.0) for sample in observations),
                    99,
                ),
            }
            for stage in stages
        },
        "regression_gate": {
            "blocking": blocking,
            "classification": (
                "environment_stable_ci" if blocking else "scheduled_or_opt_in_detail"
            ),
            "budget_ms": {"percentile": "p95", "p95": budget},
        },
        "optimization_target_ms": None,
        "target_status": "requires_explicit_review",
    }
    if include_samples:
        summary["samples"] = [
            {
                "wall_ms": round(sample.wall_ms, 3),
                "cpu_ms": round(sample.cpu_ms, 3),
                "rss_bytes": sample.rss_bytes,
                "input_blocks": sample.input_blocks,
                "output_blocks": sample.output_blocks,
                "stages_ms": {
                    key: round(value, 3) for key, value in sample.stages_ms.items()
                },
            }
            for sample in observations
        ]
    return summary


def _finalize_report(report: dict[str, Any]) -> dict[str, Any]:
    profile = str(report["profile"])
    environment = dict(report.get("environment") or {})
    environment.setdefault("sqlite", sqlite3.sqlite_version)
    fingerprint_fields = {
        key: environment[key] for key in sorted(environment) if key != "fingerprint"
    }
    fingerprint_payload = json.dumps(
        fingerprint_fields,
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=True,
    ).encode()
    environment["fingerprint"] = {
        "algorithm": "sha256",
        "value": hashlib.sha256(fingerprint_payload).hexdigest(),
        "fields": list(fingerprint_fields),
    }
    report["environment"] = environment
    report["baseline"] = {
        "id": REGRESSION_BASELINE_ID,
        "profile": profile,
        "schema_version": report["schema_version"],
        "fixture_set_version": report["fixture_set_version"],
        "comparison": "tracked_absolute_budget",
        "budget_source": "versioned_profile_constants",
        "ci_blocking_metrics": (
            list(CI_SMOKE_BUDGETS_MS) if profile == "ci-smoke" else []
        ),
        "external_latency_failure_policy": "excluded",
    }
    report["artifact_policy"] = {
        "max_bytes": REPORT_ARTIFACT_MAX_BYTES[profile],
        "retention_days": REPORT_RETENTION_DAYS[profile],
        "bounded_samples_max": MAX_SAMPLES,
        "content_free": True,
    }
    return report


def _measure(probe: Callable[[], Mapping[str, float]]) -> _Sample:
    before_rss, before_input, before_output = _resource_usage()
    before_wall = time.perf_counter_ns()
    before_cpu = time.process_time_ns()
    stages = probe()
    after_cpu = time.process_time_ns()
    after_wall = time.perf_counter_ns()
    after_rss, after_input, after_output = _resource_usage()
    return _Sample(
        wall_ms=(after_wall - before_wall) / 1_000_000,
        cpu_ms=(after_cpu - before_cpu) / 1_000_000,
        rss_bytes=after_rss,
        input_blocks=max(after_input - before_input, 0),
        output_blocks=max(after_output - before_output, 0),
        stages_ms=dict(stages),
    )


def _probe_filesystem(root: Path) -> Mapping[str, float]:
    path = root / "content-free.bin"
    started = time.perf_counter_ns()
    path.write_bytes(b"\0" * 4096)
    write_ms = _elapsed_ms(started)
    started = time.perf_counter_ns()
    assert len(path.read_bytes()) == 4096
    read_ms = _elapsed_ms(started)
    path.unlink()
    return {"filesystem_write": write_ms, "filesystem_read": read_ms}


def _probe_sqlite(root: Path) -> Mapping[str, float]:
    path = root / "baseline.sqlite3"
    started = time.perf_counter_ns()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS samples (id INTEGER PRIMARY KEY, value TEXT)"
        )
        connection.execute("INSERT INTO samples(value) VALUES (?)", ("fixture",))
        connection.execute("SELECT COUNT(*) FROM samples").fetchone()
        connection.execute("DELETE FROM samples")
    return {"database": _elapsed_ms(started)}


def _probe_session_projection(count: int) -> Mapping[str, float]:
    rows = [
        {
            "id": f"session_{index}",
            "title": "content-free",
            "status": "idle",
            "events": index % 5,
        }
        for index in range(count)
    ]
    started = time.perf_counter_ns()
    encoded = json.dumps({"sessions": rows}, separators=(",", ":"), sort_keys=True)
    json.loads(encoded)
    return {"projection": _elapsed_ms(started)}


def _probe_long_transcript() -> Mapping[str, float]:
    events = [
        {"id": index, "type": "delta", "text": "x" * 80} for index in range(1_000)
    ]
    started = time.perf_counter_ns()
    encoded = json.dumps(events, separators=(",", ":"))
    json.loads(encoded)
    return {"projection": _elapsed_ms(started)}


def _probe_tui_interaction() -> Mapping[str, float]:
    return asyncio.run(_run_tui_interaction())


async def _run_tui_interaction() -> Mapping[str, float]:
    from textual.widgets import Input

    from gpt2giga_harness.tui.app import WorkbenchTui
    from gpt2giga_harness.tui.client import (
        HarnessSummary,
        NavigationSnapshot,
        ProjectSummary,
        ReadinessSummary,
    )

    project = ProjectSummary("fixture", "Fixture", "/tmp/fixture", "main", 0)
    snapshot = NavigationSnapshot(
        transport_mode="in_process",
        projects=(project,),
        project=project,
        sessions=(),
        selected_session_id=None,
        harnesses=(HarnessSummary("echo", "Echo", "available", "local", "one_shot"),),
        readiness=ReadinessSummary(
            "ready",
            "content-free fixture",
            "available",
            "echo",
            "available",
            None,
            "one_shot",
            (),
        ),
    )

    class _FixtureClient:
        async def load(
            self,
            workspace: str | None,
            *,
            selected_session_id: str | None = None,
        ) -> NavigationSnapshot:
            del workspace, selected_session_id
            return snapshot

    app = WorkbenchTui(_FixtureClient(), workspace="/tmp/fixture")  # type: ignore[arg-type]
    started = time.perf_counter_ns()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        startup_ms = _elapsed_ms(started)
        composer = app.query_one("#composer", Input)
        composer.focus()
        started = time.perf_counter_ns()
        await pilot.press("x")
        await pilot.pause()
        first_input_ms = _elapsed_ms(started)
        started = time.perf_counter_ns()
        app.query_one("#status").update("content-free event")
        await pilot.pause()
        event_ms = _elapsed_ms(started)
    return {
        "startup_to_paint": startup_ms,
        "keypress_to_paint": first_input_ms,
        "event_to_paint": event_ms,
    }


def _probe_worker_runtime(root: Path) -> Mapping[str, float]:
    from gpt2giga_harness.runtime.store import RuntimeCoordinationStore

    store = RuntimeCoordinationStore(root / f"runtime-{time.perf_counter_ns()}")
    fingerprint: dict[str, Any] = {}
    store.register_worker(
        worker_id="fixture-worker",
        process_id=os.getpid(),
        hostname="fixture",
        capability_fingerprint=fingerprint,
    )
    started = time.perf_counter_ns()
    submission = store.submit_job(
        session_id="fixture-session",
        user_message_id="fixture-message",
        idempotency_key="fixture-key",
    )
    submit_ms = _elapsed_ms(started)
    started = time.perf_counter_ns()
    claimed = store.claim_next_job(
        worker_id="fixture-worker",
        capability_fingerprint=fingerprint,
        lease_seconds=15,
    )
    claim_ms = _elapsed_ms(started)
    assert claimed is not None
    started = time.perf_counter_ns()
    store.request_cancel(submission.job.id)
    cancel_ms = _elapsed_ms(started)
    return {
        "queue_submit": submit_ms,
        "queue_claim": claim_ms,
        "cancellation_request": cancel_ms,
    }


def _probe_web_api(root: Path) -> Mapping[str, float]:
    from fastapi.testclient import TestClient

    started = time.perf_counter_ns()
    config = HarnessConfig(data_dir=root / "api")
    app = create_app(
        config,
        registry=create_default_registry(include_entry_points=False),
    )
    setup_ms = _elapsed_ms(started)
    started = time.perf_counter_ns()
    response = TestClient(app).get("/api/defaults")
    response.raise_for_status()
    return {"app_setup": setup_ms, "request": _elapsed_ms(started)}


def _elapsed_ms(started_ns: int) -> float:
    return (time.perf_counter_ns() - started_ns) / 1_000_000


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    rank = (len(values) - 1) * percentile / 100
    lower = int(rank)
    upper = min(lower + 1, len(values) - 1)
    weight = rank - lower
    return round(values[lower] * (1 - weight) + values[upper] * weight, 3)


def _resource_usage() -> tuple[int, int, int]:
    if resource is None:
        return (0, 0, 0)
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return (
        _rss_bytes(usage.ru_maxrss),
        int(usage.ru_inblock),
        int(usage.ru_oublock),
    )


def _rss_bytes(raw_maxrss: int | float) -> int:
    # macOS reports bytes; Linux and other common Unix platforms report KiB.
    return int(raw_maxrss if sys.platform == "darwin" else raw_maxrss * 1024)
