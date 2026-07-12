from pathlib import Path

from fastapi.testclient import TestClient

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.ui.app import create_app


def test_file_preview_serves_workspace_and_temporary_images(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    workspace_image = workspace / "diagram.png"
    workspace_image.write_bytes(b"workspace-png")
    generated_image = tmp_path / "generated" / "cow_in_space.png"
    generated_image.parent.mkdir()
    generated_image.write_bytes(b"generated-png")
    client = _client(tmp_path)

    relative = client.get(
        "/api/files/preview",
        params={"path": "diagram.png", "workspace": str(workspace)},
    )
    generated = client.get(
        "/api/files/preview",
        params={"path": str(generated_image), "workspace": str(workspace)},
    )

    assert relative.status_code == 200
    assert relative.content == b"workspace-png"
    assert relative.headers["content-type"] == "image/png"
    assert relative.headers["cache-control"] == "no-store"
    assert relative.headers["x-content-type-options"] == "nosniff"
    assert generated.status_code == 200
    assert generated.content == b"generated-png"


def test_file_preview_rejects_unsafe_or_unsupported_files(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    secret = tmp_path / ".env"
    secret.write_text("TOKEN=secret\n", encoding="utf-8")
    html = workspace / "page.html"
    html.write_text("<script>alert(1)</script>\n", encoding="utf-8")
    client = _client(tmp_path)

    outside = client.get(
        "/api/files/preview",
        params={"path": "/etc/hosts", "workspace": str(workspace)},
    )
    denied = client.get(
        "/api/files/preview",
        params={"path": str(secret), "workspace": str(workspace)},
    )
    unsupported = client.get(
        "/api/files/preview",
        params={"path": str(html), "workspace": str(workspace)},
    )

    assert outside.status_code == 403
    assert denied.status_code == 403
    assert unsupported.status_code == 415


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            HarnessConfig(data_dir=str(tmp_path / "data")),
            registry=create_default_registry(include_entry_points=False),
        )
    )
