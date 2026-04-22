"""SQLite-backed runtime backend implementation."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping, MutableMapping
from pathlib import Path
from threading import RLock
from typing import Any

from .contracts import EventFeed, RuntimeStateBackend

_FEED_FILTER_COLUMNS: dict[str, str] = {
    "provider": "provider",
    "endpoint": "endpoint",
    "method": "method",
    "status_code": "status_code",
    "model": "model",
    "error_type": "error_type",
}


class SqliteMapping(MutableMapping[str, Any]):
    """Persist a mapping resource inside the runtime SQLite database."""

    def __init__(self, backend: SqliteRuntimeStateBackend, resource_name: str):
        self._backend = backend
        self._resource_name = resource_name

    def __getitem__(self, key: str) -> Any:
        value = self._backend.mapping_get(self._resource_name, key)
        if value is None:
            raise KeyError(key)
        return value

    def __setitem__(self, key: str, value: Any) -> None:
        self._backend.mapping_set(self._resource_name, key, value)

    def __delitem__(self, key: str) -> None:
        if not self._backend.mapping_delete(self._resource_name, key):
            raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return iter(self._backend.mapping_keys(self._resource_name))

    def __len__(self) -> int:
        return self._backend.mapping_count(self._resource_name)

    def clear(self) -> None:
        """Remove all tracked entries from the mapping."""
        self._backend.mapping_clear(self._resource_name)


class SqliteEventFeed:
    """Persist a bounded recent-events feed inside the runtime SQLite database."""

    def __init__(
        self,
        backend: SqliteRuntimeStateBackend,
        feed_name: str,
        *,
        max_items: int,
    ):
        self._backend = backend
        self._feed_name = feed_name
        self._max_items = max_items

    def configure(self, *, max_items: int) -> None:
        """Update the feed capacity and prune retained rows if needed."""
        self._max_items = max_items
        self._backend.feed_prune(self._feed_name, max_items=max_items)

    def append(self, item: Any) -> None:
        """Append an event and keep only the most recent retained rows."""
        self._backend.feed_append(self._feed_name, item, max_items=self._max_items)

    def recent(self, *, limit: int | None = None) -> list[Any]:
        """Return recent items in chronological order."""
        return self.query(limit=limit)

    def query(
        self,
        *,
        limit: int | None = None,
        filters: Mapping[str, Any] | None = None,
    ) -> list[Any]:
        """Return recent items filtered by equality-match fields."""
        return self._backend.feed_query(
            self._feed_name,
            limit=limit,
            filters=filters,
        )

    def clear(self) -> None:
        """Drop all tracked rows."""
        self._backend.feed_clear(self._feed_name)

    def __len__(self) -> int:
        """Return the number of retained rows."""
        return self._backend.feed_count(self._feed_name)


class SqliteRuntimeStateBackend(RuntimeStateBackend):
    """Provision runtime resources from a durable SQLite database."""

    name = "sqlite"

    def __init__(
        self,
        *,
        dsn: str | None = None,
        namespace: str = "gpt2giga",
        logger: Any | None = None,
    ) -> None:
        self._path = _resolve_sqlite_path(dsn, namespace)
        self._namespace = namespace or "gpt2giga"
        self._logger = logger
        self._lock = RLock()
        self._connection: sqlite3.Connection | None = None
        self._mappings: dict[str, SqliteMapping] = {}
        self._feeds: dict[str, SqliteEventFeed] = {}

    async def open(self) -> None:
        """Open the SQLite database eagerly during application startup."""
        self._get_connection()

    async def close(self) -> None:
        """Close the SQLite database connection if it was opened."""
        with self._lock:
            if self._connection is None:
                return
            self._connection.close()
            self._connection = None

    def mapping(self, name: str) -> MutableMapping[str, Any]:
        """Return a stable SQLite-backed mapping resource."""
        mapping = self._mappings.get(name)
        if mapping is None:
            mapping = SqliteMapping(self, name)
            self._mappings[name] = mapping
        return mapping

    def feed(self, name: str, *, max_items: int) -> EventFeed:
        """Return a stable SQLite-backed recent-events feed."""
        feed = self._feeds.get(name)
        if feed is None:
            feed = SqliteEventFeed(self, name, max_items=max_items)
            self._feeds[name] = feed
        else:
            feed.configure(max_items=max_items)
        return feed

    def mapping_get(self, resource_name: str, key: str) -> Any | None:
        """Load a single mapping item from SQLite."""
        row = self._fetchone(
            """
            SELECT item_value
            FROM runtime_mapping_entries
            WHERE namespace = ? AND resource_name = ? AND item_key = ?
            """,
            (self._namespace, resource_name, key),
        )
        if row is None:
            return None
        return json.loads(str(row["item_value"]))

    def mapping_set(self, resource_name: str, key: str, value: Any) -> None:
        """Upsert a mapping item into SQLite."""
        payload = json.dumps(value)
        self._execute(
            """
            INSERT INTO runtime_mapping_entries (
                namespace,
                resource_name,
                item_key,
                item_value
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(namespace, resource_name, item_key)
            DO UPDATE SET item_value = excluded.item_value
            """,
            (self._namespace, resource_name, key, payload),
        )

    def mapping_delete(self, resource_name: str, key: str) -> bool:
        """Delete a mapping item from SQLite."""
        cursor = self._execute(
            """
            DELETE FROM runtime_mapping_entries
            WHERE namespace = ? AND resource_name = ? AND item_key = ?
            """,
            (self._namespace, resource_name, key),
        )
        return cursor.rowcount > 0

    def mapping_keys(self, resource_name: str) -> list[str]:
        """List keys stored for a mapping resource."""
        rows = self._fetchall(
            """
            SELECT item_key
            FROM runtime_mapping_entries
            WHERE namespace = ? AND resource_name = ?
            ORDER BY item_key
            """,
            (self._namespace, resource_name),
        )
        return [str(row["item_key"]) for row in rows]

    def mapping_count(self, resource_name: str) -> int:
        """Return the number of stored mapping entries."""
        row = self._fetchone(
            """
            SELECT COUNT(*) AS item_count
            FROM runtime_mapping_entries
            WHERE namespace = ? AND resource_name = ?
            """,
            (self._namespace, resource_name),
        )
        return int(row["item_count"]) if row is not None else 0

    def mapping_clear(self, resource_name: str) -> None:
        """Delete all entries for a mapping resource."""
        self._execute(
            """
            DELETE FROM runtime_mapping_entries
            WHERE namespace = ? AND resource_name = ?
            """,
            (self._namespace, resource_name),
        )

    def feed_append(self, feed_name: str, item: Any, *, max_items: int) -> None:
        """Append an event row and prune retained history."""
        columns = _extract_feed_columns(item)
        payload = json.dumps(item)
        self._execute(
            """
            INSERT INTO runtime_feed_events (
                namespace,
                feed_name,
                payload,
                provider,
                endpoint,
                method,
                status_code,
                model,
                error_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self._namespace,
                feed_name,
                payload,
                columns["provider"],
                columns["endpoint"],
                columns["method"],
                columns["status_code"],
                columns["model"],
                columns["error_type"],
            ),
        )
        self.feed_prune(feed_name, max_items=max_items)

    def feed_query(
        self,
        feed_name: str,
        *,
        limit: int | None = None,
        filters: Mapping[str, Any] | None = None,
    ) -> list[Any]:
        """Return feed rows filtered by indexed request-audit columns."""
        normalized_filters = {
            key: value for key, value in (filters or {}).items() if value is not None
        }
        sql_filters = {
            key: value
            for key, value in normalized_filters.items()
            if key in _FEED_FILTER_COLUMNS
        }
        extra_filters = {
            key: value
            for key, value in normalized_filters.items()
            if key not in _FEED_FILTER_COLUMNS
        }

        params: list[Any] = [self._namespace, feed_name]
        if limit is not None:
            sql = """
                WITH recent_events AS (
                    SELECT
                        event_id,
                        payload,
                        provider,
                        endpoint,
                        method,
                        status_code,
                        model,
                        error_type
                    FROM runtime_feed_events
                    WHERE namespace = ? AND feed_name = ?
                    ORDER BY event_id DESC
                    LIMIT ?
                )
                SELECT event_id, payload
                FROM recent_events
            """
            params.append(limit)
        else:
            sql = """
                SELECT event_id, payload
                FROM runtime_feed_events
                WHERE namespace = ? AND feed_name = ?
            """

        if sql_filters:
            predicates = [
                f"{_FEED_FILTER_COLUMNS[key]} = ?" for key in sorted(sql_filters)
            ]
            separator = " WHERE " if "FROM recent_events" in sql else " AND "
            sql += separator + " AND ".join(predicates)
            params.extend(sql_filters[key] for key in sorted(sql_filters))

        sql += " ORDER BY event_id DESC"
        rows = self._fetchall(sql, tuple(params))
        items = [json.loads(str(row["payload"])) for row in rows]
        if extra_filters:
            items = [
                item
                for item in items
                if isinstance(item, Mapping)
                and all(item.get(key) == value for key, value in extra_filters.items())
            ]
        items.reverse()
        return items

    def feed_count(self, feed_name: str) -> int:
        """Return the number of retained feed rows."""
        row = self._fetchone(
            """
            SELECT COUNT(*) AS item_count
            FROM runtime_feed_events
            WHERE namespace = ? AND feed_name = ?
            """,
            (self._namespace, feed_name),
        )
        return int(row["item_count"]) if row is not None else 0

    def feed_clear(self, feed_name: str) -> None:
        """Delete all rows for a named feed."""
        self._execute(
            """
            DELETE FROM runtime_feed_events
            WHERE namespace = ? AND feed_name = ?
            """,
            (self._namespace, feed_name),
        )

    def feed_prune(self, feed_name: str, *, max_items: int) -> None:
        """Keep only the newest ``max_items`` rows for a named feed."""
        self._execute(
            """
            DELETE FROM runtime_feed_events
            WHERE namespace = ?
              AND feed_name = ?
              AND event_id NOT IN (
                    SELECT event_id
                    FROM runtime_feed_events
                    WHERE namespace = ? AND feed_name = ?
                    ORDER BY event_id DESC
                    LIMIT ?
              )
            """,
            (self._namespace, feed_name, self._namespace, feed_name, max_items),
        )

    def _get_connection(self) -> sqlite3.Connection:
        with self._lock:
            if self._connection is not None:
                return self._connection

            self._path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(
                self._path,
                check_same_thread=False,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            self._initialize_schema(connection)
            self._connection = connection
            if self._logger is not None:
                self._logger.info(
                    f"Runtime SQLite backend initialized at {str(self._path)}"
                )
            return connection

    def _initialize_schema(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS runtime_mapping_entries (
                namespace TEXT NOT NULL,
                resource_name TEXT NOT NULL,
                item_key TEXT NOT NULL,
                item_value TEXT NOT NULL,
                PRIMARY KEY (namespace, resource_name, item_key)
            );

            CREATE TABLE IF NOT EXISTS runtime_feed_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                namespace TEXT NOT NULL,
                feed_name TEXT NOT NULL,
                payload TEXT NOT NULL,
                provider TEXT,
                endpoint TEXT,
                method TEXT,
                status_code INTEGER,
                model TEXT,
                error_type TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_runtime_feed_recent
                ON runtime_feed_events (namespace, feed_name, event_id DESC);

            CREATE INDEX IF NOT EXISTS idx_runtime_feed_provider
                ON runtime_feed_events (namespace, feed_name, provider, event_id DESC);

            CREATE INDEX IF NOT EXISTS idx_runtime_feed_endpoint
                ON runtime_feed_events (namespace, feed_name, endpoint, event_id DESC);

            CREATE INDEX IF NOT EXISTS idx_runtime_feed_method
                ON runtime_feed_events (namespace, feed_name, method, event_id DESC);

            CREATE INDEX IF NOT EXISTS idx_runtime_feed_status_code
                ON runtime_feed_events (
                    namespace,
                    feed_name,
                    status_code,
                    event_id DESC
                );

            CREATE INDEX IF NOT EXISTS idx_runtime_feed_model
                ON runtime_feed_events (namespace, feed_name, model, event_id DESC);

            CREATE INDEX IF NOT EXISTS idx_runtime_feed_error_type
                ON runtime_feed_events (
                    namespace,
                    feed_name,
                    error_type,
                    event_id DESC
                );
            """
        )
        connection.commit()

    def _execute(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        with self._lock:
            cursor = self._get_connection().execute(sql, params)
            self._get_connection().commit()
            return cursor

    def _fetchall(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
    ) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._get_connection().execute(sql, params).fetchall())

    def _fetchone(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Row | None:
        with self._lock:
            return self._get_connection().execute(sql, params).fetchone()


def _extract_feed_columns(item: Any) -> dict[str, Any]:
    """Extract indexed filter columns from a feed item when available."""
    if not isinstance(item, Mapping):
        return {
            "provider": None,
            "endpoint": None,
            "method": None,
            "status_code": None,
            "model": None,
            "error_type": None,
        }
    status_code = item.get("status_code")
    return {
        "provider": item.get("provider"),
        "endpoint": item.get("endpoint"),
        "method": item.get("method"),
        "status_code": _safe_int(status_code) if status_code is not None else None,
        "model": item.get("model"),
        "error_type": item.get("error_type"),
    }


def _resolve_sqlite_path(dsn: str | None, namespace: str) -> Path:
    """Resolve a runtime SQLite path from config settings."""
    if isinstance(dsn, str):
        normalized = dsn.strip()
        if normalized.startswith("sqlite:///"):
            return Path(normalized.removeprefix("sqlite:///")).expanduser()
        if normalized:
            return Path(normalized).expanduser()

    safe_namespace = (namespace or "gpt2giga").replace("/", "_")
    return Path(f".gpt2giga-runtime-{safe_namespace}.sqlite3")


def _safe_int(value: Any) -> int | None:
    """Convert SQLite feed values to ints when possible."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
