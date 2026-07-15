import json
import shutil
import subprocess
from pathlib import Path

import pytest

from gpt2giga_harness.cli import main


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEMO_SOURCE = REPOSITORY_ROOT / "examples" / "harness" / "first-run-demo"


def test_first_run_demo_initializes_and_runs_offline(tmp_path, monkeypatch, capsys):
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not installed")
    workspace = tmp_path / "inventory-demo"
    shutil.copytree(DEMO_SOURCE, workspace)
    subprocess.run((git, "init", "-b", "main"), cwd=workspace, check=True)
    monkeypatch.setenv(
        "GPT2GIGA_HARNESS_DATA_DIR",
        str(workspace / ".local" / "harness"),
    )

    assert not (DEMO_SOURCE / ".giga").exists()
    assert (
        main(
            [
                "init",
                "--workspace",
                str(workspace),
                "--name",
                "harness-first-run-demo",
                "--json",
            ]
        )
        == 0
    )
    initialized = json.loads(capsys.readouterr().out)
    assert initialized["project"]["name"] == "harness-first-run-demo"
    assert initialized["config"]["exists"] is True
    assert (workspace / ".giga" / "evals" / "smoke.yaml").exists()

    assert (
        main(
            [
                "harness",
                "run",
                "echo",
                "--no-start-proxy",
                "--workspace",
                str(workspace),
                "--mode",
                "read",
                "--prompt",
                "Summarize the fictional inventory task",
                "--json",
            ]
        )
        == 0
    )
    echo_run = json.loads(capsys.readouterr().out)
    assert echo_run["ok"] is True
    assert echo_run["text"] == "Summarize the fictional inventory task"
    assert echo_run["raw"]["mode"] == "read"

    assert (
        main(
            [
                "eval",
                "run",
                "smoke",
                "--no-start-proxy",
                "--workspace",
                str(workspace),
                "--harness",
                "echo",
                "--json",
            ]
        )
        == 0
    )
    smoke_eval = json.loads(capsys.readouterr().out)
    assert smoke_eval["status"] == "passed"
    assert smoke_eval["harness_ids"] == ["echo"]
    assert smoke_eval["summary"]["total"] == 2
    assert smoke_eval["summary"]["passed"] == 2
    assert smoke_eval["summary"]["failed"] == 0
    assert smoke_eval["summary"]["errors"] == 0
    assert smoke_eval["summary"]["score"] == 1.0
    assert not (DEMO_SOURCE / ".local").exists()
