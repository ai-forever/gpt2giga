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


def test_agent_api_duplicates_as_preview_and_runs_with_snapshot(
    monkeypatch,
    tmp_path,
):
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
        json={
            "workspace": str(workspace),
            "prompt": "Review the patch",
            "idempotency_key": "cockpit-agent-review-1",
        },
    )
    assert run.status_code == 200
    assert run.json()["run"]["metadata"]["agent_id"] == "reviewer"
    assert (
        run.json()["run"]["metadata"]["agent_profile_snapshot"]["title"] == "Reviewer"
    )
    plan = run.json()["run"]["metadata"]["agent_execution_plan"]
    assert plan["queueable"] is True
    assert plan["options"]["budgets.max_attempts"]["effective"] == 1

    retried = client.post(
        "/api/agents/reviewer/run",
        json={
            "workspace": str(workspace),
            "prompt": "Review the patch",
            "idempotency_key": "cockpit-agent-review-1",
        },
    )
    rebound = client.post(
        "/api/agents/reviewer/run",
        json={
            "workspace": str(workspace),
            "prompt": "Review a different patch",
            "idempotency_key": "cockpit-agent-review-1",
        },
    )

    assert retried.status_code == 200, retried.text
    assert retried.json()["run"]["id"] == run.json()["run"]["id"]
    assert retried.json()["session"]["id"] == run.json()["session"]["id"]
    assert rebound.status_code == 409


def test_agent_api_rejects_unsupported_options_before_creating_a_run(tmp_path):
    client, workspace = _client(tmp_path)
    path = workspace / ".giga" / "agents" / "reviewer.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "budgets:\n",
            "budgets:\n  max_tokens: 512\n",
        ),
        encoding="utf-8",
    )

    detail = client.get("/api/agents/reviewer", params={"workspace": str(workspace)})
    run = client.post(
        "/api/agents/reviewer/run",
        json={"workspace": str(workspace), "prompt": "Review the patch"},
    )

    assert detail.status_code == 200
    assert detail.json()["profile"]["execution_plan"]["queueable"] is False
    assert run.status_code == 400
    assert "max_tokens cannot be enforced" in run.json()["detail"]
