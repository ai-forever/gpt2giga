from datetime import datetime, timezone
import json

from fastapi.testclient import TestClient

from gpt2giga.harness import cli
from gpt2giga.harness.config import HarnessConfig
from gpt2giga.harness.project import resolve_project
from gpt2giga.harness.runtime.store import RuntimeCoordinationStore
from gpt2giga.harness.runtime.worker import DurableJobWorker
from gpt2giga.harness.schedules import (
    ScheduleDefinition,
    build_schedule_definition,
    next_occurrences,
)
from gpt2giga.harness.ui.app import create_app


def test_rrule_preview_records_nonexistent_time_and_uses_first_ambiguous_instant():
    spring = _definition(
        start_at="2026-03-29T02:30:00",
        rrule_text="FREQ=DAILY",
        timezone_name="Europe/Berlin",
    )
    spring_rows = next_occurrences(
        spring,
        after=datetime(2026, 3, 28, 0, tzinfo=timezone.utc),
        count=2,
    )
    assert spring_rows[0]["status"] == "misfire"
    assert spring_rows[0]["reason"] == "nonexistent_local_time"
    assert spring_rows[1]["utc"] == "2026-03-30T00:30:00+00:00"

    autumn = _definition(
        start_at="2026-10-25T02:30:00",
        rrule_text="FREQ=DAILY",
        timezone_name="Europe/Berlin",
    )
    autumn_rows = next_occurrences(
        autumn,
        after=datetime(2026, 10, 24, 0, tzinfo=timezone.utc),
        count=1,
    )
    assert autumn_rows[0]["utc"] == "2026-10-25T00:30:00+00:00"
    assert autumn_rows[0]["reason"] == "ambiguous_first_instant"


