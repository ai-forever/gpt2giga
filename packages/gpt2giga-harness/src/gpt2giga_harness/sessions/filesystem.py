"""Filesystem-backed JSON/JSONL session store."""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping

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
    bundle_to_dict,
    event_from_dict,
    event_to_dict,
    message_from_dict,
    message_to_dict,
    native_link_from_dict,
    native_link_to_dict,
    raw_record_from_dict,
    raw_record_to_dict,
    run_from_dict,
    run_to_dict,
    session_from_dict,
    session_to_dict,
)
from gpt2giga_harness.sessions.locking import exclusive_file_lock
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
from gpt2giga_harness.sessions.read_index import (
    SessionIndexCursor,
    SessionIndexPage,
    SessionReadIndex,
    StaleReadSnapshotError,
)
from gpt2giga_harness.session_titles import new_session_metadata
from gpt2giga_harness.sessions.store import (
    RunNotFoundError,
    SessionNotFoundError,
    _filter_events,
    _matches_session,
    _patch_run,
    _patch_session,
    _redacted_mapping,
    _title_or_default,
    new_id,
    utc_now,
)
from gpt2giga_harness.types import GigaChatApiMode, HarnessCapability

INDEX_FILE = "index.json"
MANIFEST_FILE = "manifest.json"
MESSAGES_FILE = "messages.jsonl"
RUNS_FILE = "runs.jsonl"
EVENTS_FILE = "events.jsonl"
RAW_REQUESTS_FILE = "raw_requests.jsonl"
RAW_RESPONSES_FILE = "raw_responses.jsonl"
NATIVE_LINKS_FILE = "native_links.jsonl"
READ_INDEX_FILE = "read_model.sqlite3"


@dataclass(frozen=True)
class FilesystemRecordPage:
    """One bounded append-order page from a session JSONL file."""

    items: tuple[dict[str, Any], ...]
    next_offset: int | None
    has_more: bool
    snapshot_revision: str
    byte_count: int


