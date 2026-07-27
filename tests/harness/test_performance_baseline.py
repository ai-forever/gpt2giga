from __future__ import annotations

import json
import stat
import subprocess
import sys

import pytest

from gpt2giga_harness import cli
from gpt2giga_harness.performance_baseline import (
    CI_SMOKE_BUDGETS_MS,
    FIXTURE_SET_VERSION,
    REQUIRED_WORKLOADS,
    SCHEMA_VERSION,
    run_performance_baseline,
)


def test_cli_import_does_not_load_testclient_backend():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys, warnings; "
                "from starlette.exceptions import StarletteDeprecationWarning; "
                "warnings.simplefilter('error', StarletteDeprecationWarning); "
                "import gpt2giga_harness.cli; "
                "assert 'fastapi.testclient' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_performance_baseline_imports_without_posix_resource_module():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys\n"
                "class BlockResource:\n"
                "    def find_spec(self, fullname, path=None, target=None):\n"
                "        if fullname == 'resource':\n"
                "            raise ModuleNotFoundError(fullname)\n"
                "        return None\n"
                "sys.meta_path.insert(0, BlockResource()); "
                "from gpt2giga_harness import performance_baseline as baseline; "
                "sample = baseline._measure(lambda: {}); "
                "assert sample.rss_bytes == 0; "
                "assert sample.input_blocks == 0; "
                "assert sample.output_blocks == 0"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_performance_baseline_is_bounded_content_free_and_machine_readable():
    report = run_performance_baseline(samples=2)

    assert report["schema_version"] == SCHEMA_VERSION
    assert report["fixture_set_version"] == FIXTURE_SET_VERSION
    assert report["samples_per_probe"] == 2
    assert report["privacy"] == {
        "content_captured": False,
        "secrets_captured": False,
        "native_homes_accessed": False,
        "provider_traffic": False,
        "temporary_state_only": True,
    }
    assert report["measurement_contract"]["required_workloads"] == list(
        REQUIRED_WORKLOADS
    )
    assert {result["id"] for result in report["results"]} == set(CI_SMOKE_BUDGETS_MS)
    for result in report["results"]:
        assert set(result["percentiles_ms"]) == {"p50", "p95", "p99"}
        assert result["io"]["io_wait_ms"] is None
        assert result["optimization_target_ms"] is None
        assert "samples" not in result


def test_local_detail_profile_keeps_bounded_content_free_samples():
    report = run_performance_baseline(samples=1, profile="local-detail")

    for result in report["results"]:
        assert len(result["samples"]) == 1
        assert set(result["samples"][0]) == {
            "wall_ms",
            "cpu_ms",
            "rss_bytes",
            "input_blocks",
            "output_blocks",
            "stages_ms",
        }


def test_tui_detail_profile_is_ranked_bounded_and_content_free():
    report = run_performance_baseline(samples=1, profile="tui-detail")

    assert report["schema_version"] == "gigaloom.tui-performance-profile.v2"
    assert report["fixture_set_version"] == "g5-02.v1"
    assert report["status"] == "passed"
    assert report["privacy"] == {
        "content_captured": False,
        "secrets_captured": False,
        "native_homes_accessed": False,
        "provider_traffic": False,
        "network_accessed": False,
        "temporary_state_only": True,
    }
    assert (
        report["current_contract"]["timeline_render_strategy"]
        == "stable_event_card_cache"
    )
    assert report["current_contract"]["run_poll_rerenders_unchanged_snapshot"] is False
    assert report["current_contract"]["run_delivery"].startswith(
        "persistent_event_stream"
    )
    assert report["current_contract"]["native_delivery"].startswith(
        "persistent_event_stream"
    )
    assert report["retention"]["max_retained_events_observed"] == 100
    assert {item["id"] for item in report["accepted_repairs"]} == {
        "event_driven_run_delivery",
        "event_driven_native_output",
        "differential_timeline_rendering",
        "lazy_tui_startup",
    }
    assert set(report["implemented_repairs"]) == {
        "event_driven_run_delivery",
        "event_driven_native_output",
        "unchanged_snapshot_suppression",
        "differential_timeline_rendering",
        "lazy_tui_startup",
    }
    metrics = {item["id"] for item in report["results"]}
    assert {
        "cold_tui_import",
        "startup_to_paint",
        "first_input_to_paint",
        "timeline_full_100_projection",
        "timeline_incremental_1_projection",
        "unchanged_run_poll_projection",
        "timeline_retained_memory",
        "run_timer_wakeup_rate",
        "run_active_request_rate",
        "native_active_request_rate",
    } <= metrics
    by_metric = {item["id"]: item for item in report["results"]}
    for metric in (
        "cold_tui_import",
        "startup_to_paint",
        "first_input_to_paint",
        "timeline_full_100_projection",
        "timeline_incremental_1_projection",
        "unchanged_run_poll_projection",
        "run_timer_wakeup_rate",
        "run_active_request_rate",
        "native_active_request_rate",
    ):
        assert by_metric[metric]["target_status"] == "within_target"
    assert report["startup_imports"]["module_count_p95"] > 0
    assert [item["rank"] for item in report["ranked_bottlenecks"]] == list(
        range(1, len(report["ranked_bottlenecks"]) + 1)
    )
    assert report["profile_top"]


@pytest.mark.parametrize("samples", (0, 101))
def test_performance_baseline_rejects_unbounded_sample_counts(samples):
    with pytest.raises(ValueError, match="samples must be between 1 and 100"):
        run_performance_baseline(samples=samples)


def test_performance_cli_writes_private_report(tmp_path, capsys):
    output = tmp_path / "report.json"

    assert (
        cli.main(
            [
                "benchmark",
                "performance",
                "--samples",
                "1",
                "--output",
                str(output),
            ]
        )
        == 0
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == SCHEMA_VERSION
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert "Wrote private performance report" in capsys.readouterr().out


def test_performance_cli_writes_private_tui_profile(tmp_path, capsys):
    output = tmp_path / "tui-report.json"

    assert (
        cli.main(
            [
                "benchmark",
                "performance",
                "--profile",
                "tui-detail",
                "--samples",
                "1",
                "--output",
                str(output),
            ]
        )
        == 0
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "gigaloom.tui-performance-profile.v2"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert "Wrote private performance report" in capsys.readouterr().out
