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


def test_generated_html_has_sandboxed_preview_and_keeps_download(tmp_path):
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
    previewed = client.get(
        generated["download_url"].split("?", 1)[0], params={"preview": "html"}
    )
    downloaded = client.get(generated["download_url"])

    assert inline.status_code == 415
    assert previewed.status_code == 200
    assert b'<meta http-equiv="Content-Security-Policy"' in previewed.content
    assert previewed.text.startswith(
        '<html><head><meta http-equiv="Content-Security-Policy"'
    )
    assert b"report</html>" in previewed.content
    assert previewed.headers["content-type"] == "text/html; charset=utf-8"
    assert "sandbox allow-scripts" in previewed.headers["content-security-policy"]
    assert "allow-same-origin" not in previewed.headers["content-security-policy"]
    assert (
        "script-src 'unsafe-inline' 'unsafe-eval' blob: data:"
        in (previewed.headers["content-security-policy"])
    )
    assert "connect-src 'none'" in previewed.headers["content-security-policy"]
    assert "default-src 'none'" in previewed.headers["content-security-policy"]
    assert previewed.headers["referrer-policy"] == "no-referrer"
    assert "content-disposition" not in previewed.headers
    assert downloaded.status_code == 200
    assert downloaded.content == b"<html>report</html>"
    assert downloaded.headers["content-type"] == "application/octet-stream"
    assert downloaded.headers["content-disposition"].startswith("attachment;")
    assert "generated-" in downloaded.headers["content-disposition"]


def test_generated_html_preview_prefixes_fragments_with_embedded_policy(tmp_path):
    generated = persist_generated_file(
        tmp_path / "data",
        run_id="run-1",
        file_id="fragment-file-1",
        mime_type="text/html",
        target="doc",
        content_base64="PGgxPlJlcG9ydDwvaDE+",
    )
    client = _client(tmp_path)

    previewed = client.get(
        generated["download_url"].split("?", 1)[0], params={"preview": "html"}
    )

    assert previewed.status_code == 200
    assert previewed.text.startswith('<head><meta http-equiv="Content-Security-Policy"')
    assert '<meta name="referrer" content="no-referrer">' in previewed.text
    assert previewed.text.endswith("<h1>Report</h1>")


def test_generated_html_preview_rejects_conflicting_or_non_html_requests(tmp_path):
    data_dir = tmp_path / "data"
    generated = persist_generated_file(
        data_dir,
        run_id="run-1",
        file_id="document-file-1",
        mime_type="text/plain",
        target="file",
        content_base64="cmVwb3J0",
    )
    client = _client(tmp_path)

    previewed = client.get(
        generated["download_url"].split("?", 1)[0], params={"preview": "html"}
    )
    conflicting = client.get(
        generated["download_url"].split("?", 1)[0],
        params={"download": generated["filename"], "preview": "html"},
    )

    assert previewed.status_code == 415
    assert conflicting.status_code == 400


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            HarnessConfig(data_dir=str(tmp_path / "data")),
            registry=create_default_registry(include_entry_points=False),
        )
    )
