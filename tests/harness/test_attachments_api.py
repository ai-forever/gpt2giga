import base64
import hashlib

from fastapi.testclient import TestClient

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.harnesses.base import BaseHarness
from gpt2giga_harness.project import project_id_for_root
from gpt2giga_harness.registry import HarnessRegistry, create_default_registry
from gpt2giga_harness.sessions import FilesystemHarnessSessionStore
from gpt2giga_harness.types import (
    Availability,
    HarnessCapability,
    HarnessRequest,
    HarnessResult,
    HarnessSpec,
)
from gpt2giga_harness.ui.app import create_app

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def test_attachments_api_upload_list_fetch_metadata_and_delete(tmp_path):
    client = _client(tmp_path / "data")
    session_id = _create_session(client)

    uploaded = client.post(
        f"/api/sessions/{session_id}/attachments",
        json={
            "filename": "screenshot.png",
            "mime_type": "image/png",
            "data_base64": base64.b64encode(PNG_BYTES).decode("ascii"),
            "source": "paste",
            "metadata": {"caption": "screen"},
        },
    )

    assert uploaded.status_code == 200
    attachment = uploaded.json()["attachment"]
    attachment_id = attachment["id"]
    assert attachment["kind"] == "image"
    assert attachment["source"] == "paste"
    assert attachment["sha256"] == hashlib.sha256(PNG_BYTES).hexdigest()
    assert attachment["url"] == f"/api/attachments/{attachment_id}"
    assert attachment["supported_by"]["direct-chat"] is True
    assert attachment["supported_by"]["echo"] is True
    assert attachment["transport_by"]["codex-cli"]["rich"] is True
    assert attachment["transport_by"]["codex-cli"]["required_cli_capabilities"] == [
        "--image"
    ]
    assert attachment["transport_by"]["claude-code"]["rich"] is False
    assert (
        "claude-code uses path or metadata reference only for image attachments."
        in attachment["warnings"]
    )
    assert "storage_path" not in attachment

    listed = client.get(f"/api/sessions/{session_id}/attachments")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["attachments"]] == [attachment_id]

    metadata = client.get(f"/api/attachments/{attachment_id}/metadata")
    assert metadata.status_code == 200
    assert metadata.json()["attachment"]["id"] == attachment_id
    assert "storage_path" not in metadata.json()["attachment"]

    blob = client.get(f"/api/attachments/{attachment_id}")
    assert blob.status_code == 200
    assert blob.content == PNG_BYTES
    assert blob.headers["content-type"] == "image/png"

    deleted = client.delete(f"/api/attachments/{attachment_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}
    assert client.get(f"/api/attachments/{attachment_id}/metadata").status_code == 404
    assert client.get(f"/api/sessions/{session_id}/attachments").json() == {
        "attachments": []
    }


def test_attachments_api_creates_workspace_reference(tmp_path):
    data_dir = tmp_path / "data"
    workspace = tmp_path / "repo"
    workspace.mkdir()
    source = workspace / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("print('hello')\n", encoding="utf-8")
    client = _client(data_dir)
    session_id = _create_session(client, workspace=str(workspace))

    response = client.post(
        f"/api/sessions/{session_id}/attachments/workspace",
        json={"workspace": str(workspace), "path": "src/app.py"},
    )

    assert response.status_code == 200
    attachment = response.json()["attachment"]
    assert attachment["kind"] == "workspace_file"
    assert attachment["workspace_path"] == "src/app.py"
    assert attachment["project_id"] == project_id_for_root(workspace)
    assert attachment["supported_by"]["codex-cli"] is True
    assert attachment["supported_by"]["direct-chat"] is True
    assert "storage_path" not in attachment

    blob = client.get(f"/api/attachments/{attachment['id']}")
    assert blob.status_code == 400
    assert "no stored blob" in blob.json()["detail"]


def test_session_attachment_search_is_bounded_and_hides_workspace_root(tmp_path):
    data_dir = tmp_path / "data"
    workspace = tmp_path / "repo"
    workspace.mkdir()
    source = workspace / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("print('hello')\n", encoding="utf-8")
    (workspace / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    client = _client(data_dir)
    session_id = _create_session(client, workspace=str(workspace))

    response = client.get(
        f"/api/sessions/{session_id}/attachments/workspace/search",
        params={"q": "@src", "limit": 1},
    )

    assert response.status_code == 200
    assert response.json() == {
        "q": "@src",
        "files": [
            {
                "path": "src/app.py",
                "name": "app.py",
                "mime_type": "text/x-python",
                "kind": "text",
                "size_bytes": source.stat().st_size,
            }
        ],
        "bounded": True,
    }
    assert str(workspace) not in response.text
    assert ".env" not in response.text


def test_attachments_api_rejects_unsafe_upload_without_leaking_payload(tmp_path):
    client = _client(tmp_path / "data")
    session_id = _create_session(client)
    secret = "GIGACHAT_CREDENTIALS=super-secret"

    response = client.post(
        f"/api/sessions/{session_id}/attachments",
        json={
            "filename": ".env",
            "data_base64": base64.b64encode(secret.encode()).decode("ascii"),
        },
    )

    assert response.status_code == 400
    assert "denied" in response.json()["detail"]
    assert "super-secret" not in response.text


def test_attachments_api_rejects_invalid_base64(tmp_path):
    client = _client(tmp_path / "data")
    session_id = _create_session(client)

    response = client.post(
        f"/api/sessions/{session_id}/attachments",
        json={"filename": "note.txt", "data_base64": "not base64%%%"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "data_base64 is invalid"


def test_attachments_api_reports_unsupported_harnesses(tmp_path):
    registry = create_default_registry(include_entry_points=False)
    registry.register(_PlainHarness())
    client = _client(tmp_path / "data", registry=registry)
    session_id = _create_session(client)

    response = client.post(
        f"/api/sessions/{session_id}/attachments",
        json={
            "filename": "note.txt",
            "mime_type": "text/plain",
            "data_base64": base64.b64encode(b"hello").decode("ascii"),
        },
    )

    assert response.status_code == 200
    attachment = response.json()["attachment"]
    assert attachment["supported_by"]["plain"] is False
    assert "plain does not support attachments." in attachment["warnings"]


def test_attachments_api_unknown_session_and_attachment_return_404(tmp_path):
    client = _client(tmp_path / "data")

    upload = client.post(
        "/api/sessions/sess_missing/attachments",
        json={
            "filename": "note.txt",
            "data_base64": base64.b64encode(b"hello").decode("ascii"),
        },
    )
    assert upload.status_code == 404

    assert client.get("/api/attachments/att_missing/metadata").status_code == 404
    delete = client.delete("/api/attachments/att_missing")
    assert delete.status_code == 404


def _create_session(client: TestClient, *, workspace: str | None = None) -> str:
    payload = {"title": "attachments", "harness_id": "echo"}
    if workspace is not None:
        payload["workspace"] = workspace
    response = client.post("/api/sessions", json=payload)
    assert response.status_code == 200
    return str(response.json()["session"]["id"])


def _client(data_dir, *, registry: HarnessRegistry | None = None) -> TestClient:
    app = create_app(
        HarnessConfig(data_dir=str(data_dir)),
        registry=registry or create_default_registry(include_entry_points=False),
        store=FilesystemHarnessSessionStore(data_dir),
    )
    return TestClient(app)


class _PlainHarness(BaseHarness):
    @classmethod
    def spec(cls) -> HarnessSpec:
        return HarnessSpec(
            id="plain",
            title="Plain",
            kind="test",
            description="Harness without attachments",
            capabilities=(HarnessCapability.CHAT_COMPLETIONS,),
        )

    def availability(self) -> Availability:
        return Availability.available("test harness")

    def run(
        self,
        request: HarnessRequest,
        context,
    ) -> HarnessResult:
        return HarnessResult(ok=True, text=request.prompt)
