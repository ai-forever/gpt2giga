import hashlib
import json

from gpt2giga_harness.attachments import (
    AttachmentLimits,
    AttachmentRenderPlan,
    FilesystemAttachmentStore,
    HarnessAttachment,
    attachment_from_dict,
    attachment_to_dict,
    render_plan_from_dict,
    render_plan_to_dict,
)
from gpt2giga_harness.attachments.mime import (
    detect_attachment_kind,
    detect_mime_type,
)
from gpt2giga_harness.sessions import FilesystemHarnessSessionStore

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def test_upload_persists_content_addressed_blob_and_session_record(tmp_path):
    session_store = FilesystemHarnessSessionStore(tmp_path)
    session = session_store.create_session(title="attachments")
    store = FilesystemAttachmentStore(tmp_path)

    attachment = store.create_upload(
        session_id=session.id,
        project_id="proj_demo",
        filename="screenshot.png",
        mime_type=None,
        data=PNG_BYTES,
        source="paste",
        metadata={"caption": "screen"},
    )

    expected_sha = hashlib.sha256(PNG_BYTES).hexdigest()
    assert attachment.id.startswith("att_")
    assert attachment.kind == "image"
    assert attachment.mime_type == "image/png"
    assert attachment.sha256 == expected_sha
    assert attachment.storage_path == str(
        tmp_path / "projects" / "proj_demo" / "attachments" / expected_sha / "original"
    )
    assert store.read_blob(attachment.id) == PNG_BYTES

    reopened = FilesystemAttachmentStore(tmp_path)
    assert reopened.get_attachment(attachment.id) == attachment
    assert reopened.list_session_attachments(session.id) == (attachment,)

    metadata_path = (
        tmp_path
        / "projects"
        / "proj_demo"
        / "attachments"
        / expected_sha
        / "metadata.json"
    )
    assert (
        json.loads(metadata_path.read_text(encoding="utf-8"))["sha256"] == expected_sha
    )


def test_workspace_reference_stays_as_path_metadata(tmp_path):
    session_store = FilesystemHarnessSessionStore(tmp_path / "data")
    session = session_store.create_session(title="workspace")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    source = workspace / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("print('hello')\n", encoding="utf-8")
    store = FilesystemAttachmentStore(tmp_path / "data")

    attachment = store.create_workspace_reference(
        session_id=session.id,
        project_id="proj_demo",
        workspace_root=workspace,
        path="src/app.py",
    )

    assert attachment.kind == "workspace_file"
    assert attachment.filename == "app.py"
    assert attachment.workspace_path == "src/app.py"
    assert attachment.storage_path is None
    assert attachment.metadata["detected_kind"] == "text"
    assert attachment.sha256 == hashlib.sha256(source.read_bytes()).hexdigest()


def test_attachment_model_and_render_plan_round_trip():
    attachment = HarnessAttachment(
        id="att_1",
        session_id="sess_1",
        project_id=None,
        kind="text",
        filename="note.txt",
        mime_type="text/plain",
        size_bytes=5,
        sha256="abc",
        source="upload",
        created_at="2026-07-08T00:00:00Z",
        metadata={"line_count": 1},
    )
    plan = AttachmentRenderPlan(
        prompt_prefix="prefix",
        content_parts=({"type": "text", "text": "hello"},),
        cli_args=("--image", "path"),
        warnings=("warn",),
        metadata={"transport": "inline_text"},
    )

    assert attachment_from_dict(attachment_to_dict(attachment)) == attachment
    assert render_plan_from_dict(render_plan_to_dict(plan)) == plan


def test_mime_detection_uses_signatures_and_text_extensions():
    assert detect_mime_type("image.bin", None, PNG_BYTES) == "image/png"
    assert (
        detect_attachment_kind("notes.md", "application/octet-stream", b"# hi")
        == "text"
    )
    assert (
        detect_attachment_kind("report.pdf", "application/pdf", b"%PDF-1.7")
        == "document"
    )
    assert (
        detect_attachment_kind("archive.bin", "application/octet-stream", b"\x00\xff")
        == "binary"
    )


def test_upload_enforces_file_and_total_size_limits(tmp_path):
    session_store = FilesystemHarnessSessionStore(tmp_path)
    session = session_store.create_session(title="limits")
    store = FilesystemAttachmentStore(tmp_path)
    limits = AttachmentLimits(
        max_file_bytes=4,
        max_total_bytes_per_run=8,
        allow_binary=True,
    )

    first = store.create_upload(
        session_id=session.id,
        project_id=None,
        filename="first.bin",
        data=b"1234",
        limits=limits,
    )
    assert first.size_bytes == 4

    second = store.create_upload(
        session_id=session.id,
        project_id=None,
        filename="second.bin",
        data=b"1234",
        limits=limits,
    )
    assert second.size_bytes == 4

    try:
        store.create_upload(
            session_id=session.id,
            project_id=None,
            filename="third.bin",
            data=b"1",
            limits=limits,
        )
    except ValueError as exc:
        assert "max total" in str(exc)
    else:
        raise AssertionError("Expected total size validation failure")


def test_delete_removes_session_record_but_keeps_blob(tmp_path):
    session_store = FilesystemHarnessSessionStore(tmp_path)
    session = session_store.create_session(title="delete")
    store = FilesystemAttachmentStore(tmp_path)
    attachment = store.create_upload(
        session_id=session.id,
        project_id="proj_demo",
        filename="note.txt",
        data=b"hello",
        mime_type="text/plain",
    )
    blob_path = attachment.storage_path

    store.delete_attachment(attachment.id)

    assert store.list_session_attachments(session.id) == ()
    assert blob_path is not None
    assert (tmp_path / "projects" / "proj_demo" / "attachments").exists()
    assert (tmp_path / "projects" / "proj_demo" / "attachments").is_dir()
