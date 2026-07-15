from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "harness_p0_comparison.py"
FIXTURE_PATH = REPO_ROOT / "benchmarks" / "harness_p0" / "fixture"


def _load_script():
    spec = importlib.util.spec_from_file_location("harness_p0_comparison", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


comparison = _load_script()


def _run(*argv: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        (sys.executable, *argv),
        cwd=cwd or REPO_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def test_frozen_manifest_matches_fixture_and_comparison_contract() -> None:
    summary = comparison.validate_manifest()
    manifest = comparison._load_json(comparison.DEFAULT_MANIFEST)
    targets = {item["id"]: item for item in manifest["targets"]}

    assert summary == {
        "comparison_id": "harness-omnigent-p0-2026-07-14-v1",
        "fixture_archive_sha256": "11e42c70954db1e9e0998c3e7b1a94e041044ac2a4d7032748230c273dbff3e6",
        "fixture_seed_git_sha": "2ca1e6332dde5dd065043b073634824ec1f40af5",
        "targets": ["harness", "omnigent"],
        "workflows": 5,
        "semantic_cells": 25,
        "execution_cells": 30,
        "live_execution_started": False,
    }
    assert targets["harness"]["source"]["commit"] == (
        "6680aee9a7a231821887826774c475089b01c3f6"
    )
    assert targets["omnigent"]["source"] == {
        "url": "https://github.com/omnigent-ai/omnigent",
        "release_url": "https://github.com/omnigent-ai/omnigent/releases/tag/v0.5.1",
        "tag": "v0.5.1",
        "commit": "08285468e098244ac0b0bf98cb470d5c1a1a7070",
    }
    assert targets["omnigent"]["install"]["sha256"] == (
        "b3041397cc3243febf6301c4ff3216779d48f56ec4e5f6fea29ba6031c2b513b"
    )


def test_seed_fixture_is_offline_clean_and_contains_the_boundary_defect(
    tmp_path,
) -> None:
    workspace = tmp_path / "fixture"
    seed_sha = comparison.initialize_fixture_repo(FIXTURE_PATH, workspace)

    tests = _run("-m", "unittest", "discover", "-s", "tests", "-v", cwd=workspace)
    read_only = _run(
        "benchmark/verify.py",
        "read-only-analysis",
        "--seed-sha",
        seed_sha,
        cwd=workspace,
    )
    patch = _run("benchmark/verify.py", "isolated-reviewed-patch", cwd=workspace)

    assert tests.returncode == 0, tests.stderr
    assert read_only.returncode == 0, read_only.stderr
    assert json.loads(read_only.stdout)["passed"] is True
    assert patch.returncode == 1
    assert json.loads(patch.stdout)["passed"] is False
    assert (
        _run(
            "-c",
            "from src.inventory import reserve_stock; reserve_stock(5, 5)",
            cwd=workspace,
        ).returncode
        != 0
    )


def test_side_effect_token_is_recorded_once_with_distinct_duplicate_exit(
    tmp_path,
) -> None:
    workspace = tmp_path / "fixture"
    comparison.initialize_fixture_repo(FIXTURE_PATH, workspace)

    first = _run("benchmark/side_effect.py", "recovery-token-1", cwd=workspace)
    duplicate = _run("benchmark/side_effect.py", "recovery-token-1", cwd=workspace)
    verify = _run(
        "benchmark/verify.py",
        "restart-recovery",
        "--token",
        "recovery-token-1",
        cwd=workspace,
    )

    assert first.returncode == 0
    assert duplicate.returncode == 17
    assert json.loads(duplicate.stdout)["status"] == "duplicate"
    assert verify.returncode == 0
    assert json.loads(verify.stdout)["checks"]["ledger_entries"] == 1


def test_prepare_cell_never_executes_target_and_refuses_existing_destination(
    tmp_path,
) -> None:
    destination = tmp_path / "cell"

    cell = comparison.prepare_cell(
        comparison.DEFAULT_MANIFEST,
        destination,
        target_id="omnigent",
        workflow_id="policy-refusal-bypass",
        repetition=2,
    )

    assert cell["cell_id"] == "omnigent-policy-refusal-bypass-r2"
    assert cell["live_execution_started"] is False
    assert cell["target"]["version"] == "0.5.1"
    assert cell["input"]["fixture_sha256"] == comparison._sha256_file(
        destination / "input" / "fixture.zip"
    )
    assert (
        _run(
            "-c",
            "import subprocess; print(subprocess.check_output(['git', 'status', '--short'], text=True))",
            cwd=destination / "workspace",
        ).stdout.strip()
        == ""
    )
    with pytest.raises(comparison.ComparisonContractError, match="already exists"):
        comparison.prepare_cell(
            comparison.DEFAULT_MANIFEST,
            destination,
            target_id="omnigent",
            workflow_id="policy-refusal-bypass",
            repetition=2,
        )


def test_result_validator_checks_semantics_artifacts_redaction_and_hashes(
    tmp_path,
) -> None:
    destination = tmp_path / "cell"
    cell = comparison.prepare_cell(
        comparison.DEFAULT_MANIFEST,
        destination,
        target_id="harness",
        workflow_id="read-only-analysis",
        repetition=1,
    )
    artifact_path = destination / "evidence" / "artifacts" / "analysis.md"
    artifact_path.write_text("Boundary evidence.\n", encoding="utf-8")
    artifact = comparison.build_artifact_entry(
        destination / "evidence",
        artifact_path,
        artifact_type="analysis",
        producer="harness",
        created_at="2026-07-14T12:00:00Z",
    )
    result = {
        "schema_version": 1,
        "comparison_id": cell["comparison_id"],
        "cell_id": cell["cell_id"],
        "target": cell["target"],
        "environment": cell["environment"],
        "input": cell["input"],
        "timestamps": {
            "started_at": "2026-07-14T12:00:00Z",
            "finished_at": "2026-07-14T12:00:01Z",
            "monotonic_duration_seconds": 1.0,
        },
        "status": "passed",
        "failure": None,
        "semantic_cells": [
            {
                "id": semantic_id,
                "status": "passed",
                "reason_code": None,
                "evidence_refs": [artifact["path"]],
            }
            for semantic_id in sorted(comparison.WORKFLOW_CELLS["read-only-analysis"])
        ],
        "artifacts": [artifact],
        "metrics": {"duration_seconds": 1.0},
        "redaction": {
            "content_capture_enabled": False,
            "secret_scan_passed": True,
            "canary_found": None,
        },
        "reproduction": {
            "commands": [["python", "benchmark/verify.py", "read-only-analysis"]]
        },
    }
    result_path = destination / "evidence" / "result.json"
    result_path.write_text(json.dumps(result), encoding="utf-8")

    assert comparison.validate_result(destination)["valid"] is True

    artifact_path.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(comparison.ComparisonContractError, match="digest or size"):
        comparison.validate_result(destination)


def test_artifact_entry_rejects_path_escape(tmp_path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")

    with pytest.raises(comparison.ComparisonContractError, match="escapes"):
        comparison.build_artifact_entry(
            evidence,
            outside,
            artifact_type="log",
            producer="collector",
            created_at="2026-07-14T12:00:00Z",
        )