def test_schedule_api_requires_exact_test_hash_and_online_worker(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_echo_project(workspace)
    config = HarnessConfig(data_dir=str(tmp_path / "data"), auto_start_proxy=False)
    payload = _payload(workspace)

    with TestClient(create_app(config)) as client:
        preview = client.post("/api/schedules/preview", json=payload)
        assert preview.status_code == 200
        assert preview.json()["dry_run"] is True
        assert not (workspace / ".giga" / "schedules").exists()

        create_gate = client.post("/api/schedules", json=payload)
        assert create_gate.status_code == 202
        create_approval = create_gate.json()["approval"]["id"]
        approved_create = client.post(
            f"/api/approvals/{create_approval}/decision",
            json={"decision": "allow_project", "expires_in_seconds": 3600},
        )
        assert approved_create.status_code == 200
        created = client.post("/api/schedules", json=payload)
        assert created.status_code == 201
        original_hash = created.json()["definition"]["source_hash"]
        assert created.json()["state"]["enabled"] == 0

        untested = client.post(
            "/api/schedules/daily-echo/enable", json={"workspace": str(workspace)}
        )
        assert untested.status_code == 409

        tested = client.post(
            "/api/schedules/daily-echo/test-now",
            json={"workspace": str(workspace)},
        )
        assert tested.status_code == 200
        assert tested.json()["occurrence"]["status"] == "queued"

        offline = client.post(
            "/api/schedules/daily-echo/enable", json={"workspace": str(workspace)}
        )
        assert offline.status_code == 409
        worker = DurableJobWorker(config, worker_id="worker_api_test")
        assert worker.run_once() is True
        assert worker.run_once() is False
        enable_gate = client.post(
            "/api/schedules/daily-echo/enable", json={"workspace": str(workspace)}
        )
        assert enable_gate.status_code == 202
        enable_approval = enable_gate.json()["approval"]["id"]
        assert (
            client.post(
                f"/api/approvals/{enable_approval}/decision",
                json={"decision": "allow_once"},
            ).status_code
            == 200
        )
        enabled = client.post(
            "/api/schedules/daily-echo/enable", json={"workspace": str(workspace)}
        )
        assert enabled.status_code == 200
        assert enabled.json()["state"]["enabled"] == 1

        changed = {**payload, "prompt": "changed"}
        updated = client.put("/api/schedules/daily-echo", json=changed)
        assert updated.status_code == 200
        assert updated.json()["definition"]["source_hash"] != original_hash
        assert updated.json()["state"]["tested_hash"] is None
        assert updated.json()["state"]["enabled"] == 0


def test_schedule_cli_crud_and_preview(tmp_path, monkeypatch, capsys):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_echo_project(workspace)
    data_dir = tmp_path / "data"
    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", str(data_dir))
    source = tmp_path / "schedule.yaml"
    source.write_text(
        "\n".join(
            [
                "id: daily-echo",
                "title: Daily echo",
                "target: {kind: preset, id: echo}",
                "cadence:",
                "  kind: interval",
                "  timezone: Europe/Moscow",
                "  start_at: '2026-07-12T10:00:00'",
                "  interval_seconds: 3600",
                "prompt: scheduled hello",
                "workspace_policy: worktree",
            ]
        ),
        encoding="utf-8",
    )

    assert (
        cli.main(
            [
                "schedule",
                "preview",
                str(source),
                "--workspace",
                str(workspace),
                "--json",
            ]
        )
        == 0
    )
    preview = json.loads(capsys.readouterr().out)
    assert preview["dry_run"] is True
    assert (
        cli.main(
            ["schedule", "create", str(source), "--workspace", str(workspace), "--json"]
        )
        == 0
    )
    created = json.loads(capsys.readouterr().out)
    assert created["definition"]["id"] == "daily-echo"
    assert cli.main(["schedule", "list", "--workspace", str(workspace), "--json"]) == 0
    assert len(json.loads(capsys.readouterr().out)["schedules"]) == 1
    assert (
        cli.main(
            [
                "schedule",
                "delete",
                "daily-echo",
                "--workspace",
                str(workspace),
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["archived"] is True


def test_schedule_target_snapshot_is_immutable(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_echo_project(workspace)
    project = resolve_project(workspace, data_dir=tmp_path / "data")
    definition = build_schedule_definition(project, _payload(workspace))
    before = definition.target_hash
    config_path = workspace / ".giga" / "harness.toml"
    config_path.write_text(config_path.read_text().replace("Scheduled", "Changed"))

    assert definition.target_hash == before
    assert definition.target_snapshot["title"] == "Scheduled echo"


def test_worker_executes_run_now_without_an_open_browser(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_echo_project(workspace)
    config = HarnessConfig(data_dir=str(tmp_path / "data"), auto_start_proxy=False)
    app = create_app(config)
    project = resolve_project(workspace, data_dir=config.data_dir)
    service = app.state.harness_schedule_service
    service.upsert(project, _payload(workspace))
    service.test_now(project, "daily-echo")
    worker = DurableJobWorker(config, worker_id="worker_schedule_test")
    assert worker.run_once() is True
    assert worker.run_once() is False
    queued = service.run_now(project, "daily-echo")
    occurrence_id = queued["occurrence"]["id"]

    assert worker.run_once() is True
    assert worker.run_once() is False

    detail = service.detail(project, "daily-echo")
    occurrence = next(
        item for item in detail["occurrences"] if item["id"] == occurrence_id
    )
    assert occurrence["status"] == "succeeded"
    job = RuntimeCoordinationStore(config.data_dir).get_job(occurrence["job_id"])
    assert job.origin == "scheduled"
    assert job.schedule_id == "daily-echo"


def test_schedule_ids_are_scoped_per_project(tmp_path):
    config = HarnessConfig(data_dir=str(tmp_path / "data"), auto_start_proxy=False)
    service = create_app(config).state.harness_schedule_service
    projects = []
    for name in ("one", "two"):
        workspace = tmp_path / name
        workspace.mkdir()
        _write_echo_project(workspace)
        project = resolve_project(workspace, data_dir=config.data_dir)
        service.upsert(project, _payload(workspace))
        projects.append(project)

    assert (
        service.detail(projects[0], "daily-echo")["state"]["project_id"]
        == projects[0].id
    )
    assert (
        service.detail(projects[1], "daily-echo")["state"]["project_id"]
        == projects[1].id
    )
    assert (
        RuntimeCoordinationStore(config.data_dir).inspect()["counts"]["schedule_states"]
        == 2
    )


def _definition(
    *, start_at: str, rrule_text: str, timezone_name: str
) -> ScheduleDefinition:
    return ScheduleDefinition(
        id="dst",
        title="DST",
        target_kind="preset",
        target_id="echo",
        target_hash="hash",
        target_snapshot={},
        cadence_kind="rrule",
        timezone=timezone_name,
        start_at=start_at,
        rrule_text=rrule_text,
    )


def _write_echo_project(workspace):
    directory = workspace / ".giga"
    directory.mkdir()
    (directory / "harness.toml").write_text(
        """
[project]
name = "scheduled"

[presets.echo]
title = "Scheduled echo"
harness = "echo"
mode = "read"
prompt = "scheduled hello"
""",
        encoding="utf-8",
    )


def _payload(workspace):
    return {
        "id": "daily-echo",
        "title": "Daily echo",
        "workspace": str(workspace),
        "target": {"kind": "preset", "id": "echo"},
        "cadence": {
            "kind": "interval",
            "timezone": "Europe/Moscow",
            "start_at": "2026-07-12T10:00:00",
            "interval_seconds": 3600,
        },
        "prompt": "scheduled hello",
        "workspace_policy": "worktree",
    }
