"""Persistent index for discovered and managed native harness sessions."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol

from gpt2giga_harness.native.models import NativeSessionRef, NativeSessionStatus
from gpt2giga_harness.sessions.redaction import redact_for_storage
from gpt2giga_harness.sessions.store import new_id

INDEX_FILE = "index.json"
TRANSCRIPT_METADATA_KEYS = frozenset(
    {
        "conversation",
        "messages",
        "preview",
        "prompt",
        "raw_request",
        "raw_response",
        "raw_transcript",
        "response",
        "responses",
        "tool_calls",
        "tool_results",
        "transcript",
    }
)


class NativeSessionIndexStore(Protocol):
    """Persistence contract for native session discovery metadata."""

    def upsert_ref(
        self,
        ref: NativeSessionRef,
        *,
        project_id: str | None = None,
    ) -> NativeSessionRef:
        """Create or replace one native session reference."""

    def get_ref(self, ref_id: str) -> NativeSessionRef | None:
        """Return one native session reference by stable index id."""

    def list_refs(
        self,
        *,
        harness_id: str | None = None,
        workspace: str | None = None,
        project_id: str | None = None,
        status: NativeSessionStatus | str | None = None,
        limit: int | None = None,
    ) -> tuple[NativeSessionRef, ...]:
        """List native session references newest first."""

    def delete_ref(self, ref_id: str) -> bool:
        """Delete one native session reference if it exists."""


class FilesystemNativeSessionIndexStore:
    """Store native session refs as a transparent JSON index."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).expanduser()
        self.native_dir = self.data_dir / "native"
        self.index_path = self.native_dir / INDEX_FILE

    def upsert_ref(
        self,
        ref: NativeSessionRef,
        *,
        project_id: str | None = None,
    ) -> NativeSessionRef:
        """Create or replace one native session reference."""
        stored = _redacted_ref(_with_project_id(ref, project_id))
        refs = {existing.id: existing for existing in self._read_refs()}
        refs[stored.id] = stored
        self._write_refs(refs.values())
        return stored

    def get_ref(self, ref_id: str) -> NativeSessionRef | None:
        """Return one native session reference by stable index id."""
        for ref in self._read_refs():
            if ref.id == ref_id:
                return ref
        return None

    def list_refs(
        self,
        *,
        harness_id: str | None = None,
        workspace: str | None = None,
        project_id: str | None = None,
        status: NativeSessionStatus | str | None = None,
        limit: int | None = None,
    ) -> tuple[NativeSessionRef, ...]:
        """List native session references newest first."""
        expected_status = _parse_status(status) if status is not None else None
        refs = [
            ref
            for ref in self._read_refs()
            if _matches_ref(
                ref,
                harness_id=harness_id,
                workspace=workspace,
                project_id=project_id,
                status=expected_status,
            )
        ]
        refs.sort(key=lambda ref: (ref.updated_at or ref.created_at or "", ref.id))
        refs.reverse()
        if limit is not None:
            refs = refs[: max(limit, 0)]
        return tuple(refs)

    def delete_ref(self, ref_id: str) -> bool:
        """Delete one native session reference if it exists."""
        refs = [ref for ref in self._read_refs() if ref.id != ref_id]
        removed = len(refs) != len(self._read_refs())
        if removed:
            self._write_refs(refs)
        return removed

    def _read_refs(self) -> tuple[NativeSessionRef, ...]:
        try:
            data = _read_json(self.index_path)
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            return ()
        raw_refs = data.get("sessions", ())
        if not isinstance(raw_refs, list):
            return ()
        refs: list[NativeSessionRef] = []
        for item in raw_refs:
            if not isinstance(item, Mapping):
                continue
            try:
                refs.append(native_session_ref_from_dict(item))
            except (KeyError, TypeError, ValueError):
                continue
        return tuple(refs)

    def _write_refs(self, refs: Iterable[NativeSessionRef]) -> None:
        payload = {
            "sessions": [
                native_session_ref_to_dict(ref)
                for ref in sorted(refs, key=lambda item: item.id)
            ]
        }
        _write_json_atomic(self.index_path, payload)


def native_session_ref_to_dict(ref: NativeSessionRef) -> dict[str, Any]:
    """Serialize a native session ref for disk and API responses."""
    return {
        "id": ref.id,
        "harness_id": ref.harness_id,
        "native_session_id": ref.native_session_id,
        "title": ref.title,
        "workspace": ref.workspace,
        "source": ref.source,
        "status": ref.status.value,
        "created_at": ref.created_at,
        "updated_at": ref.updated_at,
        "message_count": ref.message_count,
        "can_preview": ref.can_preview,
        "can_import": ref.can_import,
        "can_resume": ref.can_resume,
        "resume_reason": ref.resume_reason,
        "metadata": _metadata_only(ref.metadata),
    }


def native_session_ref_from_dict(data: Mapping[str, Any]) -> NativeSessionRef:
    """Parse a native session ref from JSON-compatible data."""
    return NativeSessionRef(
        id=str(data["id"]),
        harness_id=str(data["harness_id"]),
        native_session_id=_optional_text(data.get("native_session_id")),
        title=str(data.get("title") or "Untitled native session"),
        workspace=_optional_text(data.get("workspace")),
        source=str(data.get("source") or "unknown"),
        status=_parse_status(data.get("status")),
        created_at=_optional_text(data.get("created_at")),
        updated_at=_optional_text(data.get("updated_at")),
        message_count=_optional_int(data.get("message_count")),
        can_preview=bool(data.get("can_preview")),
        can_import=bool(data.get("can_import")),
        can_resume=bool(data.get("can_resume")),
        resume_reason=_optional_text(data.get("resume_reason")),
        metadata=_metadata_only(_mapping(data.get("metadata"))),
    )


def _redacted_ref(ref: NativeSessionRef) -> NativeSessionRef:
    payload = redact_for_storage(native_session_ref_to_dict(ref))
    if isinstance(payload, Mapping):
        return native_session_ref_from_dict(payload)
    return ref


def _with_project_id(
    ref: NativeSessionRef,
    project_id: str | None,
) -> NativeSessionRef:
    if project_id is None:
        return ref
    metadata = dict(ref.metadata)
    metadata["project_id"] = project_id
    return replace(ref, metadata=metadata)


def _matches_ref(
    ref: NativeSessionRef,
    *,
    harness_id: str | None,
    workspace: str | None,
    project_id: str | None,
    status: NativeSessionStatus | None,
) -> bool:
    if harness_id is not None and ref.harness_id != harness_id:
        return False
    if workspace is not None and ref.workspace != workspace:
        return False
    if project_id is not None and ref.metadata.get("project_id") != project_id:
        return False
    if status is not None and ref.status is not status:
        return False
    return True


def _metadata_only(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): _metadata_value(item)
        for key, item in value.items()
        if _metadata_key(str(key)) not in TRANSCRIPT_METADATA_KEYS
    }


def _metadata_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return dict(_metadata_only(value))
    if isinstance(value, tuple):
        return tuple(_metadata_value(item) for item in value)
    if isinstance(value, list):
        return [_metadata_value(item) for item in value]
    return value


def _metadata_key(key: str) -> str:
    return key.strip().lower().replace("-", "_")


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _parse_status(value: Any) -> NativeSessionStatus:
    if isinstance(value, NativeSessionStatus):
        return value
    if value is None or not str(value).strip():
        return NativeSessionStatus.READONLY
    return NativeSessionStatus(str(value).strip().lower())


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return data


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
