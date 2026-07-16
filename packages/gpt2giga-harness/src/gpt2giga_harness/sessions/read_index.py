"""Derived SQLite lookup index for bounded session and run reads."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from typing import Iterable, Iterator

from gpt2giga_harness.sessions.models import (
    HarnessRun,
    HarnessSession,
    run_from_dict,
    run_to_dict,
    session_from_dict,
    session_to_dict,
)


@dataclass(frozen=True)
class SessionIndexCursor:
    """Stable newest-first position inside one index snapshot."""

    generation: int
    pinned: int
    updated_at: str
    session_id: str


@dataclass(frozen=True)
class SessionIndexPage:
    """One bounded page from the derived session index."""

    items: tuple[HarnessSession, ...]
    has_more: bool
    generation: int


class StaleReadSnapshotError(ValueError):
    """Raised when a cursor no longer names the current read snapshot."""


class SessionReadIndex:
    """Maintain rebuildable direct session and run lookup projections."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS read_index_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS read_index_sessions (
                    id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    pinned INTEGER NOT NULL,
                    archived INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    project_id TEXT,
                    workspace TEXT,
                    harness_id TEXT NOT NULL,
                    title_folded TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS read_index_sessions_order_idx
                    ON read_index_sessions(pinned DESC, updated_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS read_index_sessions_filter_idx
                    ON read_index_sessions(project_id, workspace, harness_id, archived);
                CREATE TABLE IF NOT EXISTS read_index_runs (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS read_index_runs_session_idx
                    ON read_index_runs(session_id, position);
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO read_index_meta(key, value) VALUES ('generation', '0')"
            )
            connection.execute(
                "INSERT OR IGNORE INTO read_index_meta(key, value) VALUES ('complete', '0')"
            )
            connection.execute(
                "INSERT OR IGNORE INTO read_index_meta(key, value) VALUES ('run_generation', '0')"
            )

    def is_complete(self) -> bool:
        """Return whether legacy state has been fully indexed."""
        with self._connect() as connection:
            return self._meta(connection, "complete") == "1"

    def replace_all(
        self,
        sessions: Iterable[HarnessSession],
        runs: Iterable[tuple[HarnessRun, int]],
    ) -> None:
        """Atomically rebuild the derived projection from authoritative JSON state."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM read_index_runs")
            connection.execute("DELETE FROM read_index_sessions")
            for session in sessions:
                self._upsert_session(connection, session)
            for run, position in runs:
                self._upsert_run(connection, run, position)
            generation = self._generation(connection) + 1
            self._set_meta(connection, "generation", str(generation))
            self._set_meta(
                connection,
                "run_generation",
                str(self._run_generation(connection) + 1),
            )
            self._set_meta(connection, "complete", "1")

    def upsert_session(self, session: HarnessSession) -> None:
        """Refresh one session projection and advance the list snapshot."""
        with self._connect() as connection:
            self._upsert_session(connection, session)
            if self._meta(connection, "complete") == "1":
                self._set_meta(
                    connection,
                    "generation",
                    str(self._generation(connection) + 1),
                )

    def delete_session(self, session_id: str) -> None:
        """Remove one session and its run lookup rows."""
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM read_index_runs WHERE session_id = ?", (session_id,)
            )
            connection.execute(
                "DELETE FROM read_index_sessions WHERE id = ?", (session_id,)
            )
            if self._meta(connection, "complete") == "1":
                self._set_meta(
                    connection,
                    "generation",
                    str(self._generation(connection) + 1),
                )

    def upsert_run(self, run: HarnessRun, position: int) -> None:
        """Refresh one direct run lookup row."""
        with self._connect() as connection:
            self._upsert_run(connection, run, position)
            if self._meta(connection, "complete") == "1":
                self._set_meta(
                    connection,
                    "run_generation",
                    str(self._run_generation(connection) + 1),
                )

    def runs_center_generation(self) -> tuple[int, int]:
        """Return cheap session/run generations for global live invalidation."""
        with self._connect() as connection:
            return self._generation(connection), self._run_generation(connection)

    def lookup_run(self, run_id: str) -> tuple[str, int, HarnessRun] | None:
        """Resolve one run without scanning session directories or run history."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT session_id, position, payload_json FROM read_index_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return str(row[0]), int(row[1]), run_from_dict(json.loads(str(row[2])))

    def list_sessions_page(
        self,
        *,
        project_id: str | None,
        workspace: str | None,
        harness_id: str | None,
        q: str | None,
        include_archived: bool,
        cursor: SessionIndexCursor | None,
        limit: int,
    ) -> SessionIndexPage:
        """Return a bounded stable-order page from indexed session summaries."""
        with self._connect() as connection:
            generation = self._generation(connection)
            if cursor is not None and cursor.generation != generation:
                raise StaleReadSnapshotError("session cursor snapshot is stale")
            clauses: list[str] = []
            values: list[object] = []
            if not include_archived:
                clauses.append("archived = 0")
            for column, value in (
                ("project_id", project_id),
                ("workspace", workspace),
                ("harness_id", harness_id),
            ):
                if value is not None:
                    clauses.append(f"{column} = ?")
                    values.append(value)
            if q:
                clauses.append("title_folded LIKE ? ESCAPE '\\'")
                values.append(f"%{_escape_like(q.casefold())}%")
            if cursor is not None:
                clauses.append(
                    "(pinned < ? OR (pinned = ? AND updated_at < ?) "
                    "OR (pinned = ? AND updated_at = ? AND id < ?))"
                )
                values.extend(
                    (
                        cursor.pinned,
                        cursor.pinned,
                        cursor.updated_at,
                        cursor.pinned,
                        cursor.updated_at,
                        cursor.session_id,
                    )
                )
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = connection.execute(
                f"""
                SELECT payload_json FROM read_index_sessions
                {where}
                ORDER BY pinned DESC, updated_at DESC, id DESC
                LIMIT ?
                """,
                (*values, max(limit, 0) + 1),
            ).fetchall()
        has_more = len(rows) > limit
        items = tuple(
            session_from_dict(json.loads(str(row[0]))) for row in rows[:limit]
        )
        return SessionIndexPage(
            items=items,
            has_more=has_more,
            generation=generation,
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA busy_timeout = 5000")
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _upsert_session(
        connection: sqlite3.Connection, session: HarnessSession
    ) -> None:
        connection.execute(
            """
            INSERT INTO read_index_sessions(
                id, payload_json, pinned, archived, updated_at, project_id,
                workspace, harness_id, title_folded
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                payload_json = excluded.payload_json,
                pinned = excluded.pinned,
                archived = excluded.archived,
                updated_at = excluded.updated_at,
                project_id = excluded.project_id,
                workspace = excluded.workspace,
                harness_id = excluded.harness_id,
                title_folded = excluded.title_folded
            """,
            (
                session.id,
                json.dumps(
                    session_to_dict(session), ensure_ascii=False, sort_keys=True
                ),
                int(session.pinned),
                int(session.archived),
                session.updated_at,
                str(session.metadata.get("project_id") or "") or None,
                session.workspace,
                session.default_harness_id,
                session.title.casefold(),
            ),
        )

    @staticmethod
    def _upsert_run(
        connection: sqlite3.Connection, run: HarnessRun, position: int
    ) -> None:
        connection.execute(
            """
            INSERT INTO read_index_runs(id, session_id, position, payload_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                session_id = excluded.session_id,
                position = excluded.position,
                payload_json = excluded.payload_json
            """,
            (
                run.id,
                run.session_id,
                max(position, 0),
                json.dumps(run_to_dict(run), ensure_ascii=False, sort_keys=True),
            ),
        )

    @staticmethod
    def _meta(connection: sqlite3.Connection, key: str) -> str:
        row = connection.execute(
            "SELECT value FROM read_index_meta WHERE key = ?", (key,)
        ).fetchone()
        return str(row[0]) if row is not None else "0"

    def _generation(self, connection: sqlite3.Connection) -> int:
        return int(self._meta(connection, "generation"))

    def _run_generation(self, connection: sqlite3.Connection) -> int:
        return int(self._meta(connection, "run_generation"))

    @staticmethod
    def _set_meta(connection: sqlite3.Connection, key: str, value: str) -> None:
        connection.execute(
            """
            INSERT INTO read_index_meta(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
