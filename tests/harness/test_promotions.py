from pathlib import Path

from fastapi.testclient import TestClient
import yaml

from gpt2giga.harness.config import HarnessConfig
from gpt2giga.harness.project import init_project_config
from gpt2giga.harness.types import GigaChatApiMode, HarnessCapability
from gpt2giga.harness.ui.app import create_app


def _app_with_run(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    init_project_config(workspace)
    app = create_app(HarnessConfig(data_dir=tmp_path / "data"))
    session = app.state.harness_session_store.create_session(
        workspace=str(workspace), default_harness_id="echo"
    )
    run = app.state.harness_session_store.create_run(
        session_id=session.id,
        harness_id="echo",
        prompt=(
            f"Review {workspace}/src/app.py for token=very-secret-value "
            "in run_one_off_identifier"
        ),
        model="GigaChat-Test",
        api_mode=GigaChatApiMode.V2,
        capability=HarnessCapability.AGENT_CLI,
        mode="edit",
        workspace=str(workspace),
        metadata={
            "agent_id": "implementer",
            "permission_profile": "interactive",
            "selected_files": ["src/app.py", "../escape.py", "/tmp/private.py"],
            "workspace_execution": {
                "changed_files": ["src/app.py"],
                "patch": "raw patch must not be promoted",
            },
            "raw_tool_result": "must not be promoted",
            "pr_artifact": {"title": "one off"},
        },
    )
    return app, workspace, run


def test_run_promotion_requires_review_and_writes_each_project_yaml(tmp_path) -> None:
    app, workspace, run = _app_with_run(tmp_path)
    expected = {
        "agent": Path(".giga/agents/promoted-agent.yaml"),
        "workflow": Path(".giga/workflows/promoted-workflow.yaml"),
        "eval": Path(".giga/evals/promoted-eval.yaml"),
    }
    with TestClient(app) as client:
        for kind, relative in expected.items():
            target_id = f"promoted-{kind}"
            preview = client.post(
                f"/api/runs/{run.id}/promotions/preview",
                json={"kind": kind, "target_id": target_id},
            )
            assert preview.status_code == 200
            body = preview.json()
            candidate = body["promotion"]
            assert body["review_required"] is True
            assert not (workspace / relative).exists()
            assert str(workspace) not in candidate["content"]
            assert "very-secret-value" not in candidate["content"]
            assert "raw patch must not be promoted" not in candidate["content"]
            assert "raw_tool_result" not in candidate["content"]
            assert candidate["parameters"]["selected_files"] == ["src/app.py"]
            assert candidate["provenance"]["source_run_id"] == run.id

            applied = client.post(
                f"/api/runs/{run.id}/promotions/apply",
                json={
                    "kind": kind,
                    "target_id": target_id,
                    "content": candidate["content"],
                    "source_hash": candidate["source_hash"],
                    "review_token": candidate["review_token"],
                },
            )
            assert applied.status_code == 200
            saved = workspace / relative
            assert saved.exists()
            assert yaml.safe_load(saved.read_text(encoding="utf-8"))


def test_run_promotion_rejects_unreviewed_edits_and_stale_target(tmp_path) -> None:
    app, workspace, run = _app_with_run(tmp_path)
    with TestClient(app) as client:
        preview = client.post(
            f"/api/runs/{run.id}/promotions/preview",
            json={"kind": "workflow", "target_id": "reviewed-workflow"},
        ).json()["promotion"]
        unreviewed = client.post(
            f"/api/runs/{run.id}/promotions/apply",
            json={
                "kind": "workflow",
                "target_id": "reviewed-workflow",
                "content": preview["content"] + "\n# changed after review\n",
                "source_hash": preview["source_hash"],
                "review_token": preview["review_token"],
            },
        )
        assert unreviewed.status_code == 400

        path = workspace / ".giga/workflows/reviewed-workflow.yaml"
        path.write_text(preview["content"], encoding="utf-8")
        stale = client.post(
            f"/api/runs/{run.id}/promotions/apply",
            json={
                "kind": "workflow",
                "target_id": "reviewed-workflow",
                "content": preview["content"],
                "source_hash": preview["source_hash"],
                "review_token": preview["review_token"],
            },
        )
        assert stale.status_code == 409
