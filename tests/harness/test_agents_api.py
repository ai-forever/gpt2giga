from fastapi.testclient import TestClient

from gpt2giga_harness.agents import render_starter_agent
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.project import init_project_config
from gpt2giga_harness.ui.app import create_app


def _client(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    init_project_config(workspace)
    config = HarnessConfig(data_dir=tmp_path / "data")
    return TestClient(create_app(config=config)), workspace


def test_agent_api_lists_validates_drafts_and_applies(tmp_path):
    client, workspace = _client(tmp_path)
    listing = client.get("/api/agents", params={"workspace": str(workspace)})
    assert listing.status_code == 200
    assert len(listing.json()["agents"]) == 6

    content = render_starter_agent("planner").replace("Planner", "Delivery Planner")
    draft = client.post(
        "/api/agents/planner/draft",
        json={"workspace": str(workspace), "content": content},
    )
    assert draft.status_code == 200
    assert "Delivery Planner" in draft.json()["redacted_diff"]

    applied = client.post(
        "/api/agents/planner/apply",
        json={
            "workspace": str(workspace),
            "content": content,
            "expected_hash": draft.json()["source_hash"],
        },
    )
    assert applied.status_code == 200
    assert applied.json()["profile"]["title"] == "Delivery Planner"


def test_agent_api_detects_etag_conflict_and_rejects_bad_profile(tmp_path):
    client, workspace = _client(tmp_path)
    content = render_starter_agent("planner")
    detail = client.get("/api/agents/planner", params={"workspace": str(workspace)})
    etag = detail.json()["profile"]["source_hash"]
    path = workspace / ".giga" / "agents" / "planner.yaml"
    path.write_text(content + "description: changed elsewhere\n", encoding="utf-8")

    conflict = client.post(
        "/api/agents/planner/apply",
        json={"workspace": str(workspace), "content": content, "expected_hash": etag},
    )
    invalid = client.post("/api/agents/validate", json={"content": "id: x"})

    assert conflict.status_code == 409
    assert invalid.status_code == 400


def test_agent_api_duplicates_as_preview_and_runs_with_snapshot(tmp_path):
    client, workspace = _client(tmp_path)
    duplicate = client.post(
        "/api/agents/reviewer/duplicate",
        json={"workspace": str(workspace), "new_id": "security-reviewer"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["profile"]["id"] == "security-reviewer"
    assert not (workspace / ".giga" / "agents" / "security-reviewer.yaml").exists()

    run = client.post(
        "/api/agents/reviewer/run",
        json={"workspace": str(workspace), "prompt": "Review the patch"},
    )
    assert run.status_code == 200
    assert run.json()["run"]["metadata"]["agent_id"] == "reviewer"
    assert (
        run.json()["run"]["metadata"]["agent_profile_snapshot"]["title"] == "Reviewer"
    )
