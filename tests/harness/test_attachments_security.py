import json
import shutil
import subprocess

import pytest

from gpt2giga.harness.attachments import (
    AttachmentLimits,
    AttachmentSessionNotFoundError,
    AttachmentValidationError,
    FilesystemAttachmentStore,
)
from gpt2giga.harness.sessions import FilesystemHarnessSessionStore
from gpt2giga.harness.types import REDACTED


def test_upload_denies_secret_filenames(tmp_path):
    session_store = FilesystemHarnessSessionStore(tmp_path)
    session = session_store.create_session(title="secrets")
    store = FilesystemAttachmentStore(tmp_path)

    with pytest.raises(AttachmentValidationError, match="denied"):
        store.create_upload(
            session_id=session.id,
            project_id=None,
            filename="../.env",
            data=b"GIGACHAT_CREDENTIALS=value",
        )


def test_upload_denies_private_key_payload(tmp_path):
    session_store = FilesystemHarnessSessionStore(tmp_path)
    session = session_store.create_session(title="keys")
    store = FilesystemAttachmentStore(tmp_path)

    with pytest.raises(AttachmentValidationError, match="Private key"):
        store.create_upload(
            session_id=session.id,
            project_id=None,
            filename="note.txt",
            data=b"-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----",
            mime_type="text/plain",
        )


def test_workspace_reference_denies_private_key_payload(tmp_path):
    session_store = FilesystemHarnessSessionStore(tmp_path / "data")
    session = session_store.create_session(title="workspace key")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "note.txt").write_text(
        "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----",
        encoding="utf-8",
    )
    store = FilesystemAttachmentStore(tmp_path / "data")

    with pytest.raises(AttachmentValidationError, match="Private key"):
        store.create_workspace_reference(
            session_id=session.id,
            project_id=None,
            workspace_root=workspace,
            path="note.txt",
        )


def test_upload_rejects_unsafe_project_id(tmp_path):
    session_store = FilesystemHarnessSessionStore(tmp_path)
    session = session_store.create_session(title="project id")
    store = FilesystemAttachmentStore(tmp_path)

    with pytest.raises(AttachmentValidationError, match="Project id"):
        store.create_upload(
            session_id=session.id,
            project_id="../outside",
            filename="note.txt",
            data=b"hello",
            mime_type="text/plain",
        )


def test_metadata_is_redacted_before_disk_write(tmp_path):
    secret = "sk-test-super-secret-123"
    session_store = FilesystemHarnessSessionStore(tmp_path)
    session = session_store.create_session(title="redaction")
    store = FilesystemAttachmentStore(tmp_path)

    attachment = store.create_upload(
        session_id=session.id,
        project_id="proj_demo",
        filename="note.txt",
        data=b"hello",
        mime_type="text/plain",
        metadata={
            "api_key": secret,
            "headers": {"Authorization": f"Bearer {secret}"},
        },
    )

    disk_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in tmp_path.rglob("*")
        if path.is_file() and path.name != "original"
    )
    assert secret not in disk_text
    assert REDACTED in disk_text
    assert store.get_attachment(attachment.id).metadata["api_key"] == REDACTED


def test_workspace_reference_rejects_path_escape_and_env_files(tmp_path):
    session_store = FilesystemHarnessSessionStore(tmp_path / "data")
    session = session_store.create_session(title="workspace")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    store = FilesystemAttachmentStore(tmp_path / "data")

    with pytest.raises(AttachmentValidationError, match="escapes"):
        store.create_workspace_reference(
            session_id=session.id,
            project_id=None,
            workspace_root=workspace,
            path=outside,
        )

    with pytest.raises(AttachmentValidationError, match="denied"):
        store.create_workspace_reference(
            session_id=session.id,
            project_id=None,
            workspace_root=workspace,
            path=".env",
        )


def test_workspace_reference_respects_gitignore_when_available(tmp_path):
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not installed")
    session_store = FilesystemHarnessSessionStore(tmp_path / "data")
    session = session_store.create_session(title="gitignore")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    subprocess.run((git, "init"), cwd=workspace, check=True, capture_output=True)
    (workspace / ".gitignore").write_text("ignored.log\n", encoding="utf-8")
    (workspace / "ignored.log").write_text("ignored", encoding="utf-8")
    store = FilesystemAttachmentStore(tmp_path / "data")

    with pytest.raises(AttachmentValidationError, match="ignored by git"):
        store.create_workspace_reference(
            session_id=session.id,
            project_id=None,
            workspace_root=workspace,
            path="ignored.log",
        )


def test_binary_upload_requires_explicit_allowance(tmp_path):
    session_store = FilesystemHarnessSessionStore(tmp_path)
    session = session_store.create_session(title="binary")
    store = FilesystemAttachmentStore(tmp_path)

    with pytest.raises(AttachmentValidationError, match="Binary attachments"):
        store.create_upload(
            session_id=session.id,
            project_id=None,
            filename="blob.bin",
            data=b"\x00\xff\x00",
        )

    attachment = store.create_upload(
        session_id=session.id,
        project_id=None,
        filename="blob.bin",
        data=b"\x00\xff\x00",
        limits=AttachmentLimits(allow_binary=True),
    )
    assert attachment.kind == "binary"


def test_unknown_session_is_rejected(tmp_path):
    store = FilesystemAttachmentStore(tmp_path)

    with pytest.raises(AttachmentSessionNotFoundError):
        store.create_upload(
            session_id="sess_missing",
            project_id=None,
            filename="note.txt",
            data=b"hello",
            mime_type="text/plain",
        )


def test_attachment_index_can_be_rebuilt(tmp_path):
    session_store = FilesystemHarnessSessionStore(tmp_path)
    session = session_store.create_session(title="index")
    store = FilesystemAttachmentStore(tmp_path)
    attachment = store.create_upload(
        session_id=session.id,
        project_id=None,
        filename="note.txt",
        data=b"hello",
        mime_type="text/plain",
    )
    index_path = tmp_path / "attachments" / "index.json"
    index_path.write_text(json.dumps({"attachments": "bad"}), encoding="utf-8")

    assert store.get_attachment(attachment.id).id == attachment.id
