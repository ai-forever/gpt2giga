import json

from fastapi.testclient import TestClient

from gpt2giga_harness import cli
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.project import init_project_config
from gpt2giga_harness.ui.app import create_app


def test_workflow_api_lists_validates_runs_status_and_cancels(
    capsys,
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "gpt2giga_harness.session_runner.HarnessSessionRunner._execution_readiness",
        lambda _self, _options, *, durable: {
            "ok": True,
            "blocked": False,
            "summary": {"ready": 1, "degraded": 0, "blocked": 0},
            "plan": {"delivery": "durable" if durable else "synchronous"},
            "findings": [],
        },
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    init_project_config(workspace)
    config = HarnessConfig(
        data_dir=str(tmp_path / "data"),
        proxy_url="http://127.0.0.1:9",
        auto_start_proxy=False,
    )
    monkeypatch.setenv("GPT2GIGA_HARNESS_DATA_DIR", config.data_dir)
    monkeypatch.setenv("GPT2GIGA_HARNESS_PROXY_URL", config.proxy_url)
    monkeypatch.setenv("GPT2GIGA_HARNESS_AUTO_START_PROXY", "false")

    assert (
        cli.main(
            [
                "workflow",
                "run",
                "review-team",
                "--workspace",
                str(workspace),
                "--prompt",
                "Review this project",
                "--json",
            ]
        )
        == 0
    )
    cli_run = json.loads(capsys.readouterr().out)["run"]

    app = create_app(config)
    worker = {"online": True}
    app.state.harness_schedule_service.worker_health = lambda: {
        "online": worker["online"],
        "count": 1,
    }
    with TestClient(app) as client:
        listed = client.get("/api/workflows", params={"workspace": str(workspace)})
        assert listed.status_code == 200
        assert listed.json()["workflows"][0]["id"] == "review-team"
        assert len(listed.json()["templates"]) == 3

        content = (workspace / ".giga" / "workflows" / "review-team.yaml").read_text()
        validated = client.post("/api/workflows/validate", json={"content": content})
        assert validated.status_code == 200
        assert validated.json()["plan"]["levels"][1] == [
            "security",
            "tests",
            "maintainability",
        ]

        started = client.post(
            "/api/workflows/review-team/run",
            json={
                "workspace": str(workspace),
                "prompt": "Review this project",
                "idempotency_key": "cockpit-workflow-review-1",
            },
        )
        assert started.status_code == 200
        run = started.json()["run"]
        assert run["definition_hash"]
        assert run["steps"][0]["status"] == "queued"
        assert run["definition_hash"] == cli_run["definition_hash"]
        assert run["definition"] == cli_run["definition"]
        assert run["inputs"] == cli_run["inputs"]
        assert run["max_concurrency"] == cli_run["max_concurrency"]
        assert [
            (step["step_id"], step["kind"], step["status"], step["snapshot"])
            for step in run["steps"]
        ] == [
            (step["step_id"], step["kind"], step["status"], step["snapshot"])
            for step in cli_run["steps"]
        ]

        worker["online"] = False
        retried = client.post(
            "/api/workflows/review-team/run",
            json={
                "workspace": str(workspace),
                "prompt": "Review this project",
                "idempotency_key": "cockpit-workflow-review-1",
            },
        )
        rebound = client.post(
            "/api/workflows/review-team/run",
            json={
                "workspace": str(workspace),
                "prompt": "Review something else",
                "idempotency_key": "cockpit-workflow-review-1",
            },
        )
        assert retried.status_code == 200
        assert retried.json()["run"]["id"] == run["id"]
        assert retried.json()["run"]["session_id"] == run["session_id"]
        assert rebound.status_code == 409
        assert "different workflow submission" in rebound.json()["detail"]
        worker["online"] = True

        child_summary = client.get(
            f"/api/runs/{run['steps'][0]['outputs']['run_id']}/summary"
        )
        assert child_summary.status_code == 200
        team = child_summary.json()["run"]["workflow"]
        assert team["definition_id"] == "review-team"
        assert team["total_steps"] == 5
        assert team["active_steps"] == ["plan"]
        assert team["steps"][0]["actions"]["open_run"].startswith("/runs/")

        status = client.get(f"/api/workflow-runs/{run['id']}")
        assert status.status_code == 200
        assert status.json()["run"]["id"] == run["id"]

        handoffs = client.get(f"/api/workflow-runs/{run['id']}/handoffs")
        assert handoffs.status_code == 200
        assert handoffs.json()["candidates"] == []
        assert (
            client.post(f"/api/workflow-runs/{run['id']}/merge-queue").status_code
            == 400
        )
        assert (
            client.post(f"/api/workflow-runs/{run['id']}/merge-queue/apply").status_code
            == 400
        )

        canceled = client.post(f"/api/workflow-runs/{run['id']}/cancel")
        assert canceled.status_code == 200
        assert canceled.json()["run"]["status"] == "canceled"


def test_workflow_run_reports_missing_and_offline_worker_before_advancement(
    monkeypatch,
    tmp_path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    init_project_config(workspace)
    config = HarnessConfig(
        data_dir=str(tmp_path / "data"),
        proxy_url="http://127.0.0.1:9",
        auto_start_proxy=False,
    )
    app = create_app(config)

    def fail_if_created(*_args, **_kwargs):
        raise AssertionError("offline workflow must not create retained state")

    monkeypatch.setattr(
        "gpt2giga_harness.workflows.WorkflowCoordinator._start_new",
        fail_if_created,
    )

    with TestClient(app) as client:
        missing = client.post(
            "/api/workflows/missing/run",
            json={"workspace": str(workspace)},
        )
        offline = client.post(
            "/api/workflows/review-team/run",
            json={
                "workspace": str(workspace),
                "idempotency_key": "cockpit-offline-workflow-1",
            },
        )

    assert missing.status_code == 404
    assert offline.status_code == 409
    assert offline.json()["detail"] == (
        "The durable worker is offline. Start it with `giga worker start`, then retry."
    )


def test_workflow_catalog_api_edits_histories_duplicates_imports_and_exports(
    tmp_path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    init_project_config(workspace)
    config = HarnessConfig(
        data_dir=str(tmp_path / "data"),
        proxy_url="http://127.0.0.1:9",
        auto_start_proxy=False,
    )

    with TestClient(create_app(config)) as client:
        detail = client.get(
            "/api/workflows/review-team", params={"workspace": str(workspace)}
        )
        assert detail.status_code == 200
        initial = detail.json()
        assert initial["source"].startswith("id: review-team")
        assert initial["history"] == []

        updated = client.put(
            "/api/workflows/review-team",
            json={
                "workspace": str(workspace),
                "content": initial["source"] + "future_ui: {color: blue}\n",
                "expected_hash": initial["workflow"]["source_hash"],
                "form": {
                    "title": "Review Team Updated",
                    "version": "1.1.0",
                    "steps": initial["workflow"]["steps"],
                },
            },
        )
        assert updated.status_code == 200
        assert updated.json()["workflow"]["title"] == "Review Team Updated"
        assert len(updated.json()["history"]) == 1
        assert "future_ui:" in updated.json()["source"]

        stale = client.put(
            "/api/workflows/review-team",
            json={
                "workspace": str(workspace),
                "content": initial["source"],
                "expected_hash": initial["workflow"]["source_hash"],
            },
        )
        assert stale.status_code == 409

        renamed = client.put(
            "/api/workflows/review-team",
            json={
                "workspace": str(workspace),
                "content": updated.json()["source"].replace(
                    "id: review-team", "id: renamed-flow", 1
                ),
                "expected_hash": updated.json()["workflow"]["source_hash"],
            },
        )
        assert renamed.status_code == 409
        assert not (workspace / ".giga" / "workflows" / "renamed-flow.yaml").exists()

        copied = client.post(
            "/api/workflows/review-team/duplicate",
            json={"workspace": str(workspace), "new_id": "review-copy"},
        )
        assert copied.status_code == 201
        assert copied.json()["workflow"]["id"] == "review-copy"

        imported = client.post(
            "/api/workflows/import",
            json={
                "workspace": str(workspace),
                "template_id": "diagnose-fix-regression",
            },
        )
        assert imported.status_code == 201
        assert imported.json()["plan"]["step_count"] == 3

        exported = client.get(
            "/api/workflows/review-copy/export",
            params={"workspace": str(workspace)},
        )
        assert exported.status_code == 200
        assert "attachment;" in exported.headers["content-disposition"]
        assert exported.text.startswith("id: review-copy")


def test_workflow_native_authoring_previews_applies_and_retains_delete_history(
    tmp_path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    init_project_config(workspace)
    config = HarnessConfig(
        data_dir=str(tmp_path / "data"),
        proxy_url="http://127.0.0.1:9",
        auto_start_proxy=False,
    )
    content = "\n".join(
        [
            "id: native-flow",
            "title: Native flow",
            "version: '1.0.0'",
            "steps:",
            "  - id: keep",
            "    kind: transform",
            "    transform: identity",
            "",
        ]
    )

    with TestClient(create_app(config)) as client:
        preview = client.post(
            "/api/workflows/native-flow/draft",
            json={"workspace": str(workspace), "content": content},
        )
        assert preview.status_code == 200
        assert preview.json()["plan"]["step_count"] == 1
        assert preview.json()["redacted_diff"].startswith("--- ")

        applied = client.post(
            "/api/workflows/native-flow/apply",
            json={
                "workspace": str(workspace),
                "content": content,
                "expected_hash": preview.json()["source_hash"],
            },
        )
        assert applied.status_code == 200
        source_hash = applied.json()["workflow"]["source_hash"]

        delete_preview = client.post(
            "/api/workflows/native-flow/delete-preview",
            json={"workspace": str(workspace)},
        )
        assert delete_preview.status_code == 200
        assert delete_preview.json()["source_hash"] == source_hash
        assert delete_preview.json()["dependents"] == []

        stale = client.post(
            "/api/workflows/native-flow/delete",
            json={
                "workspace": str(workspace),
                "expected_hash": "stale",
                "confirm_id": "native-flow",
            },
        )
        assert stale.status_code == 409

        deleted = client.post(
            "/api/workflows/native-flow/delete",
            json={
                "workspace": str(workspace),
                "expected_hash": source_hash,
                "confirm_id": "native-flow",
            },
        )
        assert deleted.status_code == 200
        history = workspace / ".giga" / "workflows" / ".history" / "native-flow"
        assert len(list(history.glob("*.yaml"))) == 1
