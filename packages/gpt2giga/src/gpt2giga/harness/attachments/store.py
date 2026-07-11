"""Filesystem storage for normalized harness attachments."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Mapping

from gpt2giga.harness.attachments.limits import (
    AttachmentLimits,
    AttachmentValidationError,
    normalize_workspace_file,
    safe_upload_filename,
    validate_size,
)
from gpt2giga.harness.attachments.mime import (
    detect_attachment_kind,
    detect_mime_type,
)
from gpt2giga.harness.attachments.models import (
    AttachmentKind,
    HarnessAttachment,
    attachment_from_dict,
    attachment_to_dict,
)
from gpt2giga.harness.sessions.redaction import redact_for_storage
from gpt2giga.harness.sessions.store import new_id, utc_now

SESSIONS_INDEX_FILE = "index.json"
SESSION_ATTACHMENTS_FILE = "attachments.jsonl"
ATTACHMENTS_INDEX_FILE = "index.json"
BLOB_FILE = "original"
BLOB_METADATA_FILE = "metadata.json"
DEFAULT_LIMITS = AttachmentLimits()
PRIVATE_KEY_MARKER = b"-----BEGIN "
PROJECT_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


class AttachmentNotFoundError(KeyError):
    """Raised when an attachment id cannot be found."""


class AttachmentSessionNotFoundError(KeyError):
    """Raised when an attachment is stored for an unknown session."""


class FilesystemAttachmentStore:
    """Persist attachment metadata and uploaded blobs below harness data dir."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).expanduser()
        self.sessions_dir = self.data_dir / "sessions"
        self.global_attachments_dir = self.data_dir / "attachments"

    def create_upload(
        self,
        *,
        session_id: str,
        project_id: str | None,
        filename: str,
        data: bytes,
        mime_type: str | None = None,
        source: str = "upload",
        metadata: Mapping[str, Any] | None = None,
        limits: AttachmentLimits = DEFAULT_LIMITS,
    ) -> HarnessAttachment:
        """Store an uploaded or pasted file as a content-addressed blob."""
        name = safe_upload_filename(filename, limits)
        payload = bytes(data)
        self._validate_private_key_payload(payload)
        self._validate_total_size(session_id, len(payload), limits)
        detected_mime = detect_mime_type(name, mime_type, payload)
        kind = detect_attachment_kind(name, detected_mime, payload)
        self._validate_kind(kind, limits)
        sha256 = hashlib.sha256(payload).hexdigest()
        blob_path = self._blob_path(project_id, sha256)
        if not blob_path.exists():
            _write_bytes_atomic(blob_path, payload)
        attachment = HarnessAttachment(
            id=new_id("att"),
            session_id=session_id,
            project_id=project_id,
            kind=kind.value,
            filename=name,
            mime_type=detected_mime,
            size_bytes=len(payload),
            sha256=sha256,
            source=source,
            storage_path=str(blob_path),
            created_at=utc_now(),
            metadata=self._redacted_mapping(metadata),
        )
        self._write_blob_metadata(attachment)
        return self._append_attachment(attachment)

    def create_workspace_reference(
        self,
        *,
        session_id: str,
        project_id: str | None,
        workspace_root: str | Path,
        path: str | Path,
        mime_type: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        limits: AttachmentLimits = DEFAULT_LIMITS,
    ) -> HarnessAttachment:
        """Store a reference to a safe file inside the current workspace."""
        resolved, relative = normalize_workspace_file(workspace_root, path, limits)
        size = resolved.stat().st_size
        self._validate_total_size(session_id, size, limits)
        sample = _read_sample(resolved)
        self._validate_private_key_payload(sample)
        detected_mime = detect_mime_type(relative, mime_type, sample)
        detected_kind = detect_attachment_kind(relative, detected_mime, sample)
        self._validate_kind(detected_kind, limits)
        sha256 = _sha256_file(resolved)
        combined_metadata: dict[str, Any] = {
            "detected_kind": detected_kind.value,
            "workspace_root": str(Path(workspace_root).expanduser().resolve()),
        }
        if metadata:
            combined_metadata.update(metadata)
        attachment = HarnessAttachment(
            id=new_id("att"),
            session_id=session_id,
            project_id=project_id,
            kind=AttachmentKind.WORKSPACE_FILE.value,
            filename=Path(relative).name,
            mime_type=detected_mime,
            size_bytes=size,
            sha256=sha256,
            source="workspace",
            workspace_path=relative,
            created_at=utc_now(),
            metadata=self._redacted_mapping(combined_metadata),
        )
        return self._append_attachment(attachment)

    def list_session_attachments(
        self,
        session_id: str,
    ) -> tuple[HarnessAttachment, ...]:
        """List attachments associated with a session."""
        path = self._session_attachments_path(session_id)
        return tuple(_read_jsonl(path, attachment_from_dict))

    def get_attachment(self, attachment_id: str) -> HarnessAttachment:
        """Return one attachment by id."""
        session_id = self._attachment_index().get(attachment_id)
        if session_id is None:
            self._rebuild_attachment_index()
            session_id = self._attachment_index().get(attachment_id)
        if session_id is None:
            raise AttachmentNotFoundError(attachment_id)
        for attachment in self.list_session_attachments(session_id):
            if attachment.id == attachment_id:
                return attachment
        self._remove_attachment_index_entry(attachment_id)
        raise AttachmentNotFoundError(attachment_id)

    def delete_attachment(self, attachment_id: str) -> None:
        """Remove a session attachment record while leaving shared blobs intact."""
        attachment = self.get_attachment(attachment_id)
        path = self._session_attachments_path(attachment.session_id)
        remaining = [
            item
            for item in self.list_session_attachments(attachment.session_id)
            if item.id != attachment_id
        ]
        _write_jsonl_atomic(path, [attachment_to_dict(item) for item in remaining])
        self._remove_attachment_index_entry(attachment_id)

    def read_blob(self, attachment_id: str) -> bytes:
        """Read uploaded blob bytes for a stored attachment."""
        attachment = self.get_attachment(attachment_id)
        if not attachment.storage_path:
            raise AttachmentValidationError("Attachment has no stored blob")
        path = Path(attachment.storage_path).expanduser().resolve()
        data_root = self.data_dir.expanduser().resolve()
        if not _is_relative_to(path, data_root) or not path.is_file():
            raise AttachmentValidationError("Attachment blob path is invalid")
        return path.read_bytes()

    def _append_attachment(self, attachment: HarnessAttachment) -> HarnessAttachment:
        stored = replace(
            attachment, metadata=self._redacted_mapping(attachment.metadata)
        )
        self._append_jsonl(
            self._session_attachments_path(stored.session_id),
            attachment_to_dict(stored),
        )
        self._upsert_attachment_index(stored.id, stored.session_id)
        return stored

    def _validate_total_size(
        self,
        session_id: str,
        size_bytes: int,
        limits: AttachmentLimits,
    ) -> None:
        current_total = sum(
            attachment.size_bytes
            for attachment in self.list_session_attachments(session_id)
        )
        validate_size(
            size_bytes,
            current_total_bytes=current_total,
            limits=limits,
        )

    def _validate_kind(
        self,
        kind: AttachmentKind,
        limits: AttachmentLimits,
    ) -> None:
        if kind is AttachmentKind.IMAGE and not limits.allow_images:
            raise AttachmentValidationError("Image attachments are disabled")
        if kind is AttachmentKind.DOCUMENT and not limits.allow_documents:
            raise AttachmentValidationError("Document attachments are disabled")
        if kind is AttachmentKind.BINARY and not limits.allow_binary:
            raise AttachmentValidationError("Binary attachments are disabled")

    def _validate_private_key_payload(self, payload: bytes) -> None:
        if (
            PRIVATE_KEY_MARKER in payload[:65536]
            and b"PRIVATE KEY-----" in payload[:65536]
        ):
            raise AttachmentValidationError("Private key material is not allowed")

    def _blob_path(self, project_id: str | None, sha256: str) -> Path:
        project_key = _safe_project_key(project_id)
        return (
            self.data_dir
            / "projects"
            / project_key
            / "attachments"
            / sha256
            / BLOB_FILE
        )

    def _write_blob_metadata(self, attachment: HarnessAttachment) -> None:
        blob_path = Path(attachment.storage_path or "")
        if not blob_path:
            return
        metadata = {
            "sha256": attachment.sha256,
            "kind": attachment.kind,
            "filename": attachment.filename,
            "mime_type": attachment.mime_type,
            "size_bytes": attachment.size_bytes,
            "created_at": attachment.created_at,
            "metadata": dict(attachment.metadata),
        }
        _write_json_atomic(blob_path.parent / BLOB_METADATA_FILE, metadata)

    def _session_attachments_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / SESSION_ATTACHMENTS_FILE

    def _session_dir(self, session_id: str) -> Path:
        index = self._sessions_index()
        rel_path = index.get(session_id)
        if rel_path is None:
            raise AttachmentSessionNotFoundError(session_id)
        return self.sessions_dir / rel_path

    def _sessions_index(self) -> dict[str, Path]:
        try:
            data = _read_json(self.sessions_dir / SESSIONS_INDEX_FILE)
        except FileNotFoundError as exc:
            raise AttachmentSessionNotFoundError("sessions index is missing") from exc
        sessions = data.get("sessions", [])
        if not isinstance(sessions, list):
            raise AttachmentSessionNotFoundError("sessions index is invalid")
        index: dict[str, Path] = {}
        for item in sessions:
            if not isinstance(item, Mapping):
                continue
            session_id = item.get("id")
            rel_path = item.get("path")
            if session_id and rel_path:
                index[str(session_id)] = Path(str(rel_path))
        return index

    def _attachment_index(self) -> dict[str, str]:
        try:
            data = _read_json(self.global_attachments_dir / ATTACHMENTS_INDEX_FILE)
        except FileNotFoundError:
            return {}
        attachments = data.get("attachments", [])
        if not isinstance(attachments, list):
            return self._rebuild_attachment_index()
        index: dict[str, str] = {}
        for item in attachments:
            if not isinstance(item, Mapping):
                continue
            attachment_id = item.get("id")
            session_id = item.get("session_id")
            if attachment_id and session_id:
                index[str(attachment_id)] = str(session_id)
        return index

    def _upsert_attachment_index(self, attachment_id: str, session_id: str) -> None:
        index = self._attachment_index()
        index[attachment_id] = session_id
        self._write_attachment_index(index)

    def _remove_attachment_index_entry(self, attachment_id: str) -> None:
        index = self._attachment_index()
        if attachment_id in index:
            index.pop(attachment_id, None)
            self._write_attachment_index(index)

    def _rebuild_attachment_index(self) -> dict[str, str]:
        index: dict[str, str] = {}
        if self.sessions_dir.exists():
            for path in self.sessions_dir.glob("*/*/*/" + SESSION_ATTACHMENTS_FILE):
                try:
                    for attachment in _read_jsonl(path, attachment_from_dict):
                        index[attachment.id] = attachment.session_id
                except (OSError, ValueError, json.JSONDecodeError, KeyError):
                    continue
        self._write_attachment_index(index)
        return index

    def _write_attachment_index(self, index: Mapping[str, str]) -> None:
        payload = {
            "attachments": [
                {"id": attachment_id, "session_id": session_id}
                for attachment_id, session_id in sorted(index.items())
            ]
        }
        _write_json_atomic(
            self.global_attachments_dir / ATTACHMENTS_INDEX_FILE, payload
        )

    def _append_jsonl(self, path: Path, payload: Mapping[str, Any]) -> None:
        _append_jsonl(path, redact_for_storage(dict(payload)))

    def _redacted_mapping(self, value: Mapping[str, Any] | None) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            return {}
        redacted = redact_for_storage(dict(value))
        if isinstance(redacted, Mapping):
            return dict(redacted)
        return {}


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return data


