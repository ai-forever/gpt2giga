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
        # Drain the worker on cancellation: no detached writes outlive a request.
        task = asyncio.create_task(asyncio.to_thread(operation))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if cancel_event is not None:
                cancel_event.set()
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
                    for blob in (self.path / "blobs").iterdir():
                        if (
                            len(blob.name) == 32
                            and all(c in "0123456789abcdef" for c in blob.name)
                            and blob.name not in referenced
                        ):
                            blob.unlink(missing_ok=True)
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
        return len(rows)

    def _check_metadata_budget(self, db: sqlite3.Connection) -> None:
        count, size = db.execute(
            "SELECT COUNT(*), COALESCE(SUM(length(CAST(metadata AS BLOB))), 0) FROM resources"
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
            with self._lock:
                db = self._connection()
                try:
                    with db:
                        db.execute("BEGIN IMMEDIATE")
                        self._purge(db)
                        size = len(blob) if blob is not None else 0
                        total = db.execute(
                            "SELECT COALESCE(SUM(blob_size), 0) FROM resources"
                        ).fetchone()[0]
                        if total + size > self.max_total_blob_bytes:
                            raise ResourceLimitError(
                                "Resource store blob quota exceeded"
                            )
                        if blob is not None:
                            name = uuid.uuid4().hex
                            target = self.path / "blobs" / name
                            with target.open("xb") as stream:
                                os.chmod(target, 0o600)
                                stream.write(blob)
                                stream.flush()
                                os.fsync(stream.fileno())
                        now = self._clock()
                        expiry = (
                            expires_at
                            if expires_at is not None
                            else now + self.retention_seconds
                        )
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
                    return Resource(
                        public_id, kind, json.loads(encoded), now, expiry, size
                    )
                except BaseException:
                    if name:
                        (self.path / "blobs" / name).unlink(missing_ok=True)
                    raise

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
                self._purge(db)
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

        await self._run(operation, cancel_event=cancelled)

    async def read_blob(self, owner: str, kind: str, public_id: str) -> bytes | None:
        """Return bytes only for a live, owned local resource."""

        def operation() -> bytes | None:
            with self._lock, self._connection() as db:
                # A read transaction prevents another worker's delete until read ends.
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT blob_name FROM resources WHERE owner=? AND kind=? AND public_id=? AND expires_at>?",
                    (owner, kind, public_id, self._clock()),
                ).fetchone()
                return (
                    (self.path / "blobs" / row[0]).read_bytes()
                    if row and row[0]
                    else None
                )

        return await self._run(operation)

    async def append_blob(
        self, owner: str, kind: str, public_id: str, data: bytes, *, offset: int
    ) -> Resource | None:
        """Append a resumable chunk with atomic offset and quota checks."""

        def operation() -> Resource | None:
            with self._lock:
                db = self._connection()
                new_name = None
                old_name = None
                committed = False
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
                        if metadata.get("status") in {"finalizing", "finalized"}:
                            raise ResourceConflictError(
                                "Upload session no longer accepts data"
                            )
                        if row[5] != offset:
                            raise ResourceConflictError(
                                "Upload offset does not match received bytes"
                            )
                        size = offset + len(data)
                        total = db.execute(
                            "SELECT COALESCE(SUM(blob_size), 0) FROM resources"
                        ).fetchone()[0]
                        if (
                            size > self.max_blob_bytes
                            or total + len(data) > self.max_total_blob_bytes
                        ):
                            raise ResourceLimitError(
                                "Resource store blob quota exceeded"
                            )
                        old_name = row[6]
                        previous = (
                            (self.path / "blobs" / old_name).read_bytes()
                            if old_name
                            else b""
                        )
                        new_name = uuid.uuid4().hex
                        target = self.path / "blobs" / new_name
                        with target.open("xb") as stream:
                            os.chmod(target, 0o600)
                            stream.write(previous)
                            stream.write(data)
                            stream.flush()
                            os.fsync(stream.fileno())
                        metadata["upload_offset"] = size
                        encoded = json.dumps(
                            metadata, ensure_ascii=False, separators=(",", ":")
                        )
                        db.execute(
                            "UPDATE resources SET blob_name=?, blob_size=?, metadata=? WHERE owner=? AND kind=? AND public_id=?",
                            (new_name, size, encoded, owner, kind, public_id),
                        )
                        self._check_metadata_budget(db)
                    committed = True
                    if old_name:
                        (self.path / "blobs" / old_name).unlink(missing_ok=True)
                    return self._resource(
                        (row[0], row[1], encoded, row[3], row[4], size)
                    )
                except BaseException:
                    if new_name and not committed:
                        (self.path / "blobs" / new_name).unlink(missing_ok=True)
                    raise

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

    async def delete(self, owner: str, kind: str, public_id: str) -> bool:
        """Remove only the specified owner's metadata and local blob."""

        def operation() -> bool:
            with self._lock:
                with self._connection() as db:
                    db.execute("BEGIN IMMEDIATE")
                    row = db.execute(
                        "SELECT blob_name FROM resources WHERE owner=? AND kind=? AND public_id=?",
                        (owner, kind, public_id),
                    ).fetchone()
                    if row is None:
                        return False
                    db.execute(
                        "DELETE FROM resources WHERE owner=? AND kind=? AND public_id=?",
                        (owner, kind, public_id),
                    )
                # Commit the removal first: a crash may leave an orphan blob,
                # but can never resurrect a live resource pointing at deleted bytes.
                if row[0]:
                    (self.path / "blobs" / row[0]).unlink(missing_ok=True)
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
