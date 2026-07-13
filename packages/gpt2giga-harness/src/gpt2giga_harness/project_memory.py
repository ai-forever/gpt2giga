"""Project-scoped memory store for the Unified Harness cockpit."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from gpt2giga_harness.project import HarnessProject
from gpt2giga_harness.sessions.redaction import redact_for_storage

PROJECT_MEMORY_FILE = "memory.jsonl"
MAX_MEMORY_TEXT_CHARS = 4000
MAX_MEMORY_TAGS = 16
MAX_INCLUDED_MEMORY = 20
_UNSET = object()


class ProjectMemoryNotFoundError(KeyError):
    """Raised when a project memory entry does not exist."""


@dataclass(frozen=True)
class ProjectMemoryEntry:
    """One explicit project memory or decision-log entry."""

    id: str
    project_id: str
    text: str
    tags: tuple[str, ...]
    source_session_id: str | None
    source_run_id: str | None
    created_at: str
    updated_at: str
    enabled: bool = True
    manual: bool = True
    confidence: float | None = None
    metadata: Mapping[str, Any] | None = None


class FilesystemProjectMemoryStore:
    """Persist project memory as transparent JSONL."""

    def list(
        self,
        project: HarnessProject,
        *,
        include_disabled: bool = False,
    ) -> tuple[ProjectMemoryEntry, ...]:
        """List project memory entries newest first."""
        entries = self._read_entries(project)
        if not include_disabled:
            entries = [entry for entry in entries if entry.enabled]
        entries.sort(key=lambda entry: entry.updated_at, reverse=True)
        return tuple(entries)

    def enabled_for_prompt(
        self,
        project: HarnessProject,
        *,
        limit: int = MAX_INCLUDED_MEMORY,
    ) -> tuple[ProjectMemoryEntry, ...]:
        """Return enabled entries in stable prompt order."""
        entries = [entry for entry in self._read_entries(project) if entry.enabled]
        entries.sort(key=lambda entry: entry.created_at)
        return tuple(entries[-max(limit, 0) :])

    def add(
        self,
        project: HarnessProject,
        *,
        text: str,
        tags: tuple[str, ...] = (),
        source_session_id: str | None = None,
        source_run_id: str | None = None,
        enabled: bool = True,
        manual: bool = True,
        confidence: float | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ProjectMemoryEntry:
        """Add one memory entry."""
        now = utc_now()
        entry = ProjectMemoryEntry(
            id=new_memory_id(),
            project_id=project.id,
            text=_clean_text(text),
            tags=_clean_tags(tags),
            source_session_id=_optional_text(source_session_id),
            source_run_id=_optional_text(source_run_id),
            created_at=now,
            updated_at=now,
            enabled=bool(enabled),
            manual=bool(manual),
            confidence=_clean_confidence(confidence),
            metadata=_redacted_mapping(metadata),
        )
        entries = self._read_entries(project)
        entries.append(entry)
        self._write_entries(project, entries)
        return entry

    def update(
        self,
        project: HarnessProject,
        entry_id: str,
        *,
        text: str | None = None,
        tags: tuple[str, ...] | None = None,
        enabled: bool | None = None,
        manual: bool | None = None,
        confidence: float | None | object = _UNSET,
        metadata: Mapping[str, Any] | None | object = _UNSET,
    ) -> ProjectMemoryEntry:
        """Patch one memory entry."""
        entries = self._read_entries(project)
        for index, entry in enumerate(entries):
            if entry.id != entry_id:
                continue
            changes: dict[str, Any] = {"updated_at": utc_now()}
            if text is not None:
                changes["text"] = _clean_text(text)
            if tags is not None:
                changes["tags"] = _clean_tags(tags)
            if enabled is not None:
                changes["enabled"] = bool(enabled)
            if manual is not None:
                changes["manual"] = bool(manual)
            if confidence is not _UNSET:
                changes["confidence"] = _clean_confidence(confidence)
            if metadata is not _UNSET:
                changes["metadata"] = _redacted_mapping(metadata)
            updated = replace(entry, **changes)
            entries[index] = updated
            self._write_entries(project, entries)
            return updated
        raise ProjectMemoryNotFoundError(entry_id)

    def delete(self, project: HarnessProject, entry_id: str) -> None:
        """Delete one memory entry."""
        entries = self._read_entries(project)
        kept = [entry for entry in entries if entry.id != entry_id]
        if len(kept) == len(entries):
            raise ProjectMemoryNotFoundError(entry_id)
        self._write_entries(project, kept)

    def _path(self, project: HarnessProject) -> Path:
        return Path(project.state_dir).expanduser() / PROJECT_MEMORY_FILE

    def _read_entries(self, project: HarnessProject) -> list[ProjectMemoryEntry]:
        path = self._path(project)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        entries: list[ProjectMemoryEntry] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                entry = memory_entry_from_dict(payload)
            except (TypeError, ValueError, KeyError, json.JSONDecodeError):
                continue
            if entry.project_id == project.id:
                entries.append(entry)
        return entries

    def _write_entries(
        self,
        project: HarnessProject,
        entries: list[ProjectMemoryEntry],
    ) -> None:
        path = self._path(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = "\n".join(
            json.dumps(memory_entry_to_dict(entry), ensure_ascii=False, sort_keys=True)
            for entry in entries
        )
        path.write_text(f"{payload}\n" if payload else "", encoding="utf-8")


def memory_entry_to_dict(entry: ProjectMemoryEntry) -> dict[str, Any]:
    """Serialize one memory entry for disk and API responses."""
    return {
        "id": entry.id,
        "project_id": entry.project_id,
        "text": str(redact_for_storage(entry.text)),
        "tags": [str(redact_for_storage(tag)) for tag in entry.tags],
        "source_session_id": entry.source_session_id,
        "source_run_id": entry.source_run_id,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        "enabled": entry.enabled,
        "manual": entry.manual,
        "confidence": entry.confidence,
        "metadata": _redacted_mapping(entry.metadata),
    }


def memory_entry_from_dict(data: Mapping[str, Any]) -> ProjectMemoryEntry:
    """Parse one memory entry from JSON-compatible data."""
    created_at = str(data.get("created_at") or utc_now())
    return ProjectMemoryEntry(
        id=str(data["id"]),
        project_id=str(data["project_id"]),
        text=_clean_text(str(data.get("text") or "")),
        tags=_clean_tags(tuple(str(item) for item in data.get("tags", ()))),
        source_session_id=_optional_text(data.get("source_session_id")),
        source_run_id=_optional_text(data.get("source_run_id")),
        created_at=created_at,
        updated_at=str(data.get("updated_at") or created_at),
        enabled=bool(data.get("enabled", True)),
        manual=bool(data.get("manual", True)),
        confidence=_clean_confidence(data.get("confidence")),
        metadata=_redacted_mapping(data.get("metadata")),
    )


def memory_entries_to_prompt(entries: tuple[ProjectMemoryEntry, ...]) -> str:
    """Render enabled project memory for prompt injection."""
    lines: list[str] = []
    for entry in entries:
        tag_text = f" [{', '.join(entry.tags)}]" if entry.tags else ""
        lines.append(f"-{tag_text} {entry.text}")
    return "\n".join(lines)


def memory_entries_to_context(
    entries: tuple[ProjectMemoryEntry, ...],
) -> dict[str, Any]:
    """Serialize included memory for run metadata and raw requests."""
    return {
        "count": len(entries),
        "entries": [memory_entry_to_dict(entry) for entry in entries],
    }


def new_memory_id() -> str:
    """Return a compact project memory id."""
    return f"mem_{uuid4().hex}"


def utc_now() -> str:
    """Return a stable UTC timestamp."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clean_text(text: str) -> str:
    clean = " ".join(str(redact_for_storage(text)).split())
    if not clean:
        raise ValueError("memory text is required")
    if len(clean) > MAX_MEMORY_TEXT_CHARS:
        clean = clean[:MAX_MEMORY_TEXT_CHARS].rstrip()
    return clean


def _clean_tags(tags: tuple[str, ...]) -> tuple[str, ...]:
    cleaned: list[str] = []
    for tag in tags:
        text = str(redact_for_storage(tag)).strip().lower()
        if not text:
            continue
        text = text.replace(" ", "-")[:64]
        if text not in cleaned:
            cleaned.append(text)
        if len(cleaned) >= MAX_MEMORY_TAGS:
            break
    return tuple(cleaned)


def _clean_confidence(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    if number < 0 or number > 1:
        raise ValueError("memory confidence must be between 0 and 1")
    return number


def _redacted_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    redacted = redact_for_storage(dict(value))
    if isinstance(redacted, Mapping):
        return dict(redacted)
    return {}


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(redact_for_storage(value)).strip()
    return text or None
