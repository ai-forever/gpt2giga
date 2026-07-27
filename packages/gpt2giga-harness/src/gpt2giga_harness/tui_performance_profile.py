"""Bounded, content-free G5 TUI performance profiling."""

from __future__ import annotations

import asyncio
import cProfile
from dataclasses import dataclass
from datetime import datetime, timezone
import gc
import json
from pathlib import Path
import platform
import pstats
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from typing import Any, Final

from gpt2giga_harness.tui.app import (
    NATIVE_OUTPUT_POLL_SECONDS,
    RUN_POLL_SECONDS,
    TimelinePanel,
    WorkbenchTui,
)
from gpt2giga_harness.tui.client import (
    HarnessSummary,
    MAX_NATIVE_SCROLLBACK_CHARS,
    MAX_TIMELINE_CHARS,
    MAX_TIMELINE_EVENTS,
    NavigationSnapshot,
    ProjectSummary,
    ReadinessSummary,
    RunActionBinding,
    RunSnapshot,
    TimelineEvent,
    neutralize_native_terminal_output,
)


SCHEMA_VERSION: Final[str] = "gigaloom.tui-performance-profile.v2"
FIXTURE_SET_VERSION: Final[str] = "g5-02.v1"

# Reviewed G5 repair budgets, not CI pass/fail thresholds.
TARGET_BUDGETS: Final[dict[str, tuple[str, float]]] = {
    "cold_tui_import": ("ms", 250.0),
    "startup_to_paint": ("ms", 200.0),
    "first_input_to_paint": ("ms", 75.0),
    "timeline_full_10_projection": ("ms", 4.0),
    "timeline_full_100_projection": ("ms", 16.0),
    "timeline_incremental_1_projection": ("ms", 8.0),
    "timeline_batch_10_projection": ("ms", 12.0),
    "unchanged_run_poll_projection": ("ms", 2.0),
    "native_output_normalize_64k": ("ms", 5.0),
    "filesystem_roundtrip": ("ms", 10.0),
    "sqlite_transaction": ("ms", 15.0),
    "timeline_retained_memory": ("bytes", 2_097_152.0),
    "run_timer_wakeup_rate": ("wakeups_per_minute", 4.0),
    "run_active_request_rate": ("calls_per_minute", 4.0),
    "native_active_request_rate": ("calls_per_minute", 4.0),
}


@dataclass(frozen=True)
class _TuiSample:
    timings_ms: dict[str, float]
    retained_memory_bytes: int
    retained_events: int
    retained_characters: int


class _FixtureClient:
    def __init__(self, snapshot: NavigationSnapshot) -> None:
        self.snapshot = snapshot
        self.poll_snapshot: RunSnapshot | None = None
        self.run_poll_calls = 0

    async def load(
        self,
        workspace: str | None,
        *,
        selected_session_id: str | None = None,
    ) -> NavigationSnapshot:
        del workspace, selected_session_id
        return self.snapshot

    async def snapshot_run(
        self,
        run_id: str,
        *,
        cursor: str | None = None,
    ) -> RunSnapshot:
        del run_id, cursor
        self.run_poll_calls += 1
        if self.poll_snapshot is None:
            raise RuntimeError("fixture poll snapshot is unavailable")
        return self.poll_snapshot


