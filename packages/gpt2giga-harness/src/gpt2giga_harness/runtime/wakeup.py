"""Best-effort loopback wakeups for standalone durable workers."""

from __future__ import annotations

from contextlib import suppress
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import time
from typing import Final
from uuid import uuid4


WAKE_DIRECTORY_NAME: Final[str] = "worker-wakeups"
WAKE_ENDPOINT_SCHEMA_VERSION: Final[int] = 1
MAX_WAKE_ENDPOINTS: Final[int] = 64
MAX_WAKE_ENDPOINT_CANDIDATES: Final[int] = 256
MAX_WAKE_ENDPOINT_BYTES: Final[int] = 4096
MAX_WAKE_PACKET_BYTES: Final[int] = 128


class WorkerWakeReceiver:
    """Receive content-free wake signals through a private loopback endpoint."""

    def __init__(self, data_dir: str | Path, worker_id: str) -> None:
        self.data_dir = Path(data_dir).expanduser()
        self.worker_id = worker_id
        self.token = secrets.token_hex(16)
        self._socket: socket.socket | None = None
        self._endpoint_path: Path | None = None
        try:
            receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            receiver.bind(("127.0.0.1", 0))
            receiver.setblocking(False)
            self._socket = receiver
            self._publish_endpoint(int(receiver.getsockname()[1]))
        except OSError:
            if self._socket is not None:
                self._socket.close()
            self._socket = None

    @property
    def available(self) -> bool:
        """Return whether loopback wake delivery is available."""
        return self._socket is not None and self._endpoint_path is not None

    def wait(self, timeout_seconds: float) -> bool:
        """Wait for one valid wake signal or the bounded fallback timeout."""
        timeout = max(float(timeout_seconds), 0.0)
        if self._socket is None:
            time.sleep(timeout)
            return False
        deadline = time.monotonic() + timeout
        while True:
            remaining = max(deadline - time.monotonic(), 0.0)
            self._socket.settimeout(remaining)
            try:
                payload, _ = self._socket.recvfrom(MAX_WAKE_PACKET_BYTES)
            except (TimeoutError, socket.timeout):
                return False
            except OSError:
                time.sleep(remaining)
                return False
            if secrets.compare_digest(payload, self.token.encode("ascii")):
                return True
            if remaining <= 0:
                return False

    def close(self) -> None:
        """Remove only this receiver's exact endpoint and close its socket."""
        endpoint = self._endpoint_path
        self._endpoint_path = None
        if endpoint is not None:
            try:
                payload = _read_endpoint(endpoint)
            except (OSError, ValueError):
                payload = None
            if payload is not None and payload.get("token") == self.token:
                with suppress(FileNotFoundError):
                    endpoint.unlink()
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def _publish_endpoint(self, port: int) -> None:
        directory = self.data_dir / WAKE_DIRECTORY_NAME
        directory.mkdir(parents=True, exist_ok=True)
        if directory.is_symlink():
            raise OSError("worker wake directory must not be a symlink")
        with suppress(OSError):
            directory.chmod(0o700)
        identity = hashlib.sha256(self.worker_id.encode("utf-8")).hexdigest()
        endpoint = directory / f"{identity}.json"
        temporary = directory / f".{identity}.{uuid4().hex}.tmp"
        document = json.dumps(
            {
                "schema_version": WAKE_ENDPOINT_SCHEMA_VERSION,
                "worker_id_sha256": identity,
                "process_id": os.getpid(),
                "port": port,
                "token": self.token,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        descriptor = os.open(
            temporary,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        try:
            os.write(descriptor, document)
        finally:
            os.close(descriptor)
        os.replace(temporary, endpoint)
        self._endpoint_path = endpoint


def signal_workers(data_dir: str | Path) -> int:
    """Best-effort broadcast one content-free wake to local worker endpoints."""
    directory = Path(data_dir).expanduser() / WAKE_DIRECTORY_NAME
    if not directory.is_dir() or directory.is_symlink():
        return 0
    delivered = 0
    try:
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except OSError:
        return 0
    try:
        candidates = sorted(
            directory.glob("*.json"),
            key=_modified_time,
            reverse=True,
        )[:MAX_WAKE_ENDPOINT_CANDIDATES]
        for endpoint in candidates:
            if delivered >= MAX_WAKE_ENDPOINTS:
                break
            try:
                payload = _read_endpoint(endpoint)
                process_id = int(payload["process_id"])
                port = int(payload["port"])
                token = str(payload["token"])
            except (KeyError, OSError, TypeError, ValueError):
                continue
            if not _process_is_running(process_id):
                with suppress(OSError):
                    endpoint.unlink()
                continue
            if not 1 <= port <= 65535 or not _valid_token(token):
                continue
            try:
                sender.sendto(token.encode("ascii"), ("127.0.0.1", port))
            except OSError:
                continue
            delivered += 1
    finally:
        sender.close()
    return delivered


def _read_endpoint(path: Path) -> dict[str, object]:
    if path.is_symlink():
        raise ValueError("worker wake endpoint must not be a symlink")
    if path.stat().st_size > MAX_WAKE_ENDPOINT_BYTES:
        raise ValueError("worker wake endpoint is too large")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("worker wake endpoint must be an object")
    if payload.get("schema_version") != WAKE_ENDPOINT_SCHEMA_VERSION:
        raise ValueError("unsupported worker wake endpoint schema")
    return payload


def _valid_token(value: str) -> bool:
    return len(value) == 32 and all(
        character in "0123456789abcdef" for character in value
    )


def _modified_time(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _process_is_running(process_id: int) -> bool:
    if process_id <= 0:
        return False
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True
