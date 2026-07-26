from datetime import datetime, timezone
import json
from pathlib import Path

from fastapi.testclient import TestClient

from gpt2giga_harness import cli
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.project import resolve_project
from gpt2giga_harness.runtime.policy import (
    SCHEDULE_CREATE_OWNER,
    SCHEDULE_ENABLE_OWNER,
)
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore
from gpt2giga_harness.runtime.worker import DurableJobWorker
from gpt2giga_harness.schedules import (
    ScheduleDefinition,
    build_schedule_definition,
    load_schedule,
    next_occurrences,
)
from gpt2giga_harness.ui.app import create_app


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
        assert (
            create_gate.json()["approval"]["enforcement_owner"] == SCHEDULE_CREATE_OWNER
        )
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
            json={
                "workspace": str(workspace),
                "idempotency_key": "cockpit-schedule-test-1",
            },
        )
        assert tested.status_code == 200
        assert tested.json()["occurrence"]["status"] == "queued"
        tested_retry = client.post(
            "/api/schedules/daily-echo/test-now",
            json={
                "workspace": str(workspace),
                "idempotency_key": "cockpit-schedule-test-1",
            },
        )
        assert tested_retry.status_code == 200
        assert (
            tested_retry.json()["occurrence"]["id"] == tested.json()["occurrence"]["id"]
        )
        assert (
            tested_retry.json()["occurrence"]["run_id"]
            == tested.json()["occurrence"]["run_id"]
        )

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
        assert (
            enable_gate.json()["approval"]["enforcement_owner"] == SCHEDULE_ENABLE_OWNER
        )
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

        stale = client.put(
            "/api/schedules/daily-echo",
            json={**payload, "expected_hash": original_hash},
        )
        assert stale.status_code == 409
        assert stale.json()["detail"] == "Schedule changed since it was loaded"