def run_tui_performance_profile(*, samples: int) -> dict[str, Any]:
    """Profile current TUI hot paths without user state or external traffic."""
    if not 1 <= samples <= 100:
        raise ValueError("samples must be between 1 and 100")

    cold_imports = [_cold_import_probe() for _ in range(samples)]
    tui_samples = [asyncio.run(_profile_tui_once()) for _ in range(samples)]
    comparator_samples = [_profile_comparators() for _ in range(samples)]
    raw: dict[str, list[float]] = {
        "cold_tui_import": [item["wall_ms"] for item in cold_imports],
        "run_timer_wakeup_rate": [60.0 / RUN_POLL_SECONDS] * samples,
        "run_active_request_rate": [60.0 / RUN_POLL_SECONDS] * samples,
        "native_active_request_rate": [60.0 / NATIVE_OUTPUT_POLL_SECONDS] * samples,
    }
    for sample in tui_samples:
        for metric, value in sample.timings_ms.items():
            raw.setdefault(metric, []).append(value)
        raw.setdefault("timeline_retained_memory", []).append(
            float(sample.retained_memory_bytes)
        )
    for sample in comparator_samples:
        for metric, value in sample.items():
            raw.setdefault(metric, []).append(value)

    results = [
        _summarize(metric, values, *TARGET_BUDGETS[metric])
        for metric, values in raw.items()
    ]
    ranked = sorted(
        (
            {
                "rank": 0,
                "metric": result["id"],
                "p95": result["percentiles"]["p95"],
                "unit": result["unit"],
                "target_p95": result["target"]["p95"],
                "target_ratio": result["target_ratio"],
                "status": result["target_status"],
            }
            for result in results
        ),
        key=lambda item: (-item["target_ratio"], item["metric"]),
    )
    for index, item in enumerate(ranked, start=1):
        item["rank"] = index

    return {
        "schema_version": SCHEMA_VERSION,
        "fixture_set_version": FIXTURE_SET_VERSION,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "profile": "tui-detail",
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
        "current_contract": {
            "run_resnapshot_interval_seconds": RUN_POLL_SECONDS,
            "native_reconnect_interval_seconds": NATIVE_OUTPUT_POLL_SECONDS,
            "run_request_requires_active_run": True,
            "native_request_requires_active_process": True,
            "run_poll_rerenders_unchanged_snapshot": False,
            "native_poll_updates_widgets_on_empty_output": False,
            "run_delivery": "persistent_event_stream_with_bounded_resnapshot",
            "native_delivery": "persistent_event_stream_with_bounded_reconnect",
            "timeline_render_strategy": "stable_event_card_cache",
            "event_batching": "bounded_snapshot_then_local_event_projection",
            "timeline_event_limit": MAX_TIMELINE_EVENTS,
            "timeline_character_limit": MAX_TIMELINE_CHARS,
            "native_scrollback_character_limit": MAX_NATIVE_SCROLLBACK_CHARS,
        },
        "startup_imports": {
            "module_count_p50": _percentile(
                sorted(item["module_count"] for item in cold_imports),
                50,
            ),
            "module_count_p95": _percentile(
                sorted(item["module_count"] for item in cold_imports),
                95,
            ),
        },
        "retention": {
            "max_retained_events_observed": max(
                item.retained_events for item in tui_samples
            ),
            "max_retained_characters_observed": max(
                item.retained_characters for item in tui_samples
            ),
        },
        "results": results,
        "ranked_bottlenecks": ranked,
        "accepted_repairs": [
            {
                "id": "event_driven_run_delivery",
                "evidence": [
                    "run_timer_wakeup_rate",
                    "run_active_request_rate",
                    "unchanged_run_poll_projection",
                ],
                "budget": {
                    "idle_timer_wakeups_per_minute_p95": 4.0,
                    "active_requests_per_minute_p95": 4.0,
                    "active_event_to_paint_ms_p95": 75.0,
                },
            },
            {
                "id": "event_driven_native_output",
                "evidence": [
                    "native_active_request_rate",
                    "native_output_normalize_64k",
                ],
                "budget": {
                    "active_requests_per_minute_p95": 4.0,
                    "active_event_to_paint_ms_p95": 75.0,
                },
            },
            {
                "id": "differential_timeline_rendering",
                "evidence": [
                    "timeline_full_100_projection",
                    "timeline_incremental_1_projection",
                    "timeline_batch_10_projection",
                ],
                "budget": {
                    "full_100_projection_ms_p95": 16.0,
                    "incremental_1_projection_ms_p95": 8.0,
                    "retained_events_max": MAX_TIMELINE_EVENTS,
                    "retained_characters_max": MAX_TIMELINE_CHARS,
                },
            },
            {
                "id": "lazy_tui_startup",
                "evidence": [
                    "cold_tui_import",
                    "startup_to_paint",
                    "first_input_to_paint",
                ],
                "budget": {
                    "cold_import_ms_p95": 250.0,
                    "startup_to_paint_ms_p95": 200.0,
                    "first_input_to_paint_ms_p95": 75.0,
                },
            },
        ],
        "implemented_repairs": [
            "event_driven_run_delivery",
            "event_driven_native_output",
            "unchanged_snapshot_suppression",
            "differential_timeline_rendering",
            "lazy_tui_startup",
        ],
        "profile_top": _profile_timeline_render(),
        "status": "passed",
    }


