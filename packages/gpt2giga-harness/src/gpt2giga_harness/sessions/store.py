"""Store interfaces and in-memory implementation for harness sessions."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import threading
from typing import Any, Mapping, Protocol
from uuid import uuid4

from gpt2giga_harness.native.models import parse_invocation_mode
from gpt2giga_harness.runtime.models import RunStatus, parse_run_status
from gpt2giga_harness.sessions.models import (
    HarnessMessage,
    HarnessNativeLink,
    HarnessRawRecord,
    HarnessRun,
    HarnessSession,
    HarnessSessionBundle,
    HarnessStoredEvent,
    native_link_from_dict,
    native_link_to_dict,
)
from gpt2giga_harness.sessions.event_stream import (
    EventCursorPosition,
    EventTailItem,
    EventTailPage,
    RunEventBroker,
    event_stream_size,
)
from gpt2giga_harness.sessions.redaction import (
    redact_event_payload,
    redact_for_storage,
)
from gpt2giga_harness.types import GigaChatApiMode, HarnessCapability


class SessionNotFoundError(KeyError):
    """Raised when a harness session does not exist."""


class RunNotFoundError(KeyError):
    """Raised when a harness run does not exist."""


class HarnessSessionStore(Protocol):
    """Persistence contract for normalized harness UI history."""

    def create_session(
        self,
        *,
        title: str | None = None,
        workspace: str | None = None,
        default_harness_id: str = "echo",
        default_model: str | None = None,
        default_api_mode: GigaChatApiMode = GigaChatApiMode.V2,
        default_mode: str = "plan",
        native: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> HarnessSession:
        """Create a new session."""

    def list_sessions(
        self,
        *,
        project_id: str | None = None,
        workspace: str | None = None,
        harness_id: str | None = None,
        q: str | None = None,
        include_archived: bool = False,
        limit: int | None = None,
    ) -> tuple[HarnessSession, ...]:
        """List sessions newest first."""

    def get_session(self, session_id: str) -> HarnessSession:
        """Return one session."""

    def update_session(self, session_id: str, **patch: Any) -> HarnessSession:
        """Patch one session."""

    def update_session_if_title(
        self,
        session_id: str,
        expected_title: str,
        **patch: Any,
    ) -> HarnessSession | None:
        """Atomically patch one session only while its title is unchanged."""

    def update_session_if_revision(
        self,
        session_id: str,
        expected_updated_at: str,
        **patch: Any,
    ) -> HarnessSession | None:
        """Atomically patch one session only at the presented revision."""

    def delete_session(self, session_id: str) -> None:
        """Delete one session."""

    def delete_session_if_revision(
        self,
        session_id: str,
        expected_updated_at: str,
    ) -> bool:
        """Atomically delete one session only at the presented revision."""

    def archive_session(
        self,
        session_id: str,
        archived: bool = True,
    ) -> HarnessSession:
        """Archive or unarchive one session."""

    def append_message(self, message: HarnessMessage) -> HarnessMessage:
        """Append one message."""

    def list_messages(self, session_id: str) -> tuple[HarnessMessage, ...]:
        """List messages for one session."""

    def create_run(
        self,
        *,
        run_id: str | None = None,
        session_id: str,
        harness_id: str,
        prompt: str,
        model: str | None,
        api_mode: GigaChatApiMode,
        capability: HarnessCapability,
        mode: str,
        workspace: str | None,
        invocation_mode: Any = None,
        status: RunStatus | str = RunStatus.QUEUED,
        started_at: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> HarnessRun:
        """Create one run."""

    def update_run(self, run_id: str, **patch: Any) -> HarnessRun:
        """Patch one run."""

    def get_run(self, run_id: str) -> HarnessRun:
        """Return one run by id."""

    def list_runs(self, session_id: str) -> tuple[HarnessRun, ...]:
        """List runs for one session."""

    def runs_center_generation(self) -> tuple[int, int]:
        """Return cheap session/run generations for global live invalidation."""

    def append_event(self, event: HarnessStoredEvent) -> HarnessStoredEvent:
        """Append one event."""

    def event_tail_offset(self, session_id: str) -> int:
        """Return the durable append offset after all retained session events."""

    def list_event_tail_page(
        self,
        session_id: str,
        *,
        run_id: str | None,
        offset: int = 0,
        limit: int = 100,
        max_bytes: int = 1024 * 1024,
    ) -> EventTailPage:
        """Return a bounded optionally run-filtered durable event page."""

    def resolve_event_cursor(
        self,
        session_id: str,
        *,
        run_id: str | None,
        event_id: str,
    ) -> EventCursorPosition | None:
        """Resolve one retained event identity to its durable append offset."""

    def list_events(
        self,
        session_id: str,
        *,
        run_id: str | None = None,
        after_id: str | None = None,
    ) -> tuple[HarnessStoredEvent, ...]:
        """List events for one session, optionally filtered by run."""

    def append_raw_request(
        self,
        *,
        session_id: str,
        run_id: str,
        payload: Mapping[str, Any],
    ) -> HarnessRawRecord:
        """Append one raw request record."""

    def append_raw_response(
        self,
        *,
        session_id: str,
        run_id: str,
        payload: Mapping[str, Any],
    ) -> HarnessRawRecord:
        """Append one raw response record."""

    def list_raw_requests(self, session_id: str) -> tuple[HarnessRawRecord, ...]:
        """List raw request records for one session."""

    def list_raw_responses(self, session_id: str) -> tuple[HarnessRawRecord, ...]:
        """List raw response records for one session."""

    def append_native_link(
        self,
        session_id: str,
        link: HarnessNativeLink,
    ) -> HarnessNativeLink:
        """Append one native session link."""

    def list_native_links(self, session_id: str) -> tuple[HarnessNativeLink, ...]:
        """List native links for one session."""

    def get_native_link(
        self,
        session_id: str,
        harness_id: str,
    ) -> HarnessNativeLink | None:
        """Return the latest native link for a harness in one session."""

    def get_session_bundle(self, session_id: str) -> HarnessSessionBundle:
        """Return a complete session bundle."""


class InMemoryHarnessSessionStore:
    """In-memory session store for hermetic tests."""

    def __init__(self) -> None:
        self._sessions: dict[str, HarnessSession] = {}
        self._messages: dict[str, list[HarnessMessage]] = {}
        self._runs: dict[str, list[HarnessRun]] = {}
        self._events: dict[str, list[HarnessStoredEvent]] = {}
        self._raw_requests: dict[str, list[HarnessRawRecord]] = {}
        self._raw_responses: dict[str, list[HarnessRawRecord]] = {}
        self._native_links: dict[str, list[HarnessNativeLink]] = {}
        self._session_lock = threading.RLock()
        self._session_generation = 0
        self._run_generation = 0
        self.event_broker = RunEventBroker()

    def create_session(
        self,
        *,
        title: str | None = None,
        workspace: str | None = None,
        default_harness_id: str = "echo",
        default_model: str | None = None,
        default_api_mode: GigaChatApiMode = GigaChatApiMode.V2,
        default_mode: str = "plan",
        native: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> HarnessSession:
        now = utc_now()
        session = HarnessSession(
            id=new_id("sess"),
            title=_title_or_default(title),
            created_at=now,
            updated_at=now,
            workspace=workspace,
            default_harness_id=default_harness_id,
            default_model=default_model,
            default_api_mode=default_api_mode,
            default_mode=default_mode,
            native=_redacted_mapping(native),
            metadata=_redacted_mapping(metadata),
        )
        self._sessions[session.id] = session
        self._session_generation += 1
        self.event_broker.publish_runs_center()
        return session

    def list_sessions(
        self,
        *,
        project_id: str | None = None,
        workspace: str | None = None,
        harness_id: str | None = None,
        q: str | None = None,
        include_archived: bool = False,
        limit: int | None = None,
    ) -> tuple[HarnessSession, ...]:
        sessions = [
            session
            for session in self._sessions.values()
            if _matches_session(
                session,
                project_id=project_id,
                workspace=workspace,
                harness_id=harness_id,
                q=q,
                include_archived=include_archived,
            )
        ]
        sessions.sort(key=lambda session: session.updated_at, reverse=True)
        if limit is not None:
            sessions = sessions[: max(limit, 0)]
        return tuple(sessions)

    def get_session(self, session_id: str) -> HarnessSession:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise SessionNotFoundError(session_id) from exc

    def update_session(self, session_id: str, **patch: Any) -> HarnessSession:
        with self._session_lock:
            session = self.get_session(session_id)
            updated = _patch_session(session, patch)
            self._sessions[session_id] = updated
        self._session_generation += 1
        self.event_broker.publish_runs_center()
        return updated

    def update_session_if_title(
        self,
        session_id: str,
        expected_title: str,
        **patch: Any,
    ) -> HarnessSession | None:
        """Atomically patch a session unless a user already renamed it."""
        with self._session_lock:
            session = self.get_session(session_id)
            if session.title != expected_title:
                return None
            updated = _patch_session(session, patch)
            self._sessions[session_id] = updated
        self._session_generation += 1
        self.event_broker.publish_runs_center()
        return updated

    def update_session_if_revision(
        self,
        session_id: str,
        expected_updated_at: str,
        **patch: Any,
    ) -> HarnessSession | None:
        with self._session_lock:
            session = self.get_session(session_id)
            if session.updated_at != expected_updated_at:
                return None
            updated = _patch_session(session, patch)
            self._sessions[session_id] = updated
        self._session_generation += 1
        self.event_broker.publish_runs_center()
        return updated

    def delete_session(self, session_id: str) -> None:
        with self._session_lock:
            self.get_session(session_id)
            self._sessions.pop(session_id, None)
            self._messages.pop(session_id, None)
            self._runs.pop(session_id, None)
            self._events.pop(session_id, None)
            self._raw_requests.pop(session_id, None)
            self._raw_responses.pop(session_id, None)
            self._native_links.pop(session_id, None)
            self._session_generation += 1
        self.event_broker.publish_session(session_id)
        self.event_broker.publish_runs_center()

    def delete_session_if_revision(
        self,
        session_id: str,
        expected_updated_at: str,
    ) -> bool:
        with self._session_lock:
            session = self.get_session(session_id)
            if session.updated_at != expected_updated_at:
                return False
            self._sessions.pop(session_id, None)
            self._messages.pop(session_id, None)
            self._runs.pop(session_id, None)
            self._events.pop(session_id, None)
            self._raw_requests.pop(session_id, None)
            self._raw_responses.pop(session_id, None)
            self._native_links.pop(session_id, None)
            self._session_generation += 1
        self.event_broker.publish_session(session_id)
        self.event_broker.publish_runs_center()
        return True

    def archive_session(
        self,
        session_id: str,
        archived: bool = True,
    ) -> HarnessSession:
        return self.update_session(session_id, archived=archived)

    def append_message(self, message: HarnessMessage) -> HarnessMessage:
        self.get_session(message.session_id)
        stored = replace(
            message,
            content=str(redact_for_storage(message.content)),
            metadata=_redacted_mapping(message.metadata),
        )
        self._messages.setdefault(message.session_id, []).append(stored)
        return stored

    def list_messages(self, session_id: str) -> tuple[HarnessMessage, ...]:
        self.get_session(session_id)
        return tuple(self._messages.get(session_id, ()))

    def create_run(
        self,
        *,
        run_id: str | None = None,
        session_id: str,
        harness_id: str,
        prompt: str,
        model: str | None,
        api_mode: GigaChatApiMode,
        capability: HarnessCapability,
        mode: str,
        workspace: str | None,
        invocation_mode: Any = None,
        status: RunStatus | str = RunStatus.QUEUED,
        started_at: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> HarnessRun:
        self.get_session(session_id)
        now = utc_now()
        run = HarnessRun(
            id=run_id or new_id("run"),
            session_id=session_id,
            harness_id=harness_id,
            status=parse_run_status(status),
            prompt=str(redact_for_storage(prompt)),
            model=model,
            api_mode=api_mode,
            capability=capability,
            mode=mode,
            workspace=workspace,
            invocation_mode=parse_invocation_mode(invocation_mode),
            created_at=now,
            updated_at=now,
            started_at=started_at,
            metadata=_redacted_mapping(metadata),
        )
        self._runs.setdefault(session_id, []).append(run)
        self._run_generation += 1
        self.event_broker.publish_runs_center()
        return run

    def update_run(self, run_id: str, **patch: Any) -> HarnessRun:
        session_id, index, run = self._find_run(run_id)
        updated = _patch_run(run, patch)
        self._runs[session_id][index] = updated
        self._run_generation += 1
        self.event_broker.publish_runs_center()
        return updated

    def get_run(self, run_id: str) -> HarnessRun:
        return self._find_run(run_id)[2]

    def list_runs(self, session_id: str) -> tuple[HarnessRun, ...]:
        self.get_session(session_id)
        return tuple(self._runs.get(session_id, ()))

    def runs_center_generation(self) -> tuple[int, int]:
        """Return cheap session/run generations for global live invalidation."""
        return self._session_generation, self._run_generation

    def append_event(self, event: HarnessStoredEvent) -> HarnessStoredEvent:
        self.get_session(event.session_id)
        stored = replace(
            event,
            message=str(redact_for_storage(event.message)),
            payload=redact_event_payload(event.payload),
        )
        self._events.setdefault(event.session_id, []).append(stored)
        self.event_broker.publish(stored)
        return stored

    def event_tail_offset(self, session_id: str) -> int:
        """Return the in-memory append offset without replaying retained events."""
        self.get_session(session_id)
        return len(self._events.get(session_id, ()))

    def list_event_tail_page(
        self,
        session_id: str,
        *,
        run_id: str | None,
        offset: int = 0,
        limit: int = 100,
        max_bytes: int = 1024 * 1024,
    ) -> EventTailPage:
        """Return a bounded run-filtered page without replaying prior positions."""
        self.get_session(session_id)
        events = self._events.get(session_id, ())
        if offset < 0 or offset > len(events):
            raise ValueError("event cursor offset is outside the retained tail")
        bounded_limit = min(max(limit, 1), 100)
        bounded_bytes = min(max(max_bytes, 1024), 1024 * 1024)
        items: list[EventTailItem] = []
        byte_count = 0
        position = offset
        scan_limit = min(len(events), offset + (bounded_limit * 16))
        while position < scan_limit and len(items) < bounded_limit:
            event = events[position]
            position += 1
            if run_id is not None and event.run_id != run_id:
                continue
            size = event_stream_size(event)
            if items and byte_count + size > bounded_bytes:
                position -= 1
                break
            if size > bounded_bytes:
                raise ValueError("stored event exceeds the stream byte limit")
            items.append(EventTailItem(event=event, next_offset=position))
            byte_count += size
        return EventTailPage(
            items=tuple(items),
            next_offset=position,
            has_more=position < len(events),
            byte_count=byte_count,
        )

    def resolve_event_cursor(
        self,
        session_id: str,
        *,
        run_id: str | None,
        event_id: str,
    ) -> EventCursorPosition | None:
        """Resolve one legacy event id to its append-order tail offset."""
        self.get_session(session_id)
        for position, event in enumerate(self._events.get(session_id, ()), start=1):
            if (run_id is None or event.run_id == run_id) and event.id == event_id:
                return EventCursorPosition(
                    offset=position,
                    terminal_seen=event.type == "run_finished",
                )
        return None

    def list_events(
        self,
        session_id: str,
        *,
        run_id: str | None = None,
        after_id: str | None = None,
    ) -> tuple[HarnessStoredEvent, ...]:
        self.get_session(session_id)
        events = self._events.get(session_id, ())
        return tuple(_filter_events(events, run_id=run_id, after_id=after_id))

    def append_raw_request(
        self,
        *,
        session_id: str,
        run_id: str,
        payload: Mapping[str, Any],
    ) -> HarnessRawRecord:
        return self._append_raw(self._raw_requests, session_id, run_id, payload)

    def append_raw_response(
        self,
        *,
        session_id: str,
        run_id: str,
        payload: Mapping[str, Any],
    ) -> HarnessRawRecord:
        return self._append_raw(self._raw_responses, session_id, run_id, payload)

    def list_raw_requests(self, session_id: str) -> tuple[HarnessRawRecord, ...]:
        self.get_session(session_id)
        return tuple(self._raw_requests.get(session_id, ()))

    def list_raw_responses(self, session_id: str) -> tuple[HarnessRawRecord, ...]:
        self.get_session(session_id)
        return tuple(self._raw_responses.get(session_id, ()))

    def append_native_link(
        self,
        session_id: str,
        link: HarnessNativeLink,
    ) -> HarnessNativeLink:
        self.get_session(session_id)
        stored = _redacted_native_link(replace(link, session_id=session_id))
        self._native_links.setdefault(session_id, []).append(stored)
        return stored

    def list_native_links(self, session_id: str) -> tuple[HarnessNativeLink, ...]:
        self.get_session(session_id)
        return tuple(self._native_links.get(session_id, ()))

    def get_native_link(
        self,
        session_id: str,
        harness_id: str,
    ) -> HarnessNativeLink | None:
        links = [
            link
            for link in self.list_native_links(session_id)
            if link.harness_id == harness_id
        ]
        return links[-1] if links else None

    def get_session_bundle(self, session_id: str) -> HarnessSessionBundle:
        return HarnessSessionBundle(
            session=self.get_session(session_id),
            messages=self.list_messages(session_id),
            runs=self.list_runs(session_id),
            events=self.list_events(session_id),
            raw_requests=self.list_raw_requests(session_id),
            raw_responses=self.list_raw_responses(session_id),
            native_links=self.list_native_links(session_id),
            storage={"type": "memory"},
        )

    def _append_raw(
        self,
        target: dict[str, list[HarnessRawRecord]],
        session_id: str,
        run_id: str,
        payload: Mapping[str, Any],
    ) -> HarnessRawRecord:
        self.get_session(session_id)
        record = HarnessRawRecord(
            id=new_id("raw"),
            session_id=session_id,
            run_id=run_id,
            payload=_redacted_mapping(payload),
            created_at=utc_now(),
        )
        target.setdefault(session_id, []).append(record)
        return record

    def _find_run(self, run_id: str) -> tuple[str, int, HarnessRun]:
        for session_id, runs in self._runs.items():
            for index, run in enumerate(runs):
                if run.id == run_id:
                    return session_id, index, run
        raise RunNotFoundError(run_id)


def utc_now() -> str:
    """Return a stable UTC timestamp."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    """Return a compact prefixed identifier."""
    return f"{prefix}_{uuid4().hex}"


def title_from_prompt(prompt: str) -> str:
    """Generate a session title from a first prompt."""
    title = " ".join(str(prompt).split())
    title = title.lstrip("#>*- `")
    if len(title) > 40:
        candidate = title[:37].rstrip()
        word_boundary = candidate.rfind(" ")
        if word_boundary >= 24:
            candidate = candidate[:word_boundary]
        title = candidate.rstrip(".,:;!?") + "..."
    return title or "Untitled session"


def _title_or_default(title: str | None) -> str:
    if title is None:
        return "Untitled session"
    return title_from_prompt(title)


def _matches_session(
    session: HarnessSession,
    *,
    project_id: str | None,
    workspace: str | None,
    harness_id: str | None,
    q: str | None,
    include_archived: bool,
) -> bool:
    if session.archived and not include_archived:
        return False
    if project_id and session.metadata.get("project_id") != project_id:
        return False
    if workspace and session.workspace != workspace:
        return False
    if harness_id and session.default_harness_id != harness_id:
        return False
    if q and q.lower() not in session.title.lower():
        return False
    return True


def _filter_events(
    events: list[HarnessStoredEvent] | tuple[HarnessStoredEvent, ...],
    *,
    run_id: str | None,
    after_id: str | None,
) -> list[HarnessStoredEvent]:
    result = list(events)
    if run_id is not None:
        result = [event for event in result if event.run_id == run_id]
    if after_id is not None:
        seen = False
        filtered: list[HarnessStoredEvent] = []
        for event in result:
            if seen:
                filtered.append(event)
            elif event.id == after_id:
                seen = True
        result = filtered
    return result


def _patch_session(session: HarnessSession, patch: Mapping[str, Any]) -> HarnessSession:
    allowed = {
        "title",
        "workspace",
        "default_harness_id",
        "default_model",
        "default_api_mode",
        "default_mode",
        "pinned",
        "archived",
        "tags",
        "native",
        "metadata",
    }
    changes: dict[str, Any] = {"updated_at": utc_now()}
    for key, value in patch.items():
        if key not in allowed:
            continue
        if key == "default_api_mode" and not isinstance(value, GigaChatApiMode):
            value = GigaChatApiMode(str(value))
        elif key == "tags":
            value = tuple(str(item) for item in value)
        elif key in {"native", "metadata"}:
            value = _redacted_mapping(value)
        elif key == "title":
            value = _title_or_default(str(value))
        changes[key] = value
    return replace(session, **changes)


def _patch_run(run: HarnessRun, patch: Mapping[str, Any]) -> HarnessRun:
    allowed = {
        "status",
        "updated_at",
        "started_at",
        "finished_at",
        "error",
        "command",
        "native_session_id",
        "metadata",
    }
    changes: dict[str, Any] = {"updated_at": utc_now()}
    for key, value in patch.items():
        if key not in allowed:
            continue
        if key == "command":
            value = tuple(str(redact_for_storage(item)) for item in value)
        elif key == "metadata":
            value = _redacted_mapping(value)
        elif key == "error":
            value = None if value is None else str(redact_for_storage(value))
        elif key == "status":
            value = parse_run_status(value)
        changes[key] = value
    return replace(run, **changes)


def _redacted_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    redacted = redact_for_storage(dict(value))
    if isinstance(redacted, Mapping):
        return dict(redacted)
    return {}


def _redacted_native_link(link: HarnessNativeLink) -> HarnessNativeLink:
    redacted = redact_for_storage(native_link_to_dict(link))
    if isinstance(redacted, Mapping):
        return native_link_from_dict(redacted)
    return link