def _read_jsonl(
    path: Path,
    parser: Callable[[Mapping[str, Any]], HarnessAttachment],
) -> list[HarnessAttachment]:
    if not path.exists():
        return []
    rows: list[HarnessAttachment] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            decoded = json.loads(text)
            if isinstance(decoded, Mapping):
                rows.append(parser(decoded))
    return rows


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{new_id('tmp')}")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(
            redact_for_storage(dict(payload)),
            handle,
            ensure_ascii=False,
            indent=2,
        )
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, path)


def _write_jsonl_atomic(path: Path, payloads: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{new_id('tmp')}")
    with temp_path.open("w", encoding="utf-8") as handle:
        for payload in payloads:
            handle.write(
                json.dumps(redact_for_storage(dict(payload)), ensure_ascii=False)
            )
            handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, path)


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(redact_for_storage(dict(payload)), ensure_ascii=False))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{new_id('tmp')}")
    with temp_path.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, path)


def _read_sample(path: Path, limit: int = 8192) -> bytes:
    with path.open("rb") as handle:
        return handle.read(limit)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _safe_project_key(project_id: str | None) -> str:
    if project_id is None or not str(project_id).strip():
        return "unassigned"
    value = str(project_id).strip()
    if value in {".", ".."} or not PROJECT_KEY_PATTERN.fullmatch(value):
        raise AttachmentValidationError("Project id is invalid")
    return value
