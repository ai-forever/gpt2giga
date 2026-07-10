from fastapi.testclient import TestClient

from gpt2giga.harness.config import HarnessConfig
from gpt2giga.harness.project import init_project_config
from gpt2giga.harness.ui.app import create_app


def test_workflow_api_lists_validates_runs_status_and_cancels(tmp_path) -> None:
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

        canceled = client.post(f"/api/workflow-runs/{run['id']}/cancel")
        assert canceled.status_code == 200
        assert canceled.json()["run"]["status"] == "canceled"
