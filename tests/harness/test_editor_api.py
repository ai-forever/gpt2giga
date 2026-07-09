from fastapi.testclient import TestClient

from gpt2giga.harness.config import HarnessConfig
from gpt2giga.harness.registry import create_default_registry
from gpt2giga.harness.sessions import InMemoryHarnessSessionStore
from gpt2giga.harness.types import GigaChatApiMode, HarnessCapability
from gpt2giga.harness.ui.app import create_app


def test_editor_open_file_api_builds_dry_run_command(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "app.py").write_text("print('ok')\n", encoding="utf-8")
    _write_editor_config(workspace, 'command = "code --reuse-window"\n')
    client = _client(tmp_path / "data")

    response = client.post(
        "/api/editor/open-file",
        json={
            "workspace": str(workspace),
            "path": "app.py",
            "line": 3,
            "dry_run": True,
        },
    )

    assert response.status_code == 200
    editor = response.json()["editor"]
    assert editor["kind"] == "file"
    assert editor["command"][:3] == ["code", "--reuse-window", "--goto"]
    assert editor["command"][3].endswith("app.py:3:1")
    assert editor["executed"] is False


def test_editor_open_file_api_rejects_path_escape(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("", encoding="utf-8")
    client = _client(tmp_path / "data")

    response = client.post(
        "/api/editor/open-file",
        json={
            "workspace": str(workspace),
            "path": str(outside),
            "dry_run": True,
        },
    )

    assert response.status_code == 400
    assert "inside the workspace" in response.json()["detail"]


def test_editor_open_diff_api_writes_patch_file(tmp_path):
    store = InMemoryHarnessSessionStore()
    workspace = tmp_path / "repo"
    workspace.mkdir()
    session = store.create_session(title="Diff", workspace=str(workspace))
    run = store.create_run(
        session_id=session.id,
        harness_id="echo",
        prompt="edit",
        model=None,
        api_mode=GigaChatApiMode.V2,
        capability=HarnessCapability.CHAT_COMPLETIONS,
        mode="edit",
        workspace=str(workspace),
        status="succeeded",
        metadata={
            "workspace_execution": {
                "policy": "worktree",
                "source_workspace": str(workspace),
                "patch": "diff --git a/app.py b/app.py\n",
                "changed_files": ["app.py"],
            }
        },
    )
    client = _client(tmp_path / "data", store=store)

    response = client.post(
        "/api/editor/open-diff",
        json={"run_id": run.id, "dry_run": True},
    )

    assert response.status_code == 200
    editor = response.json()["editor"]
    assert editor["kind"] == "diff"
    assert editor["target_path"].endswith(f"{run.id}.diff")
    assert "diff --git a/app.py b/app.py" in (
        tmp_path / "data" / "editor" / "diffs" / f"{run.id}.diff"
    ).read_text(encoding="utf-8")


def _client(
    data_dir,
    *,
    store: InMemoryHarnessSessionStore | None = None,
) -> TestClient:
    app = create_app(
        HarnessConfig(data_dir=str(data_dir)),
        registry=create_default_registry(include_entry_points=False),
        store=store or InMemoryHarnessSessionStore(),
    )
    return TestClient(app)


def _write_editor_config(workspace, editor_block: str) -> None:
    config_path = workspace / ".giga" / "harness.toml"
    config_path.parent.mkdir()
    config_path.write_text(f"[editor]\n{editor_block}", encoding="utf-8")