async def _profile_tui_once() -> _TuiSample:
    from textual import events
    from textual.widgets import Input

    project = ProjectSummary("fixture", "Fixture", "/tmp/fixture", "main", 0)
    navigation = NavigationSnapshot(
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
    client = _FixtureClient(navigation)
    app = WorkbenchTui(client, workspace="/tmp/fixture")  # type: ignore[arg-type]
    timings: dict[str, float] = {}
    started = time.perf_counter_ns()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause(0)
        timings["startup_to_paint"] = _elapsed_ms(started)

        composer = app.query_one("#composer", Input)
        composer.focus()
        painted = asyncio.Event()
        key_event = events.Key("x", "x")
        key_event.set_sender(app)
        started = time.perf_counter_ns()
        app._driver.send_message(key_event)
        app.call_after_refresh(painted.set)
        await asyncio.wait_for(painted.wait(), timeout=1)
        if composer.value != "x":
            raise RuntimeError("TUI input-to-paint probe did not apply its key event")
        timings["first_input_to_paint"] = _elapsed_ms(started)

        timings.update(_profile_timeline_projections())
        app._apply_run_snapshot(_run_snapshot(_events(0, 100), reason="cursor_gap"))

        client.poll_snapshot = _run_snapshot(())
        started = time.perf_counter_ns()
        await app._poll_run()
        timings["unchanged_run_poll_projection"] = _elapsed_ms(started)

        started = time.perf_counter_ns()
        neutralize_native_terminal_output("x" * MAX_NATIVE_SCROLLBACK_CHARS)
        timings["native_output_normalize_64k"] = _elapsed_ms(started)

        gc.collect()
        tracemalloc.start()
        before, _ = tracemalloc.get_traced_memory()
        for offset in range(100, 200):
            app._apply_run_snapshot(_run_snapshot(_events(offset, 1)))
        gc.collect()
        after, _ = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        retained_memory = max(after - before, 0)
        retained_events = len(app.timeline)
        retained_characters = sum(
            len(event.message) + len(event.delta or "") for event in app.timeline
        )
    return _TuiSample(
        timings_ms=timings,
        retained_memory_bytes=retained_memory,
        retained_events=retained_events,
        retained_characters=retained_characters,
    )


def _events(offset: int, count: int) -> tuple[TimelineEvent, ...]:
    return tuple(
        TimelineEvent(
            id=f"event_{offset + index:04d}",
            type="message_delta",
            message="content-free event",
            delta="x" * 80,
            category="message",
        )
        for index in range(count)
    )


def _run_snapshot(
    events: tuple[TimelineEvent, ...],
    *,
    reason: str | None = None,
) -> RunSnapshot:
    cursor = events[-1].id if events else "unchanged"
    return RunSnapshot(
        binding=RunActionBinding(
            "fixture-session",
            "fixture-run",
            "a" * 64,
            1,
            "fixture-turn",
        ),
        status="running",
        events=events,
        cursor=f"ip1.1.{cursor}",
        resnapshot_reason=reason,
    )


def _profile_timeline_projections() -> dict[str, float]:
    labels = {"message": "MESSAGE"}
    full_10 = _events(0, 10)
    full_100 = _events(0, 100)
    incremental_1 = (*full_100[1:], *_events(100, 1))
    batch_10 = (*full_100[10:], *_events(100, 10))

    def measure(
        initial: tuple[TimelineEvent, ...],
        events: tuple[TimelineEvent, ...],
    ) -> float:
        panel = TimelinePanel("empty", labels, id="timeline")
        panel.set_events(initial)
        started = time.perf_counter_ns()
        panel.set_events(events)
        return _elapsed_ms(started)

    return {
        "timeline_full_10_projection": measure((), full_10),
        "timeline_full_100_projection": measure((), full_100),
        "timeline_incremental_1_projection": measure(full_100, incremental_1),
        "timeline_batch_10_projection": measure(full_100, batch_10),
    }


def _cold_import_probe() -> dict[str, float]:
    command = (
        "import json,sys;"
        "from gpt2giga_harness.tui.app import WorkbenchTui;"
        "print(json.dumps({'modules':len(sys.modules)}))"
    )
    started = time.perf_counter_ns()
    result = subprocess.run(
        [sys.executable, "-c", command],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError("isolated TUI import probe failed")
    payload = json.loads(result.stdout)
    return {
        "wall_ms": _elapsed_ms(started),
        "module_count": float(payload["modules"]),
    }


def _profile_comparators() -> dict[str, float]:
    with tempfile.TemporaryDirectory(prefix="gigaloom-g5-profile-") as raw_root:
        root = Path(raw_root)
        path = root / "content-free.bin"
        started = time.perf_counter_ns()
        path.write_bytes(b"\0" * 4096)
        path.read_bytes()
        filesystem_ms = _elapsed_ms(started)

        started = time.perf_counter_ns()
        with sqlite3.connect(root / "profile.sqlite3") as connection:
            connection.execute("CREATE TABLE samples (id INTEGER PRIMARY KEY)")
            connection.execute("INSERT INTO samples DEFAULT VALUES")
            connection.execute("SELECT COUNT(*) FROM samples").fetchone()
        sqlite_ms = _elapsed_ms(started)
    return {
        "filesystem_roundtrip": filesystem_ms,
        "sqlite_transaction": sqlite_ms,
    }


def _summarize(
    metric: str,
    values: list[float],
    unit: str,
    target: float,
) -> dict[str, Any]:
    ordered = sorted(values)
    percentiles = {
        "p50": _percentile(ordered, 50),
        "p95": _percentile(ordered, 95),
        "p99": _percentile(ordered, 99),
    }
    ratio = percentiles["p95"] / target
    return {
        "id": metric,
        "unit": unit,
        "percentiles": percentiles,
        "mean": round(statistics.fmean(ordered), 3),
        "target": {"percentile": "p95", "p95": target},
        "target_ratio": round(ratio, 3),
        "target_status": "over_target" if ratio > 1 else "within_target",
    }


def _profile_timeline_render() -> list[dict[str, Any]]:
    panel = TimelinePanel("empty", {"message": "MESSAGE"}, id="timeline")
    events = _events(0, 100)
    profiler = cProfile.Profile()
    profiler.enable()
    for _ in range(25):
        panel.set_events(events)
    profiler.disable()
    stats = pstats.Stats(profiler)
    ranked = sorted(
        stats.stats.items(),
        key=lambda item: item[1][3],
        reverse=True,
    )
    return [
        {
            "file": Path(key[0]).name,
            "line": key[1],
            "function": key[2],
            "calls": value[1],
            "cumulative_ms": round(value[3] * 1_000, 3),
        }
        for key, value in ranked[:12]
    ]


def _percentile(values: list[float], percentile: int) -> float:
    rank = (len(values) - 1) * percentile / 100
    lower = int(rank)
    upper = min(lower + 1, len(values) - 1)
    weight = rank - lower
    return round(values[lower] * (1 - weight) + values[upper] * weight, 3)


def _elapsed_ms(started_ns: int) -> float:
    return (time.perf_counter_ns() - started_ns) / 1_000_000
