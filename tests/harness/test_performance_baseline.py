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
