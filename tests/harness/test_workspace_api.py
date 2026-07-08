from fastapi.testclient import TestClient

from gpt2giga.harness.config import HarnessConfig
from gpt2giga.harness.registry import create_default_registry
from gpt2giga.harness.ui.app import create_app


def test_workspace_tree_lists_safe_matching_files(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "src").mkdir()
    (workspace / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (workspace / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    client = _client(tmp_path)

    response = client.get(
        "/api/workspace/tree",
        params={"workspace": str(workspace), "q": "src"},
    )

    assert response.status_code == 200
    files = response.json()["files"]
    assert [item["path"] for item in files] == ["src/app.py"]
    assert files[0]["kind"] == "text"
    assert files[0]["mime_type"] == "text/x-python"
    assert ".env" not in str(files)


def test_workspace_file_metadata_rejects_unsafe_paths(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "note.txt").write_text("hello\n", encoding="utf-8")
    (workspace / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    client = _client(tmp_path)

    ok = client.get(
        "/api/workspace/file/metadata",
        params={"workspace": str(workspace), "path": "note.txt"},
    )
    denied = client.get(
        "/api/workspace/file/metadata",
        params={"workspace": str(workspace), "path": ".env"},
    )
    escaped = client.get(
        "/api/workspace/file/metadata",
        params={"workspace": str(workspace), "path": str(outside)},
    )

    assert ok.status_code == 200
    assert ok.json()["file"]["path"] == "note.txt"
    assert denied.status_code == 400
    assert "denied" in denied.json()["detail"]
    assert escaped.status_code == 400
    assert "escapes" in escaped.json()["detail"]


def _client(tmp_path):
    app = create_app(
        HarnessConfig(data_dir=str(tmp_path / "data")),
        registry=create_default_registry(include_entry_points=False),
    )
    return TestClient(app)
