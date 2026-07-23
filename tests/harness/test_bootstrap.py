from __future__ import annotations

import json
import stat

import pytest

from gpt2giga_harness import bootstrap, cli
from gpt2giga_harness.bootstrap import (
    BOOTSTRAP_STEP_MANAGED_STATE,
    BOOTSTRAP_STEP_PROJECT,
    BootstrapConflictError,
    BootstrapService,
)
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.completion import SHELLS, render_completion


def _doctor_report():
    return {
        "schema_version": 1,
        "kind": "gpt2giga_harness_doctor_report",
        "ok": True,
        "summary": {"ready": 1, "degraded": 0, "blocked": 0},
        "checks": [
            {
                "id": "support-export",
                "status": "ready",
                "remediation": [
                    {
                        "message": "Export support report.",
                        "command": ("giga doctor --json --output doctor-support.json"),
                    }
                ],
            }
        ],
    }


def test_bootstrap_preview_is_deterministic_and_side_effect_free(
    tmp_path,
    monkeypatch,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_root = tmp_path / "state"
    monkeypatch.setattr(
        bootstrap,
        "build_doctor_report",
        lambda config, *, workspace: _doctor_report(),
    )
    service = BootstrapService(HarnessConfig(data_dir=str(data_root)))

    first = service.preview(workspace=workspace)
    second = service.preview(workspace=workspace)

    assert first == second
    assert first["plan"]["all_reversible_step_ids"] == [
        BOOTSTRAP_STEP_MANAGED_STATE,
        BOOTSTRAP_STEP_PROJECT,
    ]
    assert first["plan"]["automatic_external_effects"] is False
    assert first["plan"]["remedies"][0]["command"].startswith("giga doctor")
    assert not data_root.exists()
    assert not (workspace / ".giga").exists()


def test_bootstrap_applies_all_reversible_steps_and_rolls_them_back(
    tmp_path,
    monkeypatch,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_root = tmp_path / "state"
    monkeypatch.setattr(
        bootstrap,
        "build_doctor_report",
        lambda config, *, workspace: _doctor_report(),
    )
    service = BootstrapService(HarnessConfig(data_dir=str(data_root)))
    preview = service.preview(workspace=workspace)

    applied = service.apply(
        plan_id=preview["plan"]["plan_id"],
        all_reversible=True,
        workspace=workspace,
    )

    assert applied["status"] == "applied"
    assert applied["selected_steps"] == [
        BOOTSTRAP_STEP_MANAGED_STATE,
        BOOTSTRAP_STEP_PROJECT,
    ]
    assert (workspace / ".giga" / "harness.toml").is_file()
    assert all(
        (data_root / name).is_dir() for name in ("integrations", "native", "support")
    )
    journal = (
        data_root / "bootstrap" / "applications" / f"{applied['application_id']}.json"
    )
    assert stat.S_IMODE(journal.stat().st_mode) == 0o600
    assert service.status(applied["application_id"]) == applied

    rolled_back = service.rollback(applied["application_id"], workspace=workspace)

    assert rolled_back["status"] == "rolled_back"
    assert rolled_back["rollback_available"] is False
    assert not (workspace / ".giga").exists()
    assert all(
        not (data_root / name).exists()
        for name in ("integrations", "native", "support")
    )
    assert service.rollback(applied["application_id"], workspace=workspace) == (
        rolled_back
    )


def test_bootstrap_rejects_stale_plan_before_mutation(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_root = tmp_path / "state"
    monkeypatch.setattr(
        bootstrap,
        "build_doctor_report",
        lambda config, *, workspace: _doctor_report(),
    )
    service = BootstrapService(HarnessConfig(data_dir=str(data_root)))
    preview = service.preview(workspace=workspace)
    (workspace / ".giga").mkdir()
    (workspace / ".giga" / "harness.toml").write_text(
        '[project]\nname = "existing"\n',
        encoding="utf-8",
    )

    with pytest.raises(BootstrapConflictError, match="stale"):
        service.apply(
            plan_id=preview["plan"]["plan_id"],
            all_reversible=True,
            workspace=workspace,
        )

    assert not data_root.exists()


def test_bootstrap_rolls_back_only_unchanged_created_files(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_root = tmp_path / "state"
    monkeypatch.setattr(
        bootstrap,
        "build_doctor_report",
        lambda config, *, workspace: _doctor_report(),
    )
    service = BootstrapService(HarnessConfig(data_dir=str(data_root)))
    preview = service.preview(workspace=workspace)
    applied = service.apply(
        plan_id=preview["plan"]["plan_id"],
        all_reversible=True,
        workspace=workspace,
    )
    config_path = workspace / ".giga" / "harness.toml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8") + "\n# operator change\n",
        encoding="utf-8",
    )

    with pytest.raises(BootstrapConflictError, match="changed"):
        service.rollback(applied["application_id"], workspace=workspace)

    assert config_path.is_file()
    assert service.status(applied["application_id"])["status"] == "applied"


def test_bootstrap_cli_preview_apply_status_and_rollback(
    tmp_path,
    monkeypatch,
    capsys,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data_root = tmp_path / "state"
    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(data_root))
    monkeypatch.setattr(
        bootstrap,
        "build_doctor_report",
        lambda config, *, workspace: _doctor_report(),
    )

    assert (
        cli.main(
            [
                "bootstrap",
                "preview",
                "--workspace",
                str(workspace),
                "--json",
            ]
        )
        == 0
    )
    preview = json.loads(capsys.readouterr().out)
    assert (
        cli.main(
            [
                "bootstrap",
                "apply",
                preview["plan"]["plan_id"],
                "--workspace",
                str(workspace),
                "--all-reversible",
                "--json",
            ]
        )
        == 0
    )
    applied = json.loads(capsys.readouterr().out)

    assert cli.main(["bootstrap", "status", applied["application_id"], "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "applied"
    assert (
        cli.main(
            [
                "bootstrap",
                "rollback",
                applied["application_id"],
                "--workspace",
                str(workspace),
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "rolled_back"


@pytest.mark.parametrize("shell", SHELLS)
def test_bootstrap_is_advertised_by_every_static_completion(shell):
    assert "bootstrap" in render_completion(shell)
