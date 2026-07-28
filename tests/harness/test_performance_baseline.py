from __future__ import annotations

import json
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from gpt2giga_harness import cli
from gpt2giga_harness.performance_baseline import (
    CI_SMOKE_BUDGETS_MS,
    DETAIL_REFERENCE_BUDGETS_MS,
    FIXTURE_SET_VERSION,
    REGRESSION_BASELINE_ID,
    REPORT_ARTIFACT_MAX_BYTES,
    REPORT_RETENTION_DAYS,
    REQUIRED_WORKLOADS,
    SCHEMA_VERSION,
    run_performance_baseline,
    write_performance_report,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _assert_g6_03_report_contract(report, *, profile):
    assert report["baseline"] == {
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
    assert report["artifact_policy"] == {
        "max_bytes": REPORT_ARTIFACT_MAX_BYTES[profile],
        "retention_days": REPORT_RETENTION_DAYS[profile],
        "bounded_samples_max": 100,
        "content_free": True,
    }
    fingerprint = report["environment"]["fingerprint"]
    assert fingerprint["algorithm"] == "sha256"
    assert len(fingerprint["value"]) == 64
    assert fingerprint["fields"] == sorted(fingerprint["fields"])
    assert "sqlite" in fingerprint["fields"]


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

    _assert_g6_03_report_contract(report, profile="ci-smoke")
    assert report["schema_version"] == SCHEMA_VERSION
    assert report["fixture_set_version"] == FIXTURE_SET_VERSION
    assert report["samples_per_probe"] == 2
    assert report["privacy"] == {
        "content_captured": False,
        "secrets_captured": False,
        "native_homes_accessed": False,
        "provider_traffic": False,
        "network_accessed": False,
        "temporary_state_only": True,
    }
    assert report["measurement_contract"]["required_workloads"] == list(
        REQUIRED_WORKLOADS
    )
    assert {result["id"] for result in report["results"]} == set(CI_SMOKE_BUDGETS_MS)
    for result in report["results"]:
        assert set(result["percentiles_ms"]) == {"p50", "p95", "p99"}
        assert result["regression_gate"]["blocking"] is True
        assert result["regression_gate"]["classification"] == "environment_stable_ci"
        assert result["io"]["io_wait_ms"] is None
        assert result["optimization_target_ms"] is None
        assert "samples" not in result
    assert (
        report["measurement_contract"][
            "provider_or_external_network_latency_is_blocking"
        ]
        is False
    )


def test_local_detail_profile_keeps_bounded_content_free_samples():
    report = run_performance_baseline(samples=1, profile="local-detail")

    _assert_g6_03_report_contract(report, profile="local-detail")
    assert {result["id"] for result in report["results"]} == set(
        DETAIL_REFERENCE_BUDGETS_MS
    )
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
        if result["id"] not in CI_SMOKE_BUDGETS_MS:
            assert result["regression_gate"] == {
                "blocking": False,
                "classification": "scheduled_or_opt_in_detail",
                "budget_ms": {
                    "percentile": "p95",
                    "p95": DETAIL_REFERENCE_BUDGETS_MS[result["id"]],
                },
            }


def test_tui_detail_profile_is_ranked_bounded_and_content_free():
    report = run_performance_baseline(samples=1, profile="tui-detail")

    _assert_g6_03_report_contract(report, profile="tui-detail")
    assert report["schema_version"] == "gigaloom.tui-performance-profile.v3"
    assert report["fixture_set_version"] == "g5-03.v1"
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
    assert report["closure_workloads"] == {
        "cold_start": {
            "samples": 1,
            "evidence": ["cold_tui_import"],
        },
        "warm_start": {
            "samples": 1,
            "evidence": ["startup_to_paint", "first_input_to_paint"],
        },
        "long_session": {
            "retained_event_limit": 100,
            "retained_character_limit": 65_536,
            "evidence": [
                "timeline_full_100_projection",
                "timeline_incremental_1_projection",
                "timeline_batch_10_projection",
                "timeline_retained_memory",
            ],
        },
    }
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
        assert by_metric[metric]["target_status"] in {
            "within_target",
            "over_target",
        }
    accepted_metrics = {
        metric for repair in report["accepted_repairs"] for metric in repair["evidence"]
    }
    expected_status = (
        "passed"
        if all(
            by_metric[metric]["target_status"] == "within_target"
            for metric in accepted_metrics
        )
        else "failed"
    )
    assert report["status"] == expected_status
    for metric in (
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


def test_runtime_detail_profile_is_ranked_bounded_and_content_free():
    report = run_performance_baseline(samples=1, profile="runtime-detail")

    _assert_g6_03_report_contract(report, profile="runtime-detail")
    assert report["schema_version"] == "gigaloom.runtime-performance-profile.v3"
    assert report["fixture_set_version"] == "g6-02.v1"
    assert report["privacy"] == {
        "content_captured": False,
        "secrets_captured": False,
        "native_homes_accessed": False,
        "provider_traffic": False,
        "network_accessed": False,
        "temporary_state_only": True,
    }
    assert report["measurement_contract"]["optimization_performed"] is True
    assert report["measurement_contract"]["g6_01_authorized"] is True
    assert report["measurement_contract"]["g6_02_authorized"] is True
    assert report["missing_coverage"] == {}
    assert report["status"] == "passed"
    metrics = {item["id"] for item in report["results"]}
    assert {
        "worker_idle_cycle",
        "worker_idle_loop",
        "worker_wakeup_signal",
        "worker_active_echo",
        "queue_claim_one",
        "queue_claim_many",
        "sqlite_lock_contention",
        "retry_requeue",
        "expired_lease_recovery",
        "api_defaults",
        "api_session_events",
        "sse_terminal_attach",
        "tui_navigation_load",
        "session_run_update",
    } <= metrics
    by_metric = {item["id"]: item for item in report["results"]}
    assert by_metric["worker_active_echo"]["sqlite"]["observed"] is True
    assert by_metric["worker_active_echo"]["sqlite"]["writes"]["p95"] > 0
    assert by_metric["tui_navigation_load"]["sqlite"]["observed"] is False
    assert by_metric["queue_claim_many"]["details"]["claimed_jobs"]["p95"] == 16
    assert by_metric["queue_claim_many"]["details"]["duplicate_claims"]["p95"] == 0
    assert by_metric["worker_idle_loop"]["details"]["cycles"]["p95"] >= 2
    assert (
        by_metric["worker_idle_loop"]["details"]["projected_steady_cycles_per_minute"][
            "p95"
        ]
        <= 65
    )
    assert by_metric["worker_idle_loop"]["target_status"] == "within_target"
    assert by_metric["worker_wakeup_signal"]["target_status"] == "within_target"
    assert by_metric["worker_wakeup_signal"]["details"]["delivered"]["p95"] == 1
    assert by_metric["sse_terminal_attach"]["details"]["frames"]["p95"] >= 1
    assert by_metric["runtime_reconcile"]["details"]["outbox_failed"]["p95"] == 0
    assert by_metric["session_run_update"]["details"]["retained_runs"]["p95"] == 16
    assert by_metric["session_run_update"]["details"]["updated_runs"]["p95"] == 1
    assert [item["rank"] for item in report["ranked_bottlenecks"]] == list(
        range(1, len(report["ranked_bottlenecks"]) + 1)
    )
    assert {item["target_status"] for item in report["results"]} == {
        "within_target",
        "reference_only_not_selected",
    }
    decisions = {item["id"]: item["status"] for item in report["candidate_repairs"]}
    assert decisions == {
        "demand_driven_worker_wakeup": "implemented_within_budget",
        "conflict_aware_worker_concurrency": "not_selected_by_G6-01",
        "ranked_request_hot_path_repairs": (
            "bounded_filesystem_scan_repair_implemented"
        ),
    }


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


@pytest.mark.parametrize(
    ("profile", "ci_blocking_metrics", "expected_exit_code"),
    (
        ("ci-smoke", ["session_projection"], 1),
        ("local-detail", [], 0),
        ("tui-detail", [], 0),
        ("runtime-detail", [], 0),
    ),
)
def test_performance_cli_only_fails_for_ci_blocking_metrics(
    monkeypatch,
    capsys,
    profile,
    ci_blocking_metrics,
    expected_exit_code,
):
    monkeypatch.setattr(
        cli,
        "run_performance_baseline",
        lambda **_kwargs: {
            "status": "failed",
            "baseline": {"ci_blocking_metrics": ci_blocking_metrics},
        },
    )

    assert (
        cli.main(["benchmark", "performance", "--profile", profile])
        == expected_exit_code
    )
    assert '"status": "failed"' in capsys.readouterr().out


def test_performance_report_rejects_artifacts_over_profile_limit(tmp_path):
    output = tmp_path / "oversized.json"
    report = run_performance_baseline(samples=1)
    report["oversized_fixture"] = "x" * REPORT_ARTIFACT_MAX_BYTES["ci-smoke"]

    with pytest.raises(ValueError, match="limit is 65536"):
        write_performance_report(output, report)

    assert not output.exists()


def test_performance_workflows_split_ci_and_detailed_profiles():
    ci = (REPO_ROOT / ".github/workflows/ci.yaml").read_text(encoding="utf-8")
    nightly = (REPO_ROOT / ".github/workflows/nightly-smoke.yaml").read_text(
        encoding="utf-8"
    )

    assert (
        "giga benchmark performance --profile ci-smoke --samples 5 "
        "--output performance-artifacts/ci-smoke.json"
    ) in ci
    assert "retention-days: 7" in ci
    for profile in ("local-detail", "tui-detail", "runtime-detail"):
        assert f"giga benchmark performance --profile {profile}" in nightly
    assert "retention-days: 14" in nightly


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
    assert payload["schema_version"] == "gigaloom.tui-performance-profile.v3"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert "Wrote private performance report" in capsys.readouterr().out


def test_performance_cli_writes_private_runtime_profile(tmp_path, capsys):
    output = tmp_path / "runtime-report.json"

    assert (
        cli.main(
            [
                "benchmark",
                "performance",
                "--profile",
                "runtime-detail",
                "--samples",
                "1",
                "--output",
                str(output),
            ]
        )
        == 0
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "gigaloom.runtime-performance-profile.v3"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert "Wrote private performance report" in capsys.readouterr().out