def test_schedule_native_delete_preview_binds_exact_revision(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_echo_project(workspace)
    config = HarnessConfig(data_dir=str(tmp_path / "data"), auto_start_proxy=False)
    app = create_app(config)
    project = resolve_project(workspace, data_dir=config.data_dir)
    created = app.state.harness_schedule_service.upsert(project, _payload(workspace))

    with TestClient(app) as client:
        preview = client.post(
            "/api/schedules/daily-echo/delete-preview",
            json={"workspace": str(workspace)},
        )
        assert preview.status_code == 200
        assert preview.json()["source_hash"] == created["definition"]["source_hash"]
        assert preview.json()["confirmation_required"] is True

        stale = client.delete(
            "/api/schedules/daily-echo",
            params={
                "workspace": str(workspace),
                "expected_hash": "stale",
                "confirm_id": "daily-echo",
            },
        )
        assert stale.status_code == 409

        deleted = client.delete(
            "/api/schedules/daily-echo",
            params={
                "workspace": str(workspace),
                "expected_hash": preview.json()["source_hash"],
                "confirm_id": "daily-echo",
            },
        )
        assert deleted.status_code == 200
        assert deleted.json()["archived"] is True


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


def test_scheduled_eval_redelivery_reuses_one_occurrence_and_eval_run(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_eval_project(workspace)
    config = HarnessConfig(data_dir=str(tmp_path / "data"), auto_start_proxy=False)
    service = create_app(config).state.harness_schedule_service
    project = resolve_project(workspace, data_dir=config.data_dir)
    service.upsert(project, _eval_payload(workspace))
    definition = load_schedule(project.root, "scheduled-eval")
    occurrence = service._create_occurrence(  # noqa: SLF001
        definition,
        schedule_key=service.detail(project, definition.id)["state"]["schedule_key"],
        trigger="schedule",
        scheduled_for="2026-07-15T08:00:00+00:00",
    )
    duplicate = service._create_occurrence(  # noqa: SLF001
        definition,
        schedule_key=service.detail(project, definition.id)["state"]["schedule_key"],
        trigger="schedule",
        scheduled_for="2026-07-15T08:00:00+00:00",
    )

    first = service._execute(  # noqa: SLF001
        project, definition, occurrence, dry_run=False
    )
    second = service._execute(  # noqa: SLF001
        project, definition, occurrence, dry_run=False
    )

    current = service._get_occurrence(occurrence.id)  # noqa: SLF001
    assert duplicate.id == occurrence.id
    assert first["occurrence"]["run_id"] == current.run_id
    assert second["occurrence"]["run_id"] == current.run_id
    assert current.status == "queued"
    assert len(service.eval_store.list_runs(project)) == 1
    assert len(RuntimeCoordinationStore(config.data_dir).list_jobs()) == 1


def test_worker_tick_persists_scheduled_eval_under_project_state(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_eval_project(workspace)
    data_dir = tmp_path / "data"
    config = HarnessConfig(data_dir=str(data_dir), auto_start_proxy=False)
    service = create_app(config).state.harness_schedule_service
    project = resolve_project(workspace, data_dir=config.data_dir)
    service.upsert(project, _eval_payload(workspace))
    due_at = "2026-07-15T08:00:00+00:00"
    with service.runtime_store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "UPDATE schedule_states SET enabled = 1, status = 'active', "
            "next_run_at = ? WHERE project_id = ? AND schedule_id = ?",
            (due_at, project.id, "scheduled-eval"),
        )
    worker_cwd = tmp_path / "worker-cwd"
    worker_cwd.mkdir()
    monkeypatch.chdir(worker_cwd)

    assert service.tick() == 1

    runs = service.eval_store.list_runs(project)
    assert len(runs) == 1
    assert runs[0].project_id == project.id
    assert Path(project.state_dir, "eval-runs", f"{runs[0].id}.json").is_file()
    assert not (worker_cwd / "eval-runs").exists()


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


def test_automation_center_combines_attention_and_preserves_archive_snapshot(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_echo_project(workspace)
    config = HarnessConfig(data_dir=str(tmp_path / "data"), auto_start_proxy=False)
    app = create_app(config)
    project = resolve_project(workspace, data_dir=config.data_dir)
    service = app.state.harness_schedule_service
    payload = {**_payload(workspace), "notifications": {"desktop": True}}
    created = service.upsert(project, payload)
    source_hash = created["definition"]["source_hash"]
    service._mark_attention(  # noqa: SLF001 - exercises derived UI projection
        created["state"]["schedule_key"], "nightly regression"
    )
    runtime = app.state.harness_runtime_store
    job = runtime.submit_job(
        session_id="session_failed",
        user_message_id="message_failed",
        idempotency_key="automation-failed",
        project_id=project.id,
        initial_run_id="run_failed",
    ).job
    runtime.transition_job(job.id, "failed", error_summary="tests failed")

    with TestClient(app) as client:
        approval = client.post("/api/schedules", json=payload)
        assert approval.status_code == 202
        overview = client.get("/api/automation", params={"workspace": str(workspace)})
        assert overview.status_code == 200
        attention = overview.json()["attention"]
        assert attention["unread"] == 3
        assert {item["kind"] for item in attention["items"]} == {
            "approval",
            "failed_job",
            "schedule",
        }
        assert (
            next(item for item in attention["items"] if item["kind"] == "schedule")[
                "desktop_notification"
            ]
            is True
        )

        ids = [item["id"] for item in attention["items"]]
        marked = client.post(
            "/api/attention/read", json={"item_ids": ids, "read": True}
        )
        assert marked.status_code == 200
        assert (
            client.get("/api/attention", params={"workspace": str(workspace)}).json()[
                "unread"
            ]
            == 0
        )

        archived = client.delete(
            "/api/schedules/daily-echo", params={"workspace": str(workspace)}
        )
        assert archived.status_code == 200
        archived_item = client.get(
            "/api/automation", params={"workspace": str(workspace)}
        ).json()["schedules"][0]
        assert archived_item["state"]["status"] == "archived"
        assert archived_item["definition"]["source_hash"] == source_hash
        assert archived_item["definition"]["target"]["id"] == "echo"


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


def _write_eval_project(workspace):
    directory = workspace / ".giga"
    evals = directory / "evals"
    evals.mkdir(parents=True)
    (directory / "harness.toml").write_text(
        '[project]\nname = "scheduled-eval-project"\n',
        encoding="utf-8",
    )
    (evals / "scheduled-smoke.yaml").write_text(
        """
name: scheduled-smoke
harnesses: [echo]
api_mode: v2
mode: read
workspace_policy: current
cases:
  - id: echo
    prompt: scheduled hello
    checks:
      - type: equals
        value: scheduled hello
""".lstrip(),
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


def _eval_payload(workspace):
    return {
        "id": "scheduled-eval",
        "title": "Scheduled eval",
        "workspace": str(workspace),
        "target": {"kind": "eval", "id": "scheduled-smoke"},
        "cadence": {
            "kind": "interval",
            "timezone": "Europe/Moscow",
            "start_at": "2026-07-15T11:00:00",
            "interval_seconds": 3600,
        },
        "misfire_policy": "run_once",
        "workspace_policy": "worktree",
    }