class FilesystemHarnessSessionStore:
    """Persist normalized harness history as transparent JSON and JSONL files."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).expanduser()
        self.sessions_dir = self.data_dir / "sessions"
        read_index_path = self.sessions_dir / READ_INDEX_FILE
        self._read_index: SessionReadIndex | None = (
            SessionReadIndex(read_index_path) if read_index_path.exists() else None
        )
        self._read_index_lock = threading.RLock()
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
            metadata=_redacted_mapping(
                new_session_metadata(
                    metadata,
                    explicit_title=bool(title and str(title).strip()),
                )
            ),
        )
        session_dir = self._session_dir_for_new(session)
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "artifacts").mkdir(exist_ok=True)
        self._write_session(session, session_dir)
        self._upsert_index(session.id, session_dir)
        if self._read_index is not None:
            self._read_index.upsert_session(session)
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
        sessions: list[HarnessSession] = []
        for session_id in self._index().keys():
            try:
                session = self.get_session(session_id)
            except (SessionNotFoundError, ValueError, OSError):
                continue
            if _matches_session(
                session,
                project_id=project_id,
                workspace=workspace,
                harness_id=harness_id,
                q=q,
                include_archived=include_archived,
            ):
                sessions.append(session)
        sessions.sort(
            key=lambda session: (session.pinned, session.updated_at), reverse=True
        )
        if limit is not None:
            sessions = sessions[: max(limit, 0)]
        return tuple(sessions)

    def get_session(self, session_id: str) -> HarnessSession:
        session_dir = self._session_dir(session_id)
        try:
            data = _read_json(session_dir / MANIFEST_FILE)
            return session_from_dict(data)
        except FileNotFoundError as exc:
            self._remove_index_entry(session_id)
            raise SessionNotFoundError(session_id) from exc

    def list_sessions_page(
        self,
        *,
        project_id: str | None = None,
        workspace: str | None = None,
        harness_id: str | None = None,
        q: str | None = None,
        include_archived: bool = False,
        cursor: SessionIndexCursor | None = None,
        limit: int = 50,
    ) -> SessionIndexPage:
        """Return a bounded newest-first page from the derived read index."""
        self._ensure_read_index()
        return self._session_read_index().list_sessions_page(
            project_id=project_id,
            workspace=workspace,
            harness_id=harness_id,
            q=q,
            include_archived=include_archived,
            cursor=cursor,
            limit=limit,
        )

    def list_record_page(
        self,
        session_id: str,
        *,
        record_type: str,
        projector: Callable[[Any], dict[str, Any]],
        offset: int = 0,
        snapshot_revision: str | None = None,
        limit: int = 50,
        max_bytes: int = 1024 * 1024,
    ) -> FilesystemRecordPage:
        """Read a bounded cursor page without scanning preceding history."""
        self.get_session(session_id)
        filename, parser = _RECORD_PAGE_TYPES.get(record_type, (None, None))
        if filename is None or parser is None:
            raise ValueError(f"unsupported session record type: {record_type}")
        path = self._session_dir(session_id) / filename
        revision = _record_snapshot_revision(path)
        if snapshot_revision is not None and snapshot_revision != revision:
            raise StaleReadSnapshotError(f"{record_type} cursor snapshot is stale")
        bounded_limit = min(max(limit, 1), 100)
        bounded_bytes = min(max(max_bytes, 1024), 1024 * 1024)
        if not path.exists():
            return FilesystemRecordPage((), None, False, revision, 0)
        items: list[dict[str, Any]] = []
        byte_count = 0
        next_offset: int | None = None
        has_more = False
        with path.open("rb") as handle:
            file_size = path.stat().st_size
            if offset < 0 or offset > file_size:
                raise ValueError("record cursor offset is outside its snapshot")
            handle.seek(offset)
            while len(items) < bounded_limit:
                line_start = handle.tell()
                line = handle.readline((bounded_bytes * 4) + 1)
                if not line:
                    break
                if not line.endswith(b"\n") and handle.tell() < file_size:
                    raise ValueError("stored record exceeds the bounded read limit")
                text = line.strip()
                if not text:
                    continue
                decoded = json.loads(text)
                if not isinstance(decoded, Mapping):
                    continue
                projected = projector(parser(decoded))
                projected_bytes = len(
                    json.dumps(
                        projected,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
                if items and byte_count + projected_bytes > bounded_bytes:
                    has_more = True
                    next_offset = line_start
                    break
                if projected_bytes > bounded_bytes:
                    raise ValueError("projected record exceeds the response byte limit")
                items.append(projected)
                byte_count += projected_bytes
            if next_offset is None and handle.tell() < file_size:
                has_more = True
                next_offset = handle.tell()
        return FilesystemRecordPage(
            tuple(items),
            next_offset if has_more else None,
            has_more,
            revision,
            byte_count,
        )

    def update_session(self, session_id: str, **patch: Any) -> HarnessSession:
        session_dir = self._session_dir(session_id)
        path = session_dir / MANIFEST_FILE
        with exclusive_file_lock(path):
            session = session_from_dict(_read_json(path))
            updated = _patch_session(session, patch)
            _write_json_atomic_unlocked(path, session_to_dict(updated))
        if self._read_index is not None:
            self._read_index.upsert_session(updated)
        self.event_broker.publish_runs_center()
        return updated

    def update_session_if_title(
        self,
        session_id: str,
        expected_title: str,
        **patch: Any,
    ) -> HarnessSession | None:
        """Atomically patch a session unless a user already renamed it."""
        session_dir = self._session_dir(session_id)
        path = session_dir / MANIFEST_FILE
        with exclusive_file_lock(path):
            session = session_from_dict(_read_json(path))
            if session.title != expected_title:
                return None
            updated = _patch_session(session, patch)
            _write_json_atomic_unlocked(path, session_to_dict(updated))
        if self._read_index is not None:
            self._read_index.upsert_session(updated)
        self.event_broker.publish_runs_center()
        return updated

    def update_session_if_revision(
        self,
        session_id: str,
        expected_updated_at: str,
        **patch: Any,
    ) -> HarnessSession | None:
        """Atomically patch one session only at the presented revision."""
        session_dir = self._session_dir(session_id)
        path = session_dir / MANIFEST_FILE
        with exclusive_file_lock(path):
            session = session_from_dict(_read_json(path))
            if session.updated_at != expected_updated_at:
                return None
            updated = _patch_session(session, patch)
            _write_json_atomic_unlocked(path, session_to_dict(updated))
        if self._read_index is not None:
            self._read_index.upsert_session(updated)
        self.event_broker.publish_runs_center()
        return updated

    def delete_session(self, session_id: str) -> None:
        session_dir = self._session_dir(session_id)
        if not session_dir.exists():
            self._remove_index_entry(session_id)
            raise SessionNotFoundError(session_id)
        shutil.rmtree(session_dir)
        self._remove_index_entry(session_id)
        if self._read_index is not None:
            self._read_index.delete_session(session_id)
        self.event_broker.publish_session(session_id)
        self.event_broker.publish_runs_center()

    def delete_session_if_revision(
        self,
        session_id: str,
        expected_updated_at: str,
    ) -> bool:
        session_dir = self._session_dir(session_id)
        path = session_dir / MANIFEST_FILE
        if not session_dir.exists():
            self._remove_index_entry(session_id)
            raise SessionNotFoundError(session_id)
        with exclusive_file_lock(path):
            session = session_from_dict(_read_json(path))
            if session.updated_at != expected_updated_at:
                return False
            path.replace(session_dir / ".deleted-session.json")
        shutil.rmtree(session_dir)
        self._remove_index_entry(session_id)
        if self._read_index is not None:
            self._read_index.delete_session(session_id)
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
        self._append_jsonl(
            self._session_dir(message.session_id) / MESSAGES_FILE,
            message_to_dict(stored),
        )
        return stored

    def list_messages(self, session_id: str) -> tuple[HarnessMessage, ...]:
        self.get_session(session_id)
        return tuple(
            _read_jsonl(
                self._session_dir(session_id) / MESSAGES_FILE,
                message_from_dict,
            )
        )

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
        self._append_jsonl(self._session_dir(session_id) / RUNS_FILE, run_to_dict(run))
        if self._read_index is not None:
            self._read_index.upsert_run(run, 0)
        self.event_broker.publish_runs_center()
        return run

    def update_run(self, run_id: str, **patch: Any) -> HarnessRun:
        session_id, _, _, _ = self._find_run(run_id)
        path = self._session_dir(session_id) / RUNS_FILE
        with exclusive_file_lock(path):
            runs = _read_jsonl(path, run_from_dict)
            for index, run in enumerate(runs):
                if run.id != run_id:
                    continue
                updated = _patch_run(run, patch)
                runs[index] = updated
                _write_jsonl_atomic_unlocked(
                    path,
                    [redact_for_storage(run_to_dict(item)) for item in runs],
                )
                self._session_read_index().upsert_run(updated, index)
                self.event_broker.publish_runs_center()
                return updated
        raise RunNotFoundError(run_id)

    def get_run(self, run_id: str) -> HarnessRun:
        self._ensure_read_index()
        indexed = self._session_read_index().lookup_run(run_id)
        if indexed is None:
            raise RunNotFoundError(run_id)
        return indexed[2]

    def list_runs(self, session_id: str) -> tuple[HarnessRun, ...]:
        self.get_session(session_id)
        return tuple(
            _read_jsonl(
                self._session_dir(session_id) / RUNS_FILE,
                run_from_dict,
            )
        )

    def runs_center_generation(self) -> tuple[int, int]:
        """Return cheap session/run generations for global live invalidation."""
        self._ensure_read_index()
        return self._session_read_index().runs_center_generation()

    def append_event(self, event: HarnessStoredEvent) -> HarnessStoredEvent:
        self.get_session(event.session_id)
        stored = replace(
            event,
            message=str(redact_for_storage(event.message)),
            payload=redact_event_payload(event.payload),
        )
        self._append_jsonl(
            self._session_dir(event.session_id) / EVENTS_FILE,
            event_to_dict(stored),
        )
        self.event_broker.publish(stored)
        return stored

    def event_tail_offset(self, session_id: str) -> int:
        """Return the JSONL byte offset without reading retained event rows."""
        self.get_session(session_id)
        path = self._session_dir(session_id) / EVENTS_FILE
        return path.stat().st_size if path.exists() else 0

    def list_event_tail_page(
        self,
        session_id: str,
        *,
        run_id: str | None,
        offset: int = 0,
        limit: int = 100,
        max_bytes: int = 1024 * 1024,
    ) -> EventTailPage:
        """Read a bounded run tail from a durable byte offset."""
        self.get_session(session_id)
        path = self._session_dir(session_id) / EVENTS_FILE
        if not path.exists():
            if offset != 0:
                raise ValueError("event cursor offset is outside the retained tail")
            return EventTailPage((), 0, False, 0)
        file_size = path.stat().st_size
        if offset < 0 or offset > file_size:
            raise ValueError("event cursor offset is outside the retained tail")
        bounded_limit = min(max(limit, 1), 100)
        bounded_bytes = min(max(max_bytes, 1024), 1024 * 1024)
        max_scan_bytes = bounded_bytes * 4
        items: list[EventTailItem] = []
        byte_count = 0
        scan_start = offset
        position = offset
        with path.open("rb") as handle:
            handle.seek(offset)
            while len(items) < bounded_limit and handle.tell() < file_size:
                if handle.tell() - scan_start >= max_scan_bytes:
                    break
                line_start = handle.tell()
                line = handle.readline((bounded_bytes * 4) + 1)
                if not line.endswith(b"\n") and handle.tell() < file_size:
                    raise ValueError("stored event exceeds the bounded scan limit")
                position = handle.tell()
                text = line.strip()
                if not text:
                    continue
                decoded = json.loads(text)
                if not isinstance(decoded, Mapping):
                    continue
                event = event_from_dict(decoded)
                if run_id is not None and event.run_id != run_id:
                    continue
                size = event_stream_size(event)
                if items and byte_count + size > bounded_bytes:
                    position = line_start
                    break
                if size > bounded_bytes:
                    raise ValueError("stored event exceeds the stream byte limit")
                items.append(EventTailItem(event=event, next_offset=position))
                byte_count += size
        return EventTailPage(
            items=tuple(items),
            next_offset=position,
            has_more=position < file_size,
            byte_count=byte_count,
        )

    def resolve_event_cursor(
        self,
        session_id: str,
        *,
        run_id: str | None,
        event_id: str,
    ) -> EventCursorPosition | None:
        """Resolve a legacy event id once; opaque reconnects stay offset-based."""
        self.get_session(session_id)
        path = self._session_dir(session_id) / EVENTS_FILE
        if not path.exists():
            return None
        with path.open("rb") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                decoded = json.loads(text)
                if not isinstance(decoded, Mapping):
                    continue
                event = event_from_dict(decoded)
                if (run_id is None or event.run_id == run_id) and event.id == event_id:
                    return EventCursorPosition(
                        offset=handle.tell(),
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
        events = tuple(
            _read_jsonl(
                self._session_dir(session_id) / EVENTS_FILE,
                event_from_dict,
            )
        )
        return tuple(_filter_events(events, run_id=run_id, after_id=after_id))

    def append_raw_request(
        self,
        *,
        session_id: str,
        run_id: str,
        payload: Mapping[str, Any],
    ) -> HarnessRawRecord:
        return self._append_raw(RAW_REQUESTS_FILE, session_id, run_id, payload)

    def append_raw_response(
        self,
        *,
        session_id: str,
        run_id: str,
        payload: Mapping[str, Any],
    ) -> HarnessRawRecord:
        return self._append_raw(RAW_RESPONSES_FILE, session_id, run_id, payload)

    def list_raw_requests(self, session_id: str) -> tuple[HarnessRawRecord, ...]:
        self.get_session(session_id)
        return tuple(
            _read_jsonl(
                self._session_dir(session_id) / RAW_REQUESTS_FILE,
                raw_record_from_dict,
            )
        )

    def list_raw_responses(self, session_id: str) -> tuple[HarnessRawRecord, ...]:
        self.get_session(session_id)
        return tuple(
            _read_jsonl(
                self._session_dir(session_id) / RAW_RESPONSES_FILE,
                raw_record_from_dict,
            )
        )

    def append_native_link(
        self,
        session_id: str,
        link: HarnessNativeLink,
    ) -> HarnessNativeLink:
        self.get_session(session_id)
        stored = _redacted_native_link(replace(link, session_id=session_id))
        self._append_jsonl(
            self._session_dir(session_id) / NATIVE_LINKS_FILE,
            native_link_to_dict(stored),
        )
        return stored

    def list_native_links(self, session_id: str) -> tuple[HarnessNativeLink, ...]:
        self.get_session(session_id)
        return tuple(
            _read_jsonl(
                self._session_dir(session_id) / NATIVE_LINKS_FILE,
                native_link_from_dict,
            )
        )

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
        session_dir = self._session_dir(session_id)
        return HarnessSessionBundle(
            session=self.get_session(session_id),
            messages=self.list_messages(session_id),
            runs=self.list_runs(session_id),
            events=self.list_events(session_id),
            raw_requests=self.list_raw_requests(session_id),
            raw_responses=self.list_raw_responses(session_id),
            native_links=self.list_native_links(session_id),
            storage={
                "type": "filesystem",
                "data_dir": str(self.data_dir),
                "session_dir": str(session_dir),
                "native_dir": str(self.data_dir / "native"),
            },
        )

    def bundle_dict(self, session_id: str) -> dict[str, Any]:
        """Return a serialized bundle; useful for CLI printing."""
        return bundle_to_dict(self.get_session_bundle(session_id))

    def _append_raw(
        self,
        filename: str,
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
        self._append_jsonl(
            self._session_dir(session_id) / filename,
            raw_record_to_dict(record),
        )
        return record

    def _find_run(self, run_id: str) -> tuple[str, int, HarnessRun, list[HarnessRun]]:
        self._ensure_read_index()
        indexed = self._session_read_index().lookup_run(run_id)
        if indexed is not None:
            session_id, _, expected = indexed
            runs = list(self.list_runs(session_id))
            for index, run in enumerate(runs):
                if run.id == run_id:
                    return session_id, index, run, runs
            # The JSONL files remain authoritative if the derived row is stale.
            self._rebuild_read_index()
            refreshed = self._session_read_index().lookup_run(run_id)
            if refreshed is not None:
                return self._find_run_from_session(refreshed[0], run_id)
        raise RunNotFoundError(run_id)

    def _find_run_from_session(
        self, session_id: str, run_id: str
    ) -> tuple[str, int, HarnessRun, list[HarnessRun]]:
        runs = list(self.list_runs(session_id))
        for index, run in enumerate(runs):
            if run.id == run_id:
                return session_id, index, run, runs
        raise RunNotFoundError(run_id)

    def _ensure_read_index(self) -> None:
        with self._read_index_lock:
            if not self._session_read_index().is_complete():
                self._rebuild_read_index()

    def _session_read_index(self) -> SessionReadIndex:
        with self._read_index_lock:
            if self._read_index is None:
                self._read_index = SessionReadIndex(self.sessions_dir / READ_INDEX_FILE)
            return self._read_index

    def _rebuild_read_index(self) -> None:
        with self._read_index_lock:
            sessions: list[HarnessSession] = []
            runs: list[tuple[HarnessRun, int]] = []
            for session_id in self._index().keys():
                try:
                    session_dir = self._session_dir(session_id)
                    sessions.append(
                        session_from_dict(_read_json(session_dir / MANIFEST_FILE))
                    )
                    runs.extend(
                        (run, index)
                        for index, run in enumerate(
                            _read_jsonl(session_dir / RUNS_FILE, run_from_dict)
                        )
                    )
                except (SessionNotFoundError, ValueError, OSError, KeyError):
                    continue
            self._session_read_index().replace_all(sessions, runs)

    def _write_session(self, session: HarnessSession, session_dir: Path) -> None:
        _write_json_atomic(session_dir / MANIFEST_FILE, session_to_dict(session))

    def _session_dir_for_new(self, session: HarnessSession) -> Path:
        year = session.created_at[:4]
        month = session.created_at[5:7]
        return self.sessions_dir / year / month / session.id

    def _session_dir(self, session_id: str) -> Path:
        index = self._index()
        rel = index.get(session_id)
        if rel is None:
            self._rebuild_index()
            rel = self._index().get(session_id)
        if rel is None:
            raise SessionNotFoundError(session_id)
        return self.sessions_dir / rel

    def _index(self) -> dict[str, Path]:
        try:
            return _index_from_payload(_read_json(self.sessions_dir / INDEX_FILE))
        except (FileNotFoundError, ValueError):
            return self._rebuild_index()

    def _upsert_index(self, session_id: str, session_dir: Path) -> None:
        path = self.sessions_dir / INDEX_FILE
        with exclusive_file_lock(path):
            index = self._read_or_scan_index_unlocked(path)
            index[session_id] = session_dir.relative_to(self.sessions_dir)
            self._write_index_unlocked(index)

    def _remove_index_entry(self, session_id: str) -> None:
        path = self.sessions_dir / INDEX_FILE
        with exclusive_file_lock(path):
            index = self._read_or_scan_index_unlocked(path)
            if session_id in index:
                index.pop(session_id, None)
                self._write_index_unlocked(index)

    def _rebuild_index(self) -> dict[str, Path]:
        path = self.sessions_dir / INDEX_FILE
        with exclusive_file_lock(path):
            index = self._scan_index_unlocked()
            self._write_index_unlocked(index)
        return index

    def _scan_index_unlocked(self) -> dict[str, Path]:
        index: dict[str, Path] = {}
        if self.sessions_dir.exists():
            for manifest in self.sessions_dir.glob("*/*/*/" + MANIFEST_FILE):
                try:
                    session = session_from_dict(_read_json(manifest))
                except (OSError, ValueError, json.JSONDecodeError, KeyError):
                    continue
                index[session.id] = manifest.parent.relative_to(self.sessions_dir)
        return index

    def _read_or_scan_index_unlocked(self, path: Path) -> dict[str, Path]:
        try:
            return _index_from_payload(_read_json(path))
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            return self._scan_index_unlocked()

    def _write_index_unlocked(self, index: Mapping[str, Path]) -> None:
        sessions = [
            {"id": session_id, "path": str(path)}
            for session_id, path in sorted(index.items())
        ]
        _write_json_atomic_unlocked(
            self.sessions_dir / INDEX_FILE, {"sessions": sessions}
        )

    def _append_jsonl(self, path: Path, payload: Mapping[str, Any]) -> None:
        _append_jsonl(path, redact_for_storage(dict(payload)))

    def _write_jsonl(self, path: Path, payloads: list[Mapping[str, Any]]) -> None:
        _write_jsonl_atomic(
            path,
            [redact_for_storage(dict(payload)) for payload in payloads],
        )


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return data


def _read_jsonl(path: Path, parser: Callable[[Mapping[str, Any]], Any]) -> list[Any]:
    if not path.exists():
        return []
    rows: list[Any] = []
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
    with exclusive_file_lock(path):
        _write_json_atomic_unlocked(path, payload)


def _write_json_atomic_unlocked(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{new_id('tmp')}")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(
            redact_for_storage(dict(payload)), handle, ensure_ascii=False, indent=2
        )
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, path)


def _write_jsonl_atomic(path: Path, payloads: list[Any]) -> None:
    with exclusive_file_lock(path):
        _write_jsonl_atomic_unlocked(path, payloads)


def _write_jsonl_atomic_unlocked(path: Path, payloads: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{new_id('tmp')}")
    with temp_path.open("w", encoding="utf-8") as handle:
        for payload in payloads:
            handle.write(json.dumps(redact_for_storage(payload), ensure_ascii=False))
            handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, path)


def _append_jsonl(path: Path, payload: Any) -> None:
    with exclusive_file_lock(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = (
            json.dumps(redact_for_storage(payload), ensure_ascii=False) + "\n"
        ).encode("utf-8")
        descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, encoded)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _index_from_payload(raw: Mapping[str, Any]) -> dict[str, Path]:
    sessions = raw.get("sessions", [])
    if not isinstance(sessions, list):
        raise ValueError("session index does not contain a list")
    index: dict[str, Path] = {}
    for item in sessions:
        if not isinstance(item, Mapping):
            continue
        session_id = item.get("id")
        rel_path = item.get("path")
        if session_id and rel_path:
            index[str(session_id)] = Path(str(rel_path))
    return index


_RECORD_PAGE_TYPES: dict[str, tuple[str, Callable[[Mapping[str, Any]], Any]]] = {
    "messages": (MESSAGES_FILE, message_from_dict),
    "runs": (RUNS_FILE, run_from_dict),
    "events": (EVENTS_FILE, event_from_dict),
    "raw_requests": (RAW_REQUESTS_FILE, raw_record_from_dict),
    "raw_responses": (RAW_RESPONSES_FILE, raw_record_from_dict),
    "native_links": (NATIVE_LINKS_FILE, native_link_from_dict),
}


def _record_snapshot_revision(path: Path) -> str:
    if not path.exists():
        source = f"{path.name}:empty"
    else:
        stat = path.stat()
        source = f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _redacted_native_link(link: HarnessNativeLink) -> HarnessNativeLink:
    redacted = redact_for_storage(native_link_to_dict(link))
    if isinstance(redacted, Mapping):
        return native_link_from_dict(redacted)
    return link
