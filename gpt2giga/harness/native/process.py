"""Long-lived native CLI process management for harness sessions."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import os
import subprocess
import threading
from typing import Any, IO, Mapping

from gpt2giga.harness.native.base import (
    NativeCommandPlan,
    native_command_plan_to_dict,
)
from gpt2giga.harness.sessions.models import HarnessStoredEvent
from gpt2giga.harness.sessions.store import HarnessSessionStore, new_id, utc_now
from gpt2giga.harness.types import (
    REDACTED,
    SECRET_ENV_NAMES,
    SECRET_KEY_PARTS,
    redact_secrets,
)

try:  # pragma: no cover - import availability is platform-specific.
    import pty as pty_module
except ImportError:  # pragma: no cover - Windows fallback.
    pty_module = None


class NativeProcessStatus(str, Enum):
    """Lifecycle state for a managed native process."""

    RUNNING = "running"
    EXITED = "exited"
    STOPPED = "stopped"
    FAILED = "failed"


class NativeProcessNotFoundError(KeyError):
    """Raised when a native process id is not tracked."""


class NativeProcessStartError(RuntimeError):
    """Raised when a native process cannot be started."""


@dataclass(frozen=True)
class NativeProcessRef:
    """Public metadata for one native process."""

    id: str
    pid: int | None
    harness_id: str
    session_id: str
    run_id: str
    status: NativeProcessStatus
    command: tuple[str, ...]
    display_command: tuple[str, ...]
    env: Mapping[str, str]
    cwd: str | None
    native_home: str | None
    transport: str
    started_at: str
    updated_at: str
    native_ref_id: str | None = None
    stopped_at: str | None = None
    exit_code: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NativeProcessOutput:
    """One output chunk read from a native process."""

    cursor: int
    stream: str
    text: str
    created_at: str


@dataclass(frozen=True)
class NativeOutputChunk:
    """Incremental output returned to polling callers."""

    process_id: str
    cursor: int
    outputs: tuple[NativeProcessOutput, ...]
    status: NativeProcessStatus
    exit_code: int | None = None


@dataclass
class _NativeProcessRecord:
    process: subprocess.Popen
    ref: NativeProcessRef
    secret_values: tuple[str, ...]
    outputs: list[NativeProcessOutput] = field(default_factory=list)
    next_cursor: int = 1
    reader_threads: list[threading.Thread] = field(default_factory=list)
    master_fd: int | None = None
    stdin: IO[bytes] | None = None
    exit_reported: bool = False
    resources_closed: bool = False


class NativeProcessManager:
    """Start, track, read, write, and stop native CLI processes."""

    def __init__(
        self,
        *,
        session_store: HarnessSessionStore | None = None,
        use_pty: bool | None = None,
        stop_timeout_seconds: float = 2.0,
    ) -> None:
        self.session_store = session_store
        self.use_pty = _default_use_pty() if use_pty is None else use_pty
        self.stop_timeout_seconds = stop_timeout_seconds
        self._records: dict[str, _NativeProcessRecord] = {}
        self._lock = threading.RLock()

    def start(
        self,
        plan: NativeCommandPlan,
        *,
        session_id: str,
        workspace: str | None = None,
        run_id: str | None = None,
    ) -> NativeProcessRef:
        """Start one native process and begin reading output asynchronously."""
        if not plan.command:
            raise NativeProcessStartError("Native command plan is empty")
        if self.session_store is not None:
            self.session_store.get_session(session_id)
        process_id = new_id("proc")
        event_run_id = run_id or _metadata_text(plan.metadata, "run_id") or process_id
        cwd = workspace or plan.cwd
        env = dict(plan.env)
        secret_values = _secret_values(env)
        transport = "pty" if self.use_pty and pty_module is not None else "pipes"
        try:
            process, master_fd, stdin = self._popen(
                plan=plan,
                env=env,
                cwd=cwd,
                transport=transport,
            )
        except OSError as exc:
            raise NativeProcessStartError(
                f"Native process failed to start: {exc}"
            ) from exc

        now = utc_now()
        ref = NativeProcessRef(
            id=process_id,
            pid=process.pid,
            harness_id=_metadata_text(plan.metadata, "harness_id") or "native",
            session_id=session_id,
            run_id=event_run_id,
            native_ref_id=_metadata_text(plan.metadata, "native_ref_id"),
            status=NativeProcessStatus.RUNNING,
            command=_redacted_command(plan.command, secret_values),
            display_command=_redacted_command(
                plan.display_command or plan.command,
                secret_values,
            ),
            env=_redacted_env(env, secret_values),
            cwd=_redact_text(cwd, secret_values) if cwd is not None else None,
            native_home=_redact_text(plan.native_home, secret_values)
            if plan.native_home is not None
            else None,
            transport=transport,
            started_at=now,
            updated_at=now,
            metadata=_redact_value(dict(plan.metadata), secret_values),
        )
        record = _NativeProcessRecord(
            process=process,
            ref=ref,
            secret_values=secret_values,
            master_fd=master_fd,
            stdin=stdin,
        )
        with self._lock:
            self._records[process_id] = record
            self._append_session_event_locked(
                record,
                "terminal_start",
                "Started native process.",
                {
                    "process_id": process_id,
                    "pid": process.pid,
                    "transport": transport,
                    "plan": _redact_value(
                        native_command_plan_to_dict(plan),
                        secret_values,
                    ),
                },
            )
            record.reader_threads.extend(self._start_reader_threads(record))
        return ref

    def write(self, process_id: str, data: str | bytes) -> NativeProcessRef:
        """Send input to a running native process."""
        payload = data.encode("utf-8") if isinstance(data, str) else data
        with self._lock:
            record = self._record(process_id)
            self._refresh_locked(record)
            if record.ref.status is not NativeProcessStatus.RUNNING:
                raise RuntimeError(f"Native process is not running: {process_id}")
            if record.master_fd is not None:
                os.write(record.master_fd, payload)
            elif record.stdin is not None:
                record.stdin.write(payload)
                record.stdin.flush()
            else:
                raise RuntimeError(f"Native process stdin is unavailable: {process_id}")
            text = _decode(payload)
            self._append_session_event_locked(
                record,
                "terminal_input",
                "Sent input to native process.",
                {
                    "process_id": process_id,
                    "bytes": len(payload),
                    "text": _redact_text(text, record.secret_values),
                },
            )
            return record.ref

    def read_since(
        self,
        process_id: str,
        cursor: int | None = None,
    ) -> NativeOutputChunk:
        """Return process output chunks after a cursor."""
        last_seen = cursor or 0
        with self._lock:
            record = self._record(process_id)
            self._refresh_locked(record)
            outputs = tuple(item for item in record.outputs if item.cursor > last_seen)
            next_cursor = outputs[-1].cursor if outputs else last_seen
            return NativeOutputChunk(
                process_id=process_id,
                cursor=next_cursor,
                outputs=outputs,
                status=record.ref.status,
                exit_code=record.ref.exit_code,
            )

    def status(self, process_id: str) -> NativeProcessRef:
        """Return current process status."""
        with self._lock:
            record = self._record(process_id)
            self._refresh_locked(record)
            return record.ref

    def stop(self, process_id: str) -> NativeProcessRef:
        """Terminate a running native process, killing it if needed."""
        with self._lock:
            record = self._record(process_id)
            process = record.process
            running = process.poll() is None
        if running:
            process.terminate()
            try:
                process.wait(timeout=self.stop_timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=self.stop_timeout_seconds)
        with self._lock:
            self._refresh_locked(record, stopped=running)
            self._append_session_event_locked(
                record,
                "terminal_stop",
                "Stopped native process.",
                {
                    "process_id": process_id,
                    "exit_code": record.ref.exit_code,
                },
            )
            self._close_finished_resources_locked(record)
            return record.ref

    def cleanup(self) -> tuple[NativeProcessRef, ...]:
        """Refresh tracked processes and close resources for dead ones."""
        refs: list[NativeProcessRef] = []
        with self._lock:
            for record in self._records.values():
                self._refresh_locked(record)
                self._close_finished_resources_locked(record)
                refs.append(record.ref)
        return tuple(refs)

    def _popen(
        self,
        *,
        plan: NativeCommandPlan,
        env: Mapping[str, str],
        cwd: str | None,
        transport: str,
    ) -> tuple[subprocess.Popen, int | None, IO[bytes] | None]:
        if transport == "pty":
            master_fd, slave_fd = pty_module.openpty()  # type: ignore[union-attr]
            try:
                try:
                    process = subprocess.Popen(
                        plan.command,
                        cwd=cwd,
                        env=dict(env),
                        stdin=slave_fd,
                        stdout=slave_fd,
                        stderr=slave_fd,
                        close_fds=True,
                    )
                except OSError:
                    os.close(master_fd)
                    raise
            finally:
                os.close(slave_fd)
            return process, master_fd, None

        process = subprocess.Popen(
            plan.command,
            cwd=cwd,
            env=dict(env),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=os.name != "nt",
        )
        return process, None, process.stdin

    def _start_reader_threads(
        self,
        record: _NativeProcessRecord,
    ) -> list[threading.Thread]:
        if record.master_fd is not None:
            return [
                _reader_thread(
                    target=self._read_fd,
                    args=(record.ref.id, record.master_fd, "pty"),
                )
            ]
        threads: list[threading.Thread] = []
        if record.process.stdout is not None:
            threads.append(
                _reader_thread(
                    target=self._read_pipe,
                    args=(record.ref.id, record.process.stdout, "stdout"),
                )
            )
        if record.process.stderr is not None:
            threads.append(
                _reader_thread(
                    target=self._read_pipe,
                    args=(record.ref.id, record.process.stderr, "stderr"),
                )
            )
        return threads

    def _read_fd(self, process_id: str, fd: int, stream: str) -> None:
        while True:
            try:
                data = os.read(fd, 4096)
            except OSError:
                return
            if not data:
                return
            self._append_output(process_id, stream, data)

    def _read_pipe(self, process_id: str, pipe: IO[bytes], stream: str) -> None:
        fd = pipe.fileno()
        while True:
            try:
                data = os.read(fd, 4096)
            except OSError:
                return
            if not data:
                return
            self._append_output(process_id, stream, data)

    def _append_output(self, process_id: str, stream: str, data: bytes) -> None:
        text = _decode(data)
        with self._lock:
            record = self._records.get(process_id)
            if record is None:
                return
            redacted_text = _redact_text(text, record.secret_values)
            output = NativeProcessOutput(
                cursor=record.next_cursor,
                stream=stream,
                text=redacted_text,
                created_at=utc_now(),
            )
            record.next_cursor += 1
            record.outputs.append(output)
            self._append_session_event_locked(
                record,
                "terminal_output",
                "Read native process output.",
                {
                    "process_id": process_id,
                    "cursor": output.cursor,
                    "stream": stream,
                    "text": redacted_text,
                },
            )

    def _record(self, process_id: str) -> _NativeProcessRecord:
        try:
            return self._records[process_id]
        except KeyError as exc:
            raise NativeProcessNotFoundError(process_id) from exc

    def _refresh_locked(
        self,
        record: _NativeProcessRecord,
        *,
        stopped: bool = False,
    ) -> None:
        exit_code = record.process.poll()
        if exit_code is None:
            return
        if stopped:
            status = NativeProcessStatus.STOPPED
        elif record.ref.status is NativeProcessStatus.STOPPED:
            status = NativeProcessStatus.STOPPED
        elif record.ref.status is NativeProcessStatus.FAILED:
            status = NativeProcessStatus.FAILED
        else:
            status = NativeProcessStatus.EXITED
        record.ref = replace(
            record.ref,
            status=status,
            exit_code=exit_code,
            stopped_at=utc_now() if status is NativeProcessStatus.STOPPED else None,
            updated_at=utc_now(),
        )
        if not record.exit_reported:
            record.exit_reported = True
            self._append_session_event_locked(
                record,
                "terminal_exit",
                "Native process exited.",
                {
                    "process_id": record.ref.id,
                    "exit_code": exit_code,
                    "status": status.value,
                },
            )

    def _close_finished_resources_locked(self, record: _NativeProcessRecord) -> None:
        if record.ref.status is NativeProcessStatus.RUNNING or record.resources_closed:
            return
        if any(thread.is_alive() for thread in record.reader_threads):
            return
        if record.stdin is not None:
            try:
                record.stdin.close()
            except OSError:
                pass
        if record.master_fd is not None:
            try:
                os.close(record.master_fd)
            except OSError:
                pass
        record.resources_closed = True

    def _append_session_event_locked(
        self,
        record: _NativeProcessRecord,
        event_type: str,
        message: str,
        payload: Mapping[str, Any],
    ) -> None:
        if self.session_store is None:
            return
        try:
            self.session_store.append_event(
                HarnessStoredEvent(
                    id=new_id("evt"),
                    session_id=record.ref.session_id,
                    run_id=record.ref.run_id,
                    type=event_type,
                    message=message,
                    payload=_redact_value(dict(payload), record.secret_values),
                    created_at=utc_now(),
                )
            )
        except Exception:
            return


def native_process_ref_to_dict(ref: NativeProcessRef) -> dict[str, Any]:
    """Serialize a native process ref for API responses."""
    return {
        "id": ref.id,
        "pid": ref.pid,
        "harness_id": ref.harness_id,
        "session_id": ref.session_id,
        "run_id": ref.run_id,
        "native_ref_id": ref.native_ref_id,
        "status": ref.status.value,
        "command": list(redact_secrets(ref.command)),
        "display_command": list(redact_secrets(ref.display_command)),
        "env": redact_secrets(dict(ref.env)),
        "cwd": redact_secrets(ref.cwd),
        "native_home": redact_secrets(ref.native_home),
        "transport": ref.transport,
        "started_at": ref.started_at,
        "updated_at": ref.updated_at,
        "stopped_at": ref.stopped_at,
        "exit_code": ref.exit_code,
        "metadata": redact_secrets(dict(ref.metadata)),
    }


def native_output_to_dict(output: NativeProcessOutput) -> dict[str, Any]:
    """Serialize one native process output chunk."""
    return {
        "cursor": output.cursor,
        "stream": output.stream,
        "text": redact_secrets(output.text),
        "created_at": output.created_at,
    }


def native_output_chunk_to_dict(chunk: NativeOutputChunk) -> dict[str, Any]:
    """Serialize an incremental native process output response."""
    return {
        "process_id": chunk.process_id,
        "cursor": chunk.cursor,
        "status": chunk.status.value,
        "exit_code": chunk.exit_code,
        "outputs": [native_output_to_dict(output) for output in chunk.outputs],
    }


def _reader_thread(target: Any, args: tuple[Any, ...]) -> threading.Thread:
    thread = threading.Thread(target=target, args=args, daemon=True)
    thread.start()
    return thread


def _default_use_pty() -> bool:
    return os.name == "posix" and pty_module is not None


def _metadata_text(metadata: Mapping[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if value is None or not str(value).strip():
        return None
    return str(value).strip()


def _secret_values(env: Mapping[str, str]) -> tuple[str, ...]:
    values: list[str] = []
    for key, value in env.items():
        key_text = str(key).lower()
        if (
            (
                str(key) in SECRET_ENV_NAMES
                or any(part in key_text for part in SECRET_KEY_PARTS)
            )
            and value
            and value != "0"
        ):
            values.append(str(value))
    values.sort(key=len, reverse=True)
    return tuple(values)


def _redacted_env(
    env: Mapping[str, str],
    secret_values: tuple[str, ...],
) -> Mapping[str, str]:
    redacted = _redact_value(dict(env), secret_values)
    if isinstance(redacted, Mapping):
        return {str(key): str(value) for key, value in redacted.items()}
    return {}


def _redacted_command(
    command: tuple[str, ...],
    secret_values: tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(_redact_text(str(item), secret_values) for item in command)


def _redact_value(value: Any, secret_values: tuple[str, ...]) -> Any:
    if isinstance(value, Mapping):
        return redact_secrets(
            {
                str(key): _redact_value(item, secret_values)
                for key, item in value.items()
            }
        )
    if isinstance(value, tuple):
        return tuple(_redact_value(item, secret_values) for item in value)
    if isinstance(value, list):
        return [_redact_value(item, secret_values) for item in value]
    if isinstance(value, str):
        return _redact_text(value, secret_values)
    return redact_secrets(value)


def _redact_text(value: str | None, secret_values: tuple[str, ...]) -> str:
    if value is None:
        return ""
    redacted = value
    for secret in secret_values:
        redacted = redacted.replace(secret, REDACTED)
    result = redact_secrets(redacted)
    return str(result)


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")
