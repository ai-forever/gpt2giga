"""Durable, owner-scoped resource metadata and bounded local blobs."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TypeVar

from anyio import CancelScope

T = TypeVar("T")


class ResourceStoreError(RuntimeError):
    """Report unavailable storage without exposing stored content."""


class ResourceLimitError(ResourceStoreError):
    """Report a resource metadata, count, or blob quota violation."""


class ResourceConflictError(ResourceStoreError):
    """Report a concurrent change to a versioned resource."""


class ResourceNotFoundError(ResourceStoreError):
    """Report a missing owner-scoped resource during an atomic write."""


@dataclass(frozen=True)
class Resource:
    """One resource; metadata contains protocol-specific public fields."""

    public_id: str
    kind: str
    metadata: dict[str, Any]
    created_at: float
    expires_at: float
    blob_size: int = 0


class ResourceStore:
    """Serialize local I/O off-loop; SQLite transactions coordinate workers."""

    def __init__(
        self,
        path: str | Path,
        *,
        retention_seconds: int = 30 * 86400,
        max_blob_bytes: int = 100 * 1024 * 1024,
        max_total_blob_bytes: int = 1024 * 1024 * 1024,
        max_metadata_bytes: int = 64 * 1024 * 1024,
        max_resources: int = 100_000,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = Path(path)
        self.retention_seconds = retention_seconds
        self.max_blob_bytes = max_blob_bytes
        self.max_total_blob_bytes = max_total_blob_bytes
        self.max_metadata_bytes = max_metadata_bytes
        self.max_resources = max_resources
        self._clock = clock
        self._lock = threading.RLock()
        self._admission = asyncio.Lock()
        self._db: sqlite3.Connection | None = None
        self._secret: bytes | None = None

    @classmethod
    async def open(cls, path: str | Path, **kwargs: Any) -> "ResourceStore":
        """Open durable state; a failed open never falls back to memory."""
        store = cls(path, **kwargs)
        await store._run(store._open)
        return store

    async def _run(
        self, operation: Callable[[], T], *, cancel_event: threading.Event | None = None
    ) -> T:
        # Waiting operations must not occupy shared executor threads.
        async with self._admission:
            # Drain the worker on cancellation: no detached writes outlive a request.
            task = asyncio.create_task(asyncio.to_thread(operation))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                if cancel_event is not None:
                    cancel_event.set()
                with CancelScope(shield=True):
                    while not task.done():
                        try:
                            await asyncio.shield(task)
                        except asyncio.CancelledError:
                            continue
                        except Exception:
                            break
                try:
                    task.result()
                except Exception:
                    pass
                raise

    def _open(self) -> None:
        with self._lock:
            self.path.mkdir(parents=True, exist_ok=True, mode=0o700)
            (self.path / "blobs").mkdir(exist_ok=True, mode=0o700)
            db = sqlite3.connect(
                self.path / "resources.sqlite3", timeout=30, check_same_thread=False
            )
            try:
                os.chmod(self.path / "resources.sqlite3", 0o600)
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("PRAGMA synchronous=FULL")
                db.execute(
                    "CREATE TABLE IF NOT EXISTS store_settings (key TEXT PRIMARY KEY, value BLOB NOT NULL)"
                )
                db.execute("""CREATE TABLE IF NOT EXISTS resources (
                    owner TEXT NOT NULL, kind TEXT NOT NULL, public_id TEXT NOT NULL,
                    metadata TEXT NOT NULL, created_at REAL NOT NULL,
                    expires_at REAL NOT NULL, blob_name TEXT, blob_size INTEGER NOT NULL,
                    PRIMARY KEY(owner, kind, public_id))""")
                db.execute("""CREATE TABLE IF NOT EXISTS blob_cleanup (
                    blob_name TEXT PRIMARY KEY, blob_bytes INTEGER NOT NULL)""")
                db.execute("""CREATE TABLE IF NOT EXISTS resource_usage (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    resource_count INTEGER NOT NULL, metadata_bytes INTEGER NOT NULL,
                    blob_bytes INTEGER NOT NULL)""")
                db.execute("""INSERT OR REPLACE INTO resource_usage
                    SELECT 1, COUNT(*), COALESCE(SUM(length(CAST(metadata AS BLOB))),0),
                    COALESCE(SUM(blob_size),0) +
                    (SELECT COALESCE(SUM(blob_bytes),0) FROM blob_cleanup) FROM resources""")
                db.execute("""CREATE TRIGGER IF NOT EXISTS resource_usage_insert
                    AFTER INSERT ON resources BEGIN UPDATE resource_usage SET
                    resource_count=resource_count+1,
                    metadata_bytes=metadata_bytes+length(CAST(NEW.metadata AS BLOB)),
                    blob_bytes=blob_bytes+NEW.blob_size WHERE singleton=1; END""")
                db.execute("""CREATE TRIGGER IF NOT EXISTS resource_usage_delete
                    AFTER DELETE ON resources BEGIN UPDATE resource_usage SET
                    resource_count=resource_count-1,
                    metadata_bytes=metadata_bytes-length(CAST(OLD.metadata AS BLOB)),
                    blob_bytes=blob_bytes-OLD.blob_size WHERE singleton=1; END""")
                db.execute("""CREATE TRIGGER IF NOT EXISTS resource_usage_update
                    AFTER UPDATE OF metadata, blob_size ON resources
                    BEGIN UPDATE resource_usage SET
                    metadata_bytes=metadata_bytes+length(CAST(NEW.metadata AS BLOB))
                        -length(CAST(OLD.metadata AS BLOB)),
                    blob_bytes=blob_bytes+NEW.blob_size-OLD.blob_size
                    WHERE singleton=1; END""")
                db.execute("""CREATE TRIGGER IF NOT EXISTS blob_cleanup_insert
                    AFTER INSERT ON blob_cleanup BEGIN UPDATE resource_usage SET
                    blob_bytes=blob_bytes+NEW.blob_bytes WHERE singleton=1; END""")
                db.execute("""CREATE TRIGGER IF NOT EXISTS blob_cleanup_delete
                    AFTER DELETE ON blob_cleanup BEGIN UPDATE resource_usage SET
                    blob_bytes=blob_bytes-OLD.blob_bytes WHERE singleton=1; END""")
                db.execute("""CREATE TRIGGER IF NOT EXISTS blob_cleanup_update
                    AFTER UPDATE ON blob_cleanup BEGIN UPDATE resource_usage SET
                    blob_bytes=blob_bytes+NEW.blob_bytes-OLD.blob_bytes
                    WHERE singleton=1; END""")
                db.execute(
                    "CREATE TABLE IF NOT EXISTS registered_resources (kind TEXT NOT NULL, public_id TEXT NOT NULL, PRIMARY KEY(kind, public_id))"
                )
                db.execute(
                    "INSERT OR IGNORE INTO registered_resources SELECT kind, public_id FROM resources WHERE kind='file' AND public_id NOT GLOB 'file_g2g_*'"
                )
                # Only native file IDs can fall back to the upstream Files API.
                # Gateway-prefixed IDs and non-file resources are rejected locally.
                db.execute(
                    "DELETE FROM registered_resources WHERE kind!='file' OR public_id GLOB 'file_g2g_*'"
                )
                db.execute(
                    "CREATE INDEX IF NOT EXISTS resource_expiry ON resources(expires_at)"
                )
                db.execute(
                    "CREATE INDEX IF NOT EXISTS resource_public_id ON resources(kind, public_id)"
                )
                db.execute(
                    "CREATE INDEX IF NOT EXISTS resource_page ON resources(owner, kind, created_at, public_id)"
                )
                db.execute(
                    "INSERT OR IGNORE INTO store_settings VALUES ('namespace_secret', ?)",
                    (secrets.token_bytes(32),),
                )
                db.commit()
                self._secret = bytes(
                    db.execute(
                        "SELECT value FROM store_settings WHERE key='namespace_secret'"
                    ).fetchone()[0]
                )
                # A process may have died after writing a blob but before commit.
                # Hold the database writer lock so active workers cannot have an
                # unpublished blob while this startup reconciliation scans.
                with db:
                    db.execute("BEGIN IMMEDIATE")
                    referenced = {
                        row[0]
                        for row in db.execute(
                            "SELECT blob_name FROM resources WHERE blob_name IS NOT NULL"
                        )
                    }
                    for name, size in db.execute(
                        "SELECT blob_name, blob_size FROM resources WHERE kind='upload' AND blob_name IS NOT NULL"
                    ):
                        with (self.path / "blobs" / name).open("r+b") as stream:
                            stream.truncate(size)
                    for blob in (self.path / "blobs").iterdir():
                        if (
                            len(blob.name) == 32
                            and all(c in "0123456789abcdef" for c in blob.name)
                            and blob.name not in referenced
                        ):
                            blob.unlink(missing_ok=True)
                    db.execute("DELETE FROM blob_cleanup")
                self._db = db
            except BaseException:
                db.close()
                raise

    def _connection(self) -> sqlite3.Connection:
        if self._db is None:
            raise ResourceStoreError("Resource store is not open")
        return self._db

    def owner_namespace(
        self,
        identity: str = "anonymous",
        *,
        provider: str = "gigachat",
        profile: str = "default",
        credential_context: str = "",
    ) -> str:
        """Hash trusted identity/context; never persist raw credentials."""
        if self._secret is None or self._db is None:
            raise ResourceStoreError("Resource store is not open")
        payload = json.dumps(
            [identity, provider, profile, credential_context],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest()

    @staticmethod
    def _resource(row: tuple) -> Resource:
        return Resource(row[0], row[1], json.loads(row[2]), row[3], row[4], row[5])

    def _purge(self, db: sqlite3.Connection) -> int:
        # Bound foreground cleanup. Registered IDs are intentional ACL tombstones.
        for (name,) in db.execute(
            "SELECT blob_name FROM blob_cleanup LIMIT 256"
        ).fetchall():
            self._recover_blob(db, name)
        rows = db.execute(
            "SELECT rowid, blob_name FROM resources WHERE expires_at <= ? ORDER BY expires_at LIMIT 256",
            (self._clock(),),
        ).fetchall()
        db.executemany(
            "DELETE FROM resources WHERE rowid=?", [(row[0],) for row in rows]
        )
        for _, name in rows:
            if name:
                (self.path / "blobs" / name).unlink(missing_ok=True)
                db.execute("DELETE FROM blob_cleanup WHERE blob_name=?", (name,))
        return len(rows)

    def _recover_blob(
        self, db: sqlite3.Connection, name: str, *, attempted_size: int = 0
    ) -> None:
        """Trim unpublished bytes under the writer lock, charging failed cleanup."""
        row = db.execute(
            "SELECT blob_size FROM resources WHERE blob_name=?", (name,)
        ).fetchone()
        size = row[0] if row else 0
        target = self.path / "blobs" / name
        charged = db.execute(
            "SELECT blob_bytes FROM blob_cleanup WHERE blob_name=?", (name,)
        ).fetchone()
        fallback_size = max(attempted_size, size + (charged[0] if charged else 0))
        try:
            if row:
                with target.open("r+b") as stream:
                    stream.truncate(size)
                    stream.flush()
                    os.fsync(stream.fileno())
            else:
                target.unlink(missing_ok=True)
        except OSError:
            # A failed cleanup must not make physically occupied capacity free.
            pass
        try:
            remaining = max(0, target.stat().st_size - size)
        except FileNotFoundError:
            remaining = 0
        except OSError:
            # Inaccessible files still occupy capacity. Keep the conservative
            # admitted size until a later cleanup can establish their size.
            remaining = max(0, fallback_size - size)
        if remaining:
            db.execute(
                "INSERT INTO blob_cleanup VALUES (?, ?) ON CONFLICT(blob_name) "
                "DO UPDATE SET blob_bytes=excluded.blob_bytes",
                (name, remaining),
            )
        else:
            db.execute("DELETE FROM blob_cleanup WHERE blob_name=?", (name,))

    def _check_metadata_budget(self, db: sqlite3.Connection) -> None:
        count, size = db.execute(
            "SELECT resource_count, metadata_bytes FROM resource_usage WHERE singleton=1"
        ).fetchone()
        if count > self.max_resources or size > self.max_metadata_bytes:
            raise ResourceLimitError("Resource store metadata quota exceeded")

    async def purge_expired(self) -> int:
        """Remove retained metadata/blobs; delivery deadlines are metadata only."""

        def operation() -> int:
            with self._lock, self._connection() as db:
                db.execute("BEGIN IMMEDIATE")
                return self._purge(db)

        return await self._run(operation)

    async def put(
        self,
        owner: str,
        kind: str,
        public_id: str,
        metadata: dict[str, Any],
        *,
        blob: bytes | None = None,
        expires_at: float | None = None,
    ) -> Resource:
        """Atomically publish a new resource; duplicate IDs require update."""
        encoded = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
        if blob is not None and len(blob) > self.max_blob_bytes:
            raise ResourceLimitError("Resource exceeds the per-blob size limit")

        def operation() -> Resource:
            name = None
            touched = False
            failure = None
            with self._lock:
                db = self._connection()
                try:
                    with db:
                        db.execute("BEGIN IMMEDIATE")
                        size = len(blob) if blob is not None else 0
                        total = db.execute(
                            "SELECT blob_bytes FROM resource_usage WHERE singleton=1"
                        ).fetchone()[0]
                        if total + size > self.max_total_blob_bytes:
                            raise ResourceLimitError(
                                "Resource store blob quota exceeded"
                            )
                        if blob is not None:
                            name = uuid.uuid4().hex
                        now = self._clock()
                        expiry = (
                            expires_at
                            if expires_at is not None
                            else now + self.retention_seconds
                        )
                        db.execute("SAVEPOINT put_resource")
                        if kind == "file" and not public_id.startswith("file_g2g_"):
                            db.execute(
                                "INSERT OR IGNORE INTO registered_resources VALUES (?, ?)",
                                (kind, public_id),
                            )
                        db.execute(
                            "INSERT INTO resources VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (owner, kind, public_id, encoded, now, expiry, name, size),
                        )
                        self._check_metadata_budget(db)
                        if blob is not None:
                            target = self.path / "blobs" / name
                            try:
                                with target.open("xb") as stream:
                                    touched = True
                                    os.chmod(target, 0o600)
                                    stream.write(blob)
                                    stream.flush()
                                    os.fsync(stream.fileno())
                            except BaseException as exc:
                                failure = exc
                                db.execute("ROLLBACK TO put_resource")
                                if touched:
                                    self._recover_blob(db, name, attempted_size=size)
                        db.execute("RELEASE put_resource")
                except BaseException:
                    if touched:
                        # Commit failure may release the writer lock. Recover
                        # against committed state after acquiring it again.
                        try:
                            with db:
                                db.execute("BEGIN IMMEDIATE")
                                self._recover_blob(db, name, attempted_size=size)
                        except Exception:
                            # A broken database must not replace the write error.
                            # Startup reconciliation still owns any orphan blob.
                            pass
                    if failure is not None:
                        raise failure
                    raise
                if failure is not None:
                    raise failure
                return Resource(public_id, kind, json.loads(encoded), now, expiry, size)

        await self.purge_expired()
        return await self._run(operation)

    async def get(self, owner: str, kind: str, public_id: str) -> Resource | None:
        """Read a live resource only within its owner namespace."""

        def operation() -> Resource | None:
            with self._lock, self._connection() as db:
                row = db.execute(
                    "SELECT public_id, kind, metadata, created_at, expires_at, blob_size FROM resources WHERE owner=? AND kind=? AND public_id=? AND expires_at>?",
                    (owner, kind, public_id, self._clock()),
                ).fetchone()
                return self._resource(row) if row else None

        return await self._run(operation)

    async def is_registered(self, kind: str, public_id: str) -> bool:
        """Prevent legacy upstream fallback from bypassing another owner."""

        def operation() -> bool:
            with self._lock:
                return (
                    self._connection()
                    .execute(
                        "SELECT 1 FROM registered_resources WHERE kind=? AND public_id=? LIMIT 1",
                        (kind, public_id),
                    )
                    .fetchone()
                    is not None
                )

        return await self._run(operation)

    async def list(self, owner: str, kind: str) -> list[Resource]:
        """Return live resources in stable creation/ID order."""

        def operation() -> list[Resource]:
            with self._lock:
                rows = (
                    self._connection()
                    .execute(
                        "SELECT public_id, kind, metadata, created_at, expires_at, blob_size FROM resources WHERE owner=? AND kind=? AND expires_at>? ORDER BY created_at, public_id",
                        (owner, kind, self._clock()),
                    )
                    .fetchall()
                )
                return [self._resource(row) for row in rows]

        return await self._run(operation)

    async def page(
        self,
        owners: set[str],
        kind: str,
        *,
        protocol: str,
        limit: int,
        after: str | None = None,
        before: str | None = None,
    ) -> list[Resource]:
        """Read at most limit+1 rows after an owned, protocol-scoped cursor."""

        def operation() -> list[Resource]:
            with self._lock:
                db = self._connection()
                scope = (
                    f"owner IN ({','.join('?' for _ in owners)}) AND kind=? "
                    "AND expires_at>? AND json_extract(metadata, '$.protocol')=?"
                )
                args = [*sorted(owners), kind, self._clock(), protocol]
                cursor = ""
                for value, operator in ((after, "<"), (before, ">")):
                    if value is None:
                        continue
                    row = db.execute(
                        f"SELECT created_at, public_id FROM resources WHERE {scope}{cursor} AND public_id=?",
                        (*args, value),
                    ).fetchone()
                    if row is None:
                        raise ResourceNotFoundError("Invalid resource cursor")
                    cursor += f" AND (created_at, public_id) {operator} (?, ?)"
                    args.extend(row)
                rows = db.execute(
                    "SELECT public_id, kind, metadata, created_at, expires_at, blob_size "
                    f"FROM resources WHERE {scope}{cursor} "
                    "ORDER BY created_at DESC, public_id DESC LIMIT ?",
                    (*args, limit + 1),
                ).fetchall()
                return [self._resource(row) for row in rows]

        return await self._run(operation)

    async def update(
        self,
        owner: str,
        kind: str,
        public_id: str,
        updates: dict[str, Any] | Callable[[dict[str, Any]], dict[str, Any]],
    ) -> Resource | None:
        """Atomically merge fields, or transform metadata under the write lock."""

        def operation() -> Resource | None:
            with self._lock, self._connection() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT public_id, kind, metadata, created_at, expires_at, blob_size FROM resources WHERE owner=? AND kind=? AND public_id=? AND expires_at>?",
                    (owner, kind, public_id, self._clock()),
                ).fetchone()
                if row is None:
                    return None
                metadata = json.loads(row[2])
                metadata = (
                    updates(metadata) if callable(updates) else {**metadata, **updates}
                )
                encoded = json.dumps(
                    metadata, ensure_ascii=False, separators=(",", ":")
                )
                if encoded == row[2]:
                    return self._resource(row)
                if kind == "file_upload" and metadata.get("upstream_id"):
                    db.execute(
                        "INSERT OR IGNORE INTO registered_resources VALUES ('file', ?)",
                        (metadata["upstream_id"],),
                    )
                db.execute(
                    "UPDATE resources SET metadata=? WHERE owner=? AND kind=? AND public_id=?",
                    (encoded, owner, kind, public_id),
                )
                self._check_metadata_budget(db)
                return self._resource((row[0], row[1], encoded, *row[3:]))

        return await self._run(operation)

    async def commit_response(
        self,
        owner: str,
        response_id: str,
        response_metadata: dict[str, Any] | None,
        *,
        conversation_id: str | None = None,
        conversation_owner: str | None = None,
        expected_revision: int | None = None,
        conversation_items: list[dict] | None = None,
    ) -> None:
        """Commit one completed snapshot and its conversation turn together."""
        encoded = (
            json.dumps(response_metadata, ensure_ascii=False, separators=(",", ":"))
            if response_metadata is not None
            else None
        )
        cancelled = threading.Event()

        def operation() -> None:
            with self._lock, self._connection() as db:
                db.execute("BEGIN IMMEDIATE")
                now = self._clock()
                if conversation_id is not None:
                    row = db.execute(
                        "SELECT metadata FROM resources WHERE owner=? AND kind='conversation' AND public_id=? AND expires_at>?",
                        (conversation_owner or owner, conversation_id, now),
                    ).fetchone()
                    if row is None:
                        raise ResourceNotFoundError("Conversation no longer exists")
                    metadata = json.loads(row[0])
                    if metadata["revision"] != expected_revision:
                        raise ResourceConflictError(
                            "Conversation changed during generation"
                        )
                    metadata.update(
                        items=conversation_items, revision=expected_revision + 1
                    )
                    db.execute(
                        "UPDATE resources SET metadata=? WHERE owner=? AND kind='conversation' AND public_id=?",
                        (
                            json.dumps(
                                metadata, ensure_ascii=False, separators=(",", ":")
                            ),
                            conversation_owner or owner,
                            conversation_id,
                        ),
                    )
                if encoded is not None:
                    db.execute(
                        "INSERT INTO resources VALUES (?, 'response', ?, ?, ?, ?, NULL, 0)",
                        (
                            owner,
                            response_id,
                            encoded,
                            now,
                            now + self.retention_seconds,
                        ),
                    )
                self._check_metadata_budget(db)
                if cancelled.is_set():
                    raise ResourceStoreError("Response storage cancelled")

        await self.purge_expired()
        await self._run(operation, cancel_event=cancelled)

    async def read_blob(self, owner: str, kind: str, public_id: str) -> bytes | None:
        """Return bytes only for a live, owned local resource."""

        def operation() -> bytes | None:
            with self._lock, self._connection() as db:
                # A read transaction prevents another worker's delete until read ends.
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT blob_name, blob_size FROM resources WHERE owner=? AND kind=? AND public_id=? AND expires_at>?",
                    (owner, kind, public_id, self._clock()),
                ).fetchone()
                if row and row[0]:
                    with (self.path / "blobs" / row[0]).open("rb") as stream:
                        return stream.read(row[1])
                return None

        return await self._run(operation)

    async def append_blob(
        self, owner: str, kind: str, public_id: str, data: bytes, *, offset: int
    ) -> Resource | None:
        """Append a resumable chunk with atomic offset and quota checks."""

        def operation() -> Resource | None:
            with self._lock:
                db = self._connection()
                name = None
                touched = False
                failure = None
                try:
                    with db:
                        db.execute("BEGIN IMMEDIATE")
                        row = db.execute(
                            "SELECT public_id, kind, metadata, created_at, expires_at, blob_size, blob_name FROM resources WHERE owner=? AND kind=? AND public_id=? AND expires_at>?",
                            (owner, kind, public_id, self._clock()),
                        ).fetchone()
                        if row is None:
                            return None
                        metadata = json.loads(row[2])
                        if metadata.get("status") in {
                            "finalizing",
                            "finalized",
                            "cancelled",
                        }:
                            raise ResourceConflictError(
                                "Upload session no longer accepts data"
                            )
                        if row[5] != offset:
                            raise ResourceConflictError(
                                "Upload offset does not match received bytes"
                            )
                        if (
                            row[6]
                            and db.execute(
                                "SELECT 1 FROM blob_cleanup WHERE blob_name=?",
                                (row[6],),
                            ).fetchone()
                        ):
                            self._recover_blob(db, row[6])
                        size = offset + len(data)
                        total = db.execute(
                            "SELECT blob_bytes FROM resource_usage WHERE singleton=1"
                        ).fetchone()[0]
                        if (
                            size > self.max_blob_bytes
                            or total + len(data) > self.max_total_blob_bytes
                        ):
                            raise ResourceLimitError(
                                "Resource store blob quota exceeded"
                            )
                        name = row[6] or uuid.uuid4().hex
                        metadata["upload_offset"] = size
                        encoded = json.dumps(
                            metadata, ensure_ascii=False, separators=(",", ":")
                        )
                        db.execute("SAVEPOINT append_chunk")
                        db.execute(
                            "UPDATE resources SET blob_name=?, blob_size=?, metadata=? WHERE owner=? AND kind=? AND public_id=?",
                            (name, size, encoded, owner, kind, public_id),
                        )
                        # The future count/metadata/blob usage is admitted before I/O.
                        self._check_metadata_budget(db)
                        target = self.path / "blobs" / name
                        try:
                            touched = True
                            with target.open("r+b" if row[6] else "x+b") as stream:
                                os.chmod(target, 0o600)
                                stream.truncate(row[5])
                                stream.seek(row[5])
                                stream.write(data)
                                stream.flush()
                                os.fsync(stream.fileno())
                        except BaseException as exc:
                            db.execute("ROLLBACK TO append_chunk")
                            self._recover_blob(db, name, attempted_size=size)
                            failure = exc
                        db.execute("RELEASE append_chunk")
                except BaseException:
                    if touched and name:
                        # Commit/rollback can release the lock. Never use the old
                        # offset here: another worker may already have appended.
                        with db:
                            db.execute("BEGIN IMMEDIATE")
                            self._recover_blob(db, name, attempted_size=size)
                    raise
                if failure is not None:
                    raise failure
                return self._resource((row[0], row[1], encoded, row[3], row[4], size))

        return await self._run(operation)

    async def promote_blob(
        self,
        owner: str,
        source_kind: str,
        source_id: str,
        kind: str,
        public_id: str,
        metadata: dict[str, Any],
    ) -> Resource:
        """Adopt an owned upload blob without copying or charging quota twice."""
        encoded = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))

        def operation() -> Resource:
            with self._lock, self._connection() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT blob_name, blob_size FROM resources WHERE owner=? AND kind=? AND public_id=? AND expires_at>?",
                    (owner, source_kind, source_id, self._clock()),
                ).fetchone()
                if row is None:
                    raise ResourceNotFoundError("Upload session no longer exists")
                now = self._clock()
                expiry = now + self.retention_seconds
                if kind == "file" and not public_id.startswith("file_g2g_"):
                    db.execute(
                        "INSERT OR IGNORE INTO registered_resources VALUES (?, ?)",
                        (kind, public_id),
                    )
                db.execute(
                    "INSERT INTO resources VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (owner, kind, public_id, encoded, now, expiry, row[0], row[1]),
                )
                db.execute(
                    "DELETE FROM resources WHERE owner=? AND kind=? AND public_id=?",
                    (owner, source_kind, source_id),
                )
                self._check_metadata_budget(db)
                return Resource(
                    public_id, kind, json.loads(encoded), now, expiry, row[1]
                )

        return await self._run(operation)

    async def delete(
        self,
        owner: str,
        kind: str,
        public_id: str,
        *,
        expected_status: str | None = None,
    ) -> bool:
        """Remove only the specified owner's metadata and local blob."""

        def operation() -> bool:
            with self._lock:
                with self._connection() as db:
                    db.execute("BEGIN IMMEDIATE")
                    row = db.execute(
                        "SELECT blob_name, metadata, blob_size FROM resources WHERE owner=? AND kind=? AND public_id=?",
                        (owner, kind, public_id),
                    ).fetchone()
                    if row is None:
                        return False
                    if (
                        expected_status is not None
                        and json.loads(row[1]).get("status") != expected_status
                    ):
                        raise ResourceConflictError(
                            "Resource status changed concurrently"
                        )
                    if row[0]:
                        # Transfer the committed prefix to cleanup ownership in
                        # the same transaction; a crash before unlink cannot
                        # make its physical capacity available to another writer.
                        db.execute(
                            "INSERT INTO blob_cleanup VALUES (?, ?) "
                            "ON CONFLICT(blob_name) DO UPDATE SET "
                            "blob_bytes=blob_cleanup.blob_bytes+excluded.blob_bytes",
                            (row[0], row[2]),
                        )
                    db.execute(
                        "DELETE FROM resources WHERE owner=? AND kind=? AND public_id=?",
                        (owner, kind, public_id),
                    )
                # Commit the removal first: a crash may leave an orphan blob,
                # but can never resurrect a live resource pointing at deleted bytes.
                if row[0]:
                    with db:
                        db.execute("BEGIN IMMEDIATE")
                        self._recover_blob(db, row[0])
                return True

        return await self._run(operation)

    async def aclose(self) -> None:
        """Drain the store and close its single connection."""

        def operation() -> None:
            with self._lock:
                if self._db is not None:
                    self._db.close()
                    self._db = None
                    self._secret = None

        await self._run(operation)
