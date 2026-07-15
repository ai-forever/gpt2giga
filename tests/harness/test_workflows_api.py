from fastapi.testclient import TestClient

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.project import init_project_config
from gpt2giga_harness.ui.app import create_app


def test_workflow_api_lists_validates_runs_status_and_cancels(
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

    with TestClient(create_app(config)) as client:
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
            json={"workspace": str(workspace), "prompt": "Review this project"},
        )
        assert started.status_code == 200
        run = started.json()["run"]
        assert run["definition_hash"]
        assert run["steps"][0]["status"] == "queued"

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
