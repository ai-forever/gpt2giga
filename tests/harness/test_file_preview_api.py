from pathlib import Path

from fastapi.testclient import TestClient

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.generated_files import (
    persist_generated_file,
    persist_generated_image,
)
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


def test_generated_file_preview_serves_only_hashed_harness_files(tmp_path):
    data_dir = tmp_path / "data"
    generated = persist_generated_image(
        data_dir,
        run_id="run-1",
        file_id="image-file-1",
        mime_type="image/jpeg",
        content_base64="Z2VuZXJhdGVkLWpwZWc=",
    )
    client = _client(tmp_path)

    response = client.get(generated["preview_url"])
    escaped = client.get("/api/files/generated/not-a-hash/../../etc/passwd")

    assert response.status_code == 200
    assert response.content == b"generated-jpeg"
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert escaped.status_code == 404


def test_generated_document_is_download_only(tmp_path):
    data_dir = tmp_path / "data"
    generated = persist_generated_file(
        data_dir,
        run_id="run-1",
        file_id="document-file-1",
        mime_type="text/html",
        target="doc",
        content_base64="PGh0bWw+cmVwb3J0PC9odG1sPg==",
    )
    client = _client(tmp_path)

    inline = client.get(generated["download_url"].split("?", 1)[0])
    downloaded = client.get(generated["download_url"])

    assert inline.status_code == 415
    assert downloaded.status_code == 200
    assert downloaded.content == b"<html>report</html>"
    assert downloaded.headers["content-type"] == "application/octet-stream"
    assert downloaded.headers["content-disposition"].startswith("attachment;")
    assert "generated-" in downloaded.headers["content-disposition"]


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            HarnessConfig(data_dir=str(tmp_path / "data")),
            registry=create_default_registry(include_entry_points=False),
        )
    )
