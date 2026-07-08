"""Filesystem-backed JSON/JSONL session store."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Mapping

from gpt2giga.harness.sessions.models import (
    HarnessMessage,
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
    raw_record_from_dict,
    raw_record_to_dict,
    run_from_dict,
    run_to_dict,
    session_from_dict,
    session_to_dict,
)
from gpt2giga.harness.sessions.redaction import redact_for_storage
from gpt2giga.harness.sessions.store import (
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
from gpt2giga.harness.types import GigaChatApiMode, HarnessCapability

INDEX_FILE = "index.json"
MANIFEST_FILE = "manifest.json"
MESSAGES_FILE = "messages.jsonl"
RUNS_FILE = "runs.jsonl"
EVENTS_FILE = "events.jsonl"
RAW_REQUESTS_FILE = "raw_requests.jsonl"
RAW_RESPONSES_FILE = "raw_responses.jsonl"


class FilesystemHarnessSessionStore:
    """Persist normalized harness history as transparent JSON and JSONL files."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).expanduser()
        self.sessions_dir = self.data_dir / "sessions"

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
        session_dir = self._session_dir_for_new(session)
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "artifacts").mkdir(exist_ok=True)
        self._write_session(session, session_dir)
        self._upsert_index(session.id, session_dir)
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

    def update_session(self, session_id: str, **patch: Any) -> HarnessSession:
        session = self.get_session(session_id)
        updated = _patch_session(session, patch)
        self._write_session(updated, self._session_dir(session_id))
        return updated

    def delete_session(self, session_id: str) -> None:
        session_dir = self._session_dir(session_id)
        if not session_dir.exists():
            self._remove_index_entry(session_id)
            raise SessionNotFoundError(session_id)
        shutil.rmtree(session_dir)
        self._remove_index_entry(session_id)

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
        session_id: str,
        harness_id: str,
        prompt: str,
        model: str | None,
        api_mode: GigaChatApiMode,
        capability: HarnessCapability,
        mode: str,
        workspace: str | None,
        status: str = "queued",
        started_at: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> HarnessRun:
        self.get_session(session_id)
        now = utc_now()
        run = HarnessRun(
            id=new_id("run"),
            session_id=session_id,
            harness_id=harness_id,
            status=status,
            prompt=str(redact_for_storage(prompt)),
            model=model,
            api_mode=api_mode,
            capability=capability,
            mode=mode,
            workspace=workspace,
            created_at=now,
            updated_at=now,
            started_at=started_at,
            metadata=_redacted_mapping(metadata),
        )
        self._append_jsonl(self._session_dir(session_id) / RUNS_FILE, run_to_dict(run))
        return run

    def update_run(self, run_id: str, **patch: Any) -> HarnessRun:
        session_id, index, run, runs = self._find_run(run_id)
        updated = _patch_run(run, patch)
        runs[index] = updated
        self._write_jsonl(
            self._session_dir(session_id) / RUNS_FILE,
            [run_to_dict(item) for item in runs],
        )
        return updated

    def list_runs(self, session_id: str) -> tuple[HarnessRun, ...]:
        self.get_session(session_id)
        return tuple(
            _read_jsonl(
                self._session_dir(session_id) / RUNS_FILE,
                run_from_dict,
            )
        )

    def append_event(self, event: HarnessStoredEvent) -> HarnessStoredEvent:
        self.get_session(event.session_id)
        stored = replace(
            event,
            message=str(redact_for_storage(event.message)),
            payload=_redacted_mapping(event.payload),
        )
        self._append_jsonl(
            self._session_dir(event.session_id) / EVENTS_FILE,
            event_to_dict(stored),
        )
        return stored

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

    def get_session_bundle(self, session_id: str) -> HarnessSessionBundle:
        session_dir = self._session_dir(session_id)
        return HarnessSessionBundle(
            session=self.get_session(session_id),
            messages=self.list_messages(session_id),
            runs=self.list_runs(session_id),
            events=self.list_events(session_id),
            raw_requests=self.list_raw_requests(session_id),
            raw_responses=self.list_raw_responses(session_id),
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
        for session_id in self._index().keys():
            try:
                runs = list(self.list_runs(session_id))
            except (SessionNotFoundError, ValueError, OSError):
                continue
            for index, run in enumerate(runs):
                if run.id == run_id:
                    return session_id, index, run, runs
        raise RunNotFoundError(run_id)

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
            raw = _read_json(self.sessions_dir / INDEX_FILE)
        except FileNotFoundError:
            return self._rebuild_index()
        sessions = raw.get("sessions", [])
        if not isinstance(sessions, list):
            return self._rebuild_index()
        index: dict[str, Path] = {}
        for item in sessions:
            if not isinstance(item, Mapping):
                continue
            session_id = item.get("id")
            rel_path = item.get("path")
            if session_id and rel_path:
                index[str(session_id)] = Path(str(rel_path))
        return index

    def _upsert_index(self, session_id: str, session_dir: Path) -> None:
        index = self._index()
        index[session_id] = session_dir.relative_to(self.sessions_dir)
        self._write_index(index)

    def _remove_index_entry(self, session_id: str) -> None:
        index = self._index()
        if session_id in index:
            index.pop(session_id, None)
            self._write_index(index)

    def _rebuild_index(self) -> dict[str, Path]:
        index: dict[str, Path] = {}
        if self.sessions_dir.exists():
            for manifest in self.sessions_dir.glob("*/*/*/" + MANIFEST_FILE):
                try:
                    session = session_from_dict(_read_json(manifest))
                except (OSError, ValueError, json.JSONDecodeError, KeyError):
                    continue
                index[session.id] = manifest.parent.relative_to(self.sessions_dir)
        self._write_index(index)
        return index

    def _write_index(self, index: Mapping[str, Path]) -> None:
        sessions = [
            {"id": session_id, "path": str(path)}
            for session_id, path in sorted(index.items())
        ]
        _write_json_atomic(self.sessions_dir / INDEX_FILE, {"sessions": sessions})

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
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(redact_for_storage(payload), ensure_ascii=False))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
