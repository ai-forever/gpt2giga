import json
import subprocess

from fastapi.testclient import TestClient

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.sessions.models import HarnessStoredEvent
from gpt2giga_harness.sessions.store import new_id, utc_now
from gpt2giga_harness.ui.app import create_app


def test_trace_replay_api_binds_one_axis_to_new_session_and_comparison(tmp_path):
    app = _app(tmp_path)
    client = TestClient(app)
    created = client.post(
        "/api/sessions/run",
        json={
            "harness_id": "echo",
            "model": "source-model",
            "prompt": "trace-canary-must-not-enter-manifest",
        },
    )
    assert created.status_code == 200
    source = created.json()
    source_run_id = source["run"]["id"]

    preview = client.post(
        f"/api/runs/{source_run_id}/trace-replays/preview",
        json={"axis": "model", "target": "target-model"},
    )

    assert preview.status_code == 200
    preview_body = preview.json()
    manifest = preview_body["manifest"]
    assert manifest["axis"] == "model"
    assert manifest["source_dimensions"]["model"] == "source-model"
    assert manifest["target_dimensions"]["model"] == "target-model"
    assert manifest["source_dimensions"]["harness"] == "echo"
    assert manifest["target_dimensions"]["harness"] == "echo"
    assert preview_body["admission"] == {"admitted": True, "reason_code": None}
    assert "trace-canary" not in json.dumps(preview_body)

    started = client.post(
        f"/api/runs/{source_run_id}/trace-replays",
        json={
            "axis": "model",
            "target": "target-model",
            "manifest_sha256": manifest["manifest_sha256"],
        },
    )

    assert started.status_code == 200
    replay = started.json()
    assert replay["source"]["run_id"] == source_run_id
    assert replay["destination"]["run_id"] != source_run_id
    assert replay["destination"]["session_id"] != source["session"]["id"]
    assert replay["destination"]["model"] == "target-model"
    assert replay["snapshot_equality"] == {
        "status": "verified",
        "changed_axes": ["model"],
        "unchanged_verified": True,
        "target_verified": True,
    }
    assert replay["comparison_status"] == "ready"
    assert replay["comparison"]["semantic"]["changed"] is False
    assert replay["comparison"]["tools"]["source"]["event_count"] == 0
    assert replay["comparison"]["tools"]["target"]["event_count"] == 0
    assert replay["comparison"]["cost"]["source"]["confidence"] == "unknown"
    assert replay["comparison"]["cost"]["target"]["confidence"] == "unknown"
    assert replay["comparison"]["cost"]["delta"] is None
    assert replay["external_telemetry_required"] is False
    assert replay["automatic_apply"] is False

    retained = client.get(f"/api/runs/{replay['destination']['run_id']}/trace-replay")
    assert retained.status_code == 200
    assert retained.json() == replay
    assert (
        app.state.harness_session_store.get_run(source_run_id).model == "source-model"
    )


def test_trace_replay_rejects_stale_multi_axis_and_provider_authority(tmp_path):
    app = _app(tmp_path)
    client = TestClient(app)
    created = client.post(
        "/api/sessions/run",
        json={"harness_id": "echo", "model": "source-model", "prompt": "source"},
    ).json()
    run_id = created["run"]["id"]

    unknown = client.post(
        f"/api/runs/{run_id}/trace-replays/preview",
        json={"axis": "model", "target": "target", "harness": "other"},
    )
    assert unknown.status_code == 400
    assert "unknown trace replay fields" in unknown.text

    unchanged = client.post(
        f"/api/runs/{run_id}/trace-replays/preview",
        json={"axis": "model", "target": "source-model"},
    )
    assert unchanged.status_code == 400
    assert "exactly one execution axis" in unchanged.text

    preview = client.post(
        f"/api/runs/{run_id}/trace-replays/preview",
        json={"axis": "model", "target": "target-model"},
    ).json()
    run = app.state.harness_session_store.get_run(run_id)
    app.state.harness_session_store.append_event(
        HarnessStoredEvent(
            id=new_id("evt"),
            session_id=run.session_id,
            run_id=run.id,
            type="tool.completed",
            message="content-free",
            payload={"tool_id": "fixture"},
            created_at=utc_now(),
        )
    )
    stale = client.post(
        f"/api/runs/{run_id}/trace-replays",
        json={
            "axis": "model",
            "target": "target-model",
            "manifest_sha256": preview["manifest"]["manifest_sha256"],
        },
    )
    assert stale.status_code == 409
    assert "source evidence changed" in stale.text

    provider = client.post(
        f"/api/runs/{run_id}/trace-replays/preview",
        json={"axis": "provider", "target": "provider-b@revision-2"},
    )
    assert provider.status_code == 200
    assert provider.json()["admission"] == {
        "admitted": False,
        "reason_code": "provider_axis_requires_route_authority",
    }
    blocked = client.post(
        f"/api/runs/{run_id}/trace-replays",
        json={
            "axis": "provider",
            "target": "provider-b@revision-2",
            "manifest_sha256": provider.json()["manifest"]["manifest_sha256"],
        },
    )
    assert blocked.status_code == 400
    assert "provider_axis_requires_route_authority" in blocked.text


def test_trace_replay_workspace_run_uses_fresh_isolated_worktree(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "config", "user.name", "Trace Replay")
    _git(repository, "config", "user.email", "trace@example.test")
    (repository / "tracked.txt").write_text("baseline\n", encoding="utf-8")
    _git(repository, "add", "tracked.txt")
    _git(repository, "commit", "-m", "baseline")

    app = _app(tmp_path / "data")
    client = TestClient(app)
    created = client.post(
        "/api/sessions/run",
        json={
            "harness_id": "echo",
            "mode": "edit",
            "model": "source-model",
            "prompt": "isolated replay",
            "workspace": str(repository),
            "workspace_policy": "current",
        },
    )
    assert created.status_code == 200
    source = created.json()
    source_run_id = source["run"]["id"]
    assert source["run"]["metadata"]["workspace_execution"]["worktree_path"] is None

    preview = client.post(
        f"/api/runs/{source_run_id}/trace-replays/preview",
        json={"axis": "model", "target": "target-model"},
    ).json()
    started = client.post(
        f"/api/runs/{source_run_id}/trace-replays",
        json={
            "axis": "model",
            "target": "target-model",
            "manifest_sha256": preview["manifest"]["manifest_sha256"],
        },
    )

    assert started.status_code == 200
    assert started.json()["destination"]["workspace_isolated"] is True
    destination = app.state.harness_session_store.get_run(
        started.json()["destination"]["run_id"]
    )
    workspace = destination.metadata["workspace_execution"]
    assert workspace["policy"] == "worktree"
    assert workspace["source_workspace"] == str(repository)
    assert workspace["worktree_path"] != str(repository)
    assert (
        app.state.harness_session_store.get_run(source_run_id).metadata[
            "workspace_execution"
        ]["worktree_path"]
        is None
    )


def _app(data_dir):
    return create_app(
        HarnessConfig(data_dir=str(data_dir)),
        registry=create_default_registry(include_entry_points=False),
    )


def _git(repository, *args):
    result = subprocess.run(
        ("git", *args),
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()
