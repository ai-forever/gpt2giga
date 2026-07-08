"""Normalized session models for the Unified Harness UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from gpt2giga.harness.types import (
    GigaChatApiMode,
    HarnessCapability,
    parse_api_mode,
    parse_capability,
)


@dataclass(frozen=True)
class HarnessSession:
    """Long-lived UI conversation owned by gpt2giga."""

    id: str
    title: str
    created_at: str
    updated_at: str
    workspace: str | None
    default_harness_id: str
    default_model: str | None
    default_api_mode: GigaChatApiMode
    default_mode: str
    pinned: bool = False
    archived: bool = False
    tags: tuple[str, ...] = ()
    native: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HarnessMessage:
    """Message rendered in the chat surface."""

    id: str
    session_id: str
    run_id: str | None
    role: str
    content: str
    created_at: str
    harness_id: str | None = None
    model: str | None = None
    api_mode: GigaChatApiMode | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HarnessRun:
    """One harness execution inside a session."""

    id: str
    session_id: str
    harness_id: str
    status: str
    prompt: str
    model: str | None
    api_mode: GigaChatApiMode
    capability: HarnessCapability
    mode: str
    workspace: str | None
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    command: tuple[str, ...] = ()
    native_session_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HarnessStoredEvent:
    """Append-only normalized event emitted by session orchestration."""

    id: str
    session_id: str
    run_id: str
    type: str
    message: str
    payload: Mapping[str, Any]
    created_at: str


@dataclass(frozen=True)
class HarnessRawRecord:
    """Redacted raw request or response stored for audit inspection."""

    id: str
    session_id: str
    run_id: str
    payload: Mapping[str, Any]
    created_at: str


@dataclass(frozen=True)
class HarnessSessionBundle:
    """Complete persisted view of one session."""

    session: HarnessSession
    messages: tuple[HarnessMessage, ...]
    runs: tuple[HarnessRun, ...]
    events: tuple[HarnessStoredEvent, ...]
    raw_requests: tuple[HarnessRawRecord, ...] = ()
    raw_responses: tuple[HarnessRawRecord, ...] = ()
    storage: Mapping[str, Any] = field(default_factory=dict)


def session_to_dict(session: HarnessSession) -> dict[str, Any]:
    """Serialize a session for disk and API responses."""
    return {
        "id": session.id,
        "title": session.title,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "workspace": session.workspace,
        "default_harness_id": session.default_harness_id,
        "default_model": session.default_model,
        "default_api_mode": session.default_api_mode.value,
        "default_mode": session.default_mode,
        "pinned": session.pinned,
        "archived": session.archived,
        "tags": list(session.tags),
        "native": dict(session.native),
        "metadata": dict(session.metadata),
    }


def session_from_dict(data: Mapping[str, Any]) -> HarnessSession:
    """Parse a session from JSON-compatible data."""
    return HarnessSession(
        id=str(data["id"]),
        title=str(data.get("title") or "Untitled session"),
        created_at=str(data["created_at"]),
        updated_at=str(data.get("updated_at") or data["created_at"]),
        workspace=_optional_text(data.get("workspace")),
        default_harness_id=str(data.get("default_harness_id") or "echo"),
        default_model=_optional_text(data.get("default_model")),
        default_api_mode=parse_api_mode(data.get("default_api_mode")),
        default_mode=str(data.get("default_mode") or "plan"),
        pinned=bool(data.get("pinned")),
        archived=bool(data.get("archived")),
        tags=tuple(str(item) for item in data.get("tags", ())),
        native=_mapping(data.get("native")),
        metadata=_mapping(data.get("metadata")),
    )


def message_to_dict(message: HarnessMessage) -> dict[str, Any]:
    """Serialize a message for disk and API responses."""
    return {
        "id": message.id,
        "session_id": message.session_id,
        "run_id": message.run_id,
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at,
        "harness_id": message.harness_id,
        "model": message.model,
        "api_mode": message.api_mode.value if message.api_mode is not None else None,
        "metadata": dict(message.metadata),
    }


def message_from_dict(data: Mapping[str, Any]) -> HarnessMessage:
    """Parse a message from JSON-compatible data."""
    api_mode_value = data.get("api_mode")
    return HarnessMessage(
        id=str(data["id"]),
        session_id=str(data["session_id"]),
        run_id=_optional_text(data.get("run_id")),
        role=str(data.get("role") or "user"),
        content=str(data.get("content") or ""),
        created_at=str(data["created_at"]),
        harness_id=_optional_text(data.get("harness_id")),
        model=_optional_text(data.get("model")),
        api_mode=parse_api_mode(api_mode_value) if api_mode_value else None,
        metadata=_mapping(data.get("metadata")),
    )


def run_to_dict(run: HarnessRun) -> dict[str, Any]:
    """Serialize a run for disk and API responses."""
    return {
        "id": run.id,
        "session_id": run.session_id,
        "harness_id": run.harness_id,
        "status": run.status,
        "prompt": run.prompt,
        "model": run.model,
        "api_mode": run.api_mode.value,
        "capability": run.capability.value,
        "mode": run.mode,
        "workspace": run.workspace,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "error": run.error,
        "command": list(run.command),
        "native_session_id": run.native_session_id,
        "metadata": dict(run.metadata),
    }


def run_from_dict(data: Mapping[str, Any]) -> HarnessRun:
    """Parse a run from JSON-compatible data."""
    return HarnessRun(
        id=str(data["id"]),
        session_id=str(data["session_id"]),
        harness_id=str(data["harness_id"]),
        status=str(data.get("status") or "queued"),
        prompt=str(data.get("prompt") or ""),
        model=_optional_text(data.get("model")),
        api_mode=parse_api_mode(data.get("api_mode")),
        capability=parse_capability(data.get("capability")),
        mode=str(data.get("mode") or "plan"),
        workspace=_optional_text(data.get("workspace")),
        created_at=str(data["created_at"]),
        updated_at=str(data.get("updated_at") or data["created_at"]),
        started_at=_optional_text(data.get("started_at")),
        finished_at=_optional_text(data.get("finished_at")),
        error=_optional_text(data.get("error")),
        command=tuple(str(item) for item in data.get("command", ())),
        native_session_id=_optional_text(data.get("native_session_id")),
        metadata=_mapping(data.get("metadata")),
    )


def event_to_dict(event: HarnessStoredEvent) -> dict[str, Any]:
    """Serialize a stored event for disk and API responses."""
    return {
        "id": event.id,
        "session_id": event.session_id,
        "run_id": event.run_id,
        "type": event.type,
        "message": event.message,
        "payload": dict(event.payload),
        "created_at": event.created_at,
    }


def event_from_dict(data: Mapping[str, Any]) -> HarnessStoredEvent:
    """Parse a stored event from JSON-compatible data."""
    return HarnessStoredEvent(
        id=str(data["id"]),
        session_id=str(data["session_id"]),
        run_id=str(data["run_id"]),
        type=str(data.get("type") or "event"),
        message=str(data.get("message") or ""),
        payload=_mapping(data.get("payload")),
        created_at=str(data["created_at"]),
    )


def raw_record_to_dict(record: HarnessRawRecord) -> dict[str, Any]:
    """Serialize a raw record for disk and API responses."""
    return {
        "id": record.id,
        "session_id": record.session_id,
        "run_id": record.run_id,
        "payload": dict(record.payload),
        "created_at": record.created_at,
    }


def raw_record_from_dict(data: Mapping[str, Any]) -> HarnessRawRecord:
    """Parse a raw record from JSON-compatible data."""
    return HarnessRawRecord(
        id=str(data["id"]),
        session_id=str(data["session_id"]),
        run_id=str(data["run_id"]),
        payload=_mapping(data.get("payload")),
        created_at=str(data["created_at"]),
    )


def bundle_to_dict(bundle: HarnessSessionBundle) -> dict[str, Any]:
    """Serialize a complete session bundle for API responses."""
    return {
        "session": session_to_dict(bundle.session),
        "messages": [message_to_dict(message) for message in bundle.messages],
        "runs": [run_to_dict(run) for run in bundle.runs],
        "events": [event_to_dict(event) for event in bundle.events],
        "raw_requests": [raw_record_to_dict(record) for record in bundle.raw_requests],
        "raw_responses": [
            raw_record_to_dict(record) for record in bundle.raw_responses
        ],
        "storage": dict(bundle.storage),
    }


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}
