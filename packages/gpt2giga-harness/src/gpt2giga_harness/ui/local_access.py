"""Private server-side state for the loopback GigaLoom UI session."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
import json
import os
from pathlib import Path
import secrets
import stat
import time
from typing import Any
from uuid import uuid4

from gpt2giga_harness.sessions.locking import exclusive_file_lock

LOCAL_UI_SESSION_TTL_SECONDS = 12 * 60 * 60
_SCHEMA_VERSION = 1


class LocalUIAccessError(RuntimeError):
    """Raised when private local UI access state is unsafe or invalid."""


@dataclass(frozen=True)
class LocalUISession:
    """Opaque browser session material returned only to the cookie boundary."""

    token: str
    expires_at: float


@dataclass(frozen=True)
class LocalUIAccessStatus:
    """Content-free local access state safe for UI projection."""

    authenticated: bool
    claimable: bool
    expires_at: float | None
    recovery: str


class LocalUIAccessStore:
    """Persist only hashed loopback sessions in a private atomic store."""

    def __init__(
        self,
        data_dir: str | Path,
        *,
        clock: Callable[[], float] = time.time,
        session_ttl_seconds: int = LOCAL_UI_SESSION_TTL_SECONDS,
    ) -> None:
        self.root = Path(data_dir).expanduser() / "ui_access"
        self.path = self.root / "state.json"
        self._clock = clock
        self._session_ttl_seconds = session_ttl_seconds

    def claim(self) -> LocalUISession | None:
        """Claim the one pending OS-local first-run or recovery bootstrap."""
        with self._state_lock():
            state = self._load()
            if not state["claimable"]:
                return None
            session = self._new_session()
            state["claimable"] = False
            state["sessions"] = [self._session_record(session)]
            self._write(state)
            return session

    def authenticate(self, token: str | None) -> bool:
        """Validate an opaque cookie against active hashed server state."""
        if not token:
            return False
        digest = _digest(token)
        now = self._clock()
        with self._state_lock():
            state = self._load()
            return any(
                record["expires_at"] > now and compare_digest(record["digest"], digest)
                for record in state["sessions"]
            )

    def status(self, token: str | None = None) -> LocalUIAccessStatus:
        """Return bounded status without exposing cookies or stored digests."""
        digest = _digest(token) if token else None
        now = self._clock()
        with self._state_lock():
            state = self._load()
            expires_at = next(
                (
                    record["expires_at"]
                    for record in state["sessions"]
                    if digest is not None
                    and record["expires_at"] > now
                    and compare_digest(record["digest"], digest)
                ),
                None,
            )
            return LocalUIAccessStatus(
                authenticated=expires_at is not None,
                claimable=state["claimable"],
                expires_at=expires_at,
                recovery=(
                    "Rotate or log out this OS-local browser session."
                    if expires_at is not None
                    else "Continue the pending OS-local bootstrap."
                    if state["claimable"]
                    else "Open this loopback UI and recover local access."
                ),
            )

    def logout(self, token: str | None) -> bool:
        """Revoke only the presented local browser session."""
        if not token:
            return False
        digest = _digest(token)
        with self._state_lock():
            state = self._load()
            retained = [
                record
                for record in state["sessions"]
                if not compare_digest(record["digest"], digest)
            ]
            changed = len(retained) != len(state["sessions"])
            if changed:
                state["sessions"] = retained
                self._write(state)
            return changed

    def rotate(self, token: str | None) -> LocalUISession | None:
        """Replace an authenticated local session and revoke every old one."""
        if not token:
            return None
        with self._state_lock():
            state = self._load()
            if not _token_matches(state, token, self._clock()):
                return None
            session = self._new_session()
            state["generation"] += 1
            state["claimable"] = False
            state["sessions"] = [self._session_record(session)]
            self._write(state)
            return session

    def recover(self) -> LocalUISession:
        """Invalidate prior sessions and complete a new OS-local recovery."""
        with self._state_lock():
            state = self._load()
            session = self._new_session()
            state["generation"] += 1
            state["claimable"] = False
            state["sessions"] = [self._session_record(session)]
            self._write(state)
            return session

    def _new_session(self) -> LocalUISession:
        return LocalUISession(
            token=secrets.token_urlsafe(32),
            expires_at=self._clock() + self._session_ttl_seconds,
        )

    @staticmethod
    def _session_record(session: LocalUISession) -> dict[str, Any]:
        return {
            "digest": _digest(session.token),
            "expires_at": session.expires_at,
        }

    def _state_lock(self):
        self._ensure_root()
        return exclusive_file_lock(self.path)

    def _ensure_root(self) -> None:
        try:
            status = self.root.lstat()
        except FileNotFoundError:
            self.root.mkdir(parents=True, mode=0o700)
            status = self.root.lstat()
        if not stat.S_ISDIR(status.st_mode) or self.root.is_symlink():
            raise LocalUIAccessError("local UI access root must be a private directory")
        try:
            self.root.chmod(0o700)
        except OSError:
            pass

    def _load(self) -> dict[str, Any]:
        try:
            status = self.path.lstat()
        except FileNotFoundError:
            return {
                "schema_version": _SCHEMA_VERSION,
                "generation": 1,
                "claimable": True,
                "sessions": [],
            }
        if not stat.S_ISREG(status.st_mode) or self.path.is_symlink():
            raise LocalUIAccessError("local UI access state must be a regular file")
        descriptor = os.open(
            self.path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise LocalUIAccessError("local UI access state must be a regular file")
            if hasattr(os, "fchmod"):
                os.fchmod(descriptor, 0o600)
            raw = os.read(descriptor, 64 * 1024 + 1)
        finally:
            os.close(descriptor)
        if len(raw) > 64 * 1024:
            raise LocalUIAccessError("local UI access state is too large")
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LocalUIAccessError("local UI access state is invalid") from exc
        return _validated_state(payload)

    def _write(self, payload: Mapping[str, Any]) -> None:
        content = (
            json.dumps(payload, indent=2, sort_keys=True, separators=(",", ": ")) + "\n"
        ).encode()
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        descriptor = os.open(
            temporary,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        try:
            os.write(descriptor, content)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, self.path)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass


def _validated_state(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LocalUIAccessError("local UI access state is invalid")
    if value.get("schema_version") != _SCHEMA_VERSION:
        raise LocalUIAccessError("local UI access schema is unsupported")
    generation = value.get("generation")
    claimable = value.get("claimable")
    sessions = value.get("sessions")
    if (
        not isinstance(generation, int)
        or generation < 1
        or not isinstance(claimable, bool)
        or not isinstance(sessions, list)
        or len(sessions) > 8
    ):
        raise LocalUIAccessError("local UI access state is invalid")
    normalized_sessions: list[dict[str, Any]] = []
    for record in sessions:
        if not isinstance(record, dict):
            raise LocalUIAccessError("local UI access state is invalid")
        digest = record.get("digest")
        expires_at = record.get("expires_at")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or not isinstance(expires_at, (int, float))
        ):
            raise LocalUIAccessError("local UI access state is invalid")
        normalized_sessions.append({"digest": digest, "expires_at": float(expires_at)})
    return {
        "schema_version": _SCHEMA_VERSION,
        "generation": generation,
        "claimable": claimable,
        "sessions": normalized_sessions,
    }


def _digest(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def _token_matches(state: Mapping[str, Any], token: str, now: float) -> bool:
    digest = _digest(token)
    return any(
        record["expires_at"] > now and compare_digest(record["digest"], digest)
        for record in state["sessions"]
    )
