"""Long-lived native CLI process management for harness sessions."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
import os
from pathlib import Path
import struct
import subprocess
import threading
import time
from typing import Any, IO, Mapping
from uuid import uuid4

from gpt2giga_harness.native.base import (
    NativeCommandPlan,
    NativePromptDeliveryStatus,
    native_command_plan_to_dict,
    native_prompt_delivery_to_dict,
)
from gpt2giga_harness.sessions.models import HarnessStoredEvent
from gpt2giga_harness.sessions.store import HarnessSessionStore, new_id, utc_now
from gpt2giga_harness.runtime.models import (
    NativeProcessOutputRecord,
    NativeProcessRecord,
)
from gpt2giga_harness.runtime.store import (
    NativeProcessRecordNotFoundError,
    RuntimeCoordinationStore,
)
from gpt2giga_harness.types import (
    REDACTED,
    SECRET_ENV_NAMES,
    SECRET_KEY_PARTS,
    redact_secrets,
)

try:  # pragma: no cover - import availability is platform-specific.
    import pty as pty_module
except ImportError:  # pragma: no cover - Windows fallback.
    pty_module = None

try:  # pragma: no cover - import availability is platform-specific.
    import fcntl
    import termios
except ImportError:  # pragma: no cover - Windows fallback.
    fcntl = None
    termios = None


MIN_TERMINAL_ROWS = 2
MAX_TERMINAL_ROWS = 200
MIN_TERMINAL_COLUMNS = 20
MAX_TERMINAL_COLUMNS = 500


class NativeProcessStatus(str, Enum):
    """Lifecycle state for a managed native process."""

    RUNNING = "running"
    EXITED = "exited"
    STOPPED = "stopped"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    INTERRUPTED = "interrupted"
    UNKNOWN = "unknown"


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
    owner_id: str | None = None
    owner_process_id: int | None = None
    process_group_id: int | None = None
    heartbeat_at: str | None = None
    leased_until: str | None = None
    timeout_at: str | None = None
    cancel_requested_at: str | None = None
    terminal_cursor: int = 0
    recovery_outcome: str | None = None
    reconnectable: bool = True


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
    oldest_cursor: int | None = None
    truncated: bool = False


@dataclass
class _OwnedNativeProcess:
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
    supervisor_thread: threading.Thread | None = None


class NativeProcessManager:
    """Start, track, read, write, and stop native CLI processes."""

    def __init__(
        self,
        *,
        session_store: HarnessSessionStore | None = None,
        runtime_store: RuntimeCoordinationStore | None = None,
        use_pty: bool | None = None,
        stop_timeout_seconds: float = 2.0,
        owner_id: str | None = None,
        lease_seconds: float = 5.0,
        heartbeat_seconds: float = 1.0,
        max_output_chunks: int = 512,
    ) -> None:
        self.session_store = session_store
        self.runtime_store = runtime_store
        self.use_pty = _default_use_pty() if use_pty is None else use_pty
        self.stop_timeout_seconds = stop_timeout_seconds
        self.owner_id = owner_id or f"native_owner_{uuid4().hex}"
        self.owner_process_id = os.getpid()
        self.lease_seconds = max(float(lease_seconds), 0.1)
        self.heartbeat_seconds = max(
            min(float(heartbeat_seconds), self.lease_seconds / 2), 0.05
        )
        self.max_output_chunks = max(int(max_output_chunks), 1)
        self._records: dict[str, _OwnedNativeProcess] = {}
        self._lock = threading.RLock()
        self._shutdown = threading.Event()
        self._reconcile_expired_records()

    def start(
        self,
        plan: NativeCommandPlan,
        *,
        session_id: str,
        workspace: str | None = None,
        run_id: str | None = None,
        timeout_seconds: float | None = None,
    ) -> NativeProcessRef:
        """Start one native process and begin reading output asynchronously."""
        if not plan.command:
            raise NativeProcessStartError("Native command plan is empty")
        if self.session_store is not None:
            self.session_store.get_session(session_id)
        validated_timeout = (
            _positive_timeout(timeout_seconds) if timeout_seconds is not None else None
        )
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
        leased_until = _future_utc(self.lease_seconds)
        timeout_at = (
            _future_utc(validated_timeout) if validated_timeout is not None else None
        )
        process_group_id = _process_group_id(process.pid)
        public_command = (
            plan.display_command
            if plan.prompt_delivery is not None and plan.display_command
            else plan.command
        )
        metadata = dict(plan.metadata)
        if plan.prompt_delivery is not None:
            metadata["prompt_delivery"] = native_prompt_delivery_to_dict(
                plan.prompt_delivery,
                status=NativePromptDeliveryStatus.DELIVERED,
            )
        ref = NativeProcessRef(
            id=process_id,
            pid=process.pid,
            harness_id=_metadata_text(plan.metadata, "harness_id") or "native",
            session_id=session_id,
            run_id=event_run_id,
            native_ref_id=_metadata_text(plan.metadata, "native_ref_id"),
            status=NativeProcessStatus.RUNNING,
            command=_redacted_command(public_command, secret_values),
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
            metadata=_redact_value(metadata, secret_values),
            owner_id=self.owner_id,
            owner_process_id=self.owner_process_id,
            process_group_id=process_group_id,
            heartbeat_at=now,
            leased_until=leased_until,
            timeout_at=timeout_at,
        )
        record = _OwnedNativeProcess(
            process=process,
            ref=ref,
            secret_values=secret_values,
            master_fd=master_fd,
            stdin=stdin,
        )
        if self.runtime_store is not None:
            try:
                self.runtime_store.create_native_process(_durable_record_from_ref(ref))
            except Exception as exc:
                process.terminate()
                try:
                    process.wait(timeout=self.stop_timeout_seconds)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=self.stop_timeout_seconds)
                raise NativeProcessStartError(
                    "Native process ownership could not be persisted"
                ) from exc
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
                    "prompt_delivery": metadata.get("prompt_delivery"),
                },
            )
            record.reader_threads.extend(self._start_reader_threads(record))
            record.supervisor_thread = _reader_thread(
                target=self._supervise,
                args=(record.ref.id,),
                name=f"gpt2giga-native-{record.ref.id}-owner",
            )
        return ref

    def write(self, process_id: str, data: str | bytes) -> NativeProcessRef:
        """Send input to a running native process."""
        payload = data.encode("utf-8") if isinstance(data, str) else data
        with self._lock:
            record = self._owned_record(process_id)
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

    def resize(self, process_id: str, *, rows: int, columns: int) -> NativeProcessRef:
        """Resize the owned PTY after validating bounded terminal dimensions."""
        validated_rows = _terminal_dimension(
            rows,
            name="rows",
            minimum=MIN_TERMINAL_ROWS,
            maximum=MAX_TERMINAL_ROWS,
        )
        validated_columns = _terminal_dimension(
            columns,
            name="columns",
            minimum=MIN_TERMINAL_COLUMNS,
            maximum=MAX_TERMINAL_COLUMNS,
        )
        with self._lock:
            record = self._owned_record(process_id)
            self._refresh_locked(record)
            if record.ref.status is not NativeProcessStatus.RUNNING:
                raise RuntimeError(f"Native process is not running: {process_id}")
            if record.master_fd is None or fcntl is None or termios is None:
                raise RuntimeError(
                    "Native terminal resize is unavailable for this process transport."
                )
            try:
                fcntl.ioctl(
                    record.master_fd,
                    termios.TIOCSWINSZ,
                    struct.pack("HHHH", validated_rows, validated_columns, 0, 0),
                )
            except OSError as exc:
                raise RuntimeError("Native terminal resize failed.") from exc
            self._append_session_event_locked(
                record,
                "terminal_resize",
                "Resized native process terminal.",
                {
                    "process_id": process_id,
                    "rows": validated_rows,
                    "columns": validated_columns,
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
            record = self._records.get(process_id)
            if record is not None:
                self._refresh_locked(record)
                outputs = tuple(
                    item for item in record.outputs if item.cursor > last_seen
                )
                oldest_cursor = record.outputs[0].cursor if record.outputs else None
                next_cursor = outputs[-1].cursor if outputs else last_seen
                return NativeOutputChunk(
                    process_id=process_id,
                    cursor=next_cursor,
                    outputs=outputs,
                    status=record.ref.status,
                    exit_code=record.ref.exit_code,
                    oldest_cursor=oldest_cursor,
                    truncated=(
                        oldest_cursor is not None and last_seen < oldest_cursor - 1
                    ),
                )
        return self._read_durable_outputs(process_id, last_seen)

    def status(self, process_id: str) -> NativeProcessRef:
        """Return current process status."""
        with self._lock:
            record = self._records.get(process_id)
            if record is not None:
                self._refresh_locked(record)
                return record.ref
        self._reconcile_expired_records()
        return self._durable_ref(process_id)

    def stop(self, process_id: str) -> NativeProcessRef:
        """Terminate a running native process, killing it if needed."""
        with self._lock:
            record = self._records.get(process_id)
            if record is None:
                if self.runtime_store is not None:
                    with suppress(NativeProcessRecordNotFoundError):
                        self.runtime_store.request_native_process_cancel(process_id)
                return self._wait_for_foreign_cancel(process_id)
            cancel_requested_at = utc_now()
            if self.runtime_store is not None:
                with suppress(NativeProcessRecordNotFoundError):
                    durable = self.runtime_store.request_native_process_cancel(
                        process_id
                    )
                    cancel_requested_at = (
                        durable.cancel_requested_at or cancel_requested_at
                    )
            record.ref = replace(
                record.ref,
                status=NativeProcessStatus.STOPPED,
                cancel_requested_at=cancel_requested_at,
            )
            process = record.process
            running = process.poll() is None
        if running:
            self._terminate_process(process)
        with self._lock:
            self._refresh_locked(
                record,
                terminal_status=(NativeProcessStatus.STOPPED if running else None),
                recovery_outcome="cancel_requested" if running else None,
            )
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

    def close(self, *, terminate_owned: bool = True) -> None:
        """Stop supervision and optionally terminate every locally owned process."""
        self._shutdown.set()
        if terminate_owned:
            for process_id in tuple(self._records):
                try:
                    self.stop(process_id)
                except (NativeProcessNotFoundError, RuntimeError):
                    continue

    def cleanup(self) -> tuple[NativeProcessRef, ...]:
        """Refresh tracked processes and close resources for dead ones."""
        refs: list[NativeProcessRef] = []
        with self._lock:
            for record in self._records.values():
                self._refresh_locked(record)
                self._close_finished_resources_locked(record)
                refs.append(record.ref)
        return tuple(refs)

    def is_home_active(self, home: str | Path) -> bool:
        """Return whether a running native process owns the managed home."""
        target = Path(home).expanduser().resolve()
        with self._lock:
            for record in self._records.values():
                self._refresh_locked(record)
                native_home = record.ref.native_home
                if (
                    record.ref.status is NativeProcessStatus.RUNNING
                    and native_home
                    and Path(native_home).expanduser().resolve() == target
                ):
                    return True
        if self.runtime_store is not None:
            for durable in self.runtime_store.list_native_processes():
                native_home = _optional_mapping_text(durable.ref, "native_home")
                if (
                    durable.status == NativeProcessStatus.RUNNING.value
                    and native_home
                    and Path(native_home).expanduser().resolve() == target
                ):
                    return True
        return False

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
                        start_new_session=os.name == "posix",
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
            start_new_session=os.name == "posix",
        )
        return process, None, process.stdin

    def _start_reader_threads(
        self,
        record: _OwnedNativeProcess,
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
        try:
            while True:
                try:
                    data = os.read(fd, 4096)
                except OSError:
                    return
                if not data:
                    return
                self._append_output(process_id, stream, data)
        finally:
            with self._lock:
                record = self._records.get(process_id)
                if record is not None and record.master_fd == fd:
                    record.master_fd = None
            with suppress(OSError):
                os.close(fd)

    def _read_pipe(self, process_id: str, pipe: IO[bytes], stream: str) -> None:
        try:
            fd = pipe.fileno()
            while True:
                try:
                    data = os.read(fd, 4096)
                except OSError:
                    return
                if not data:
                    return
                self._append_output(process_id, stream, data)
        finally:
            with suppress(OSError, ValueError):
                pipe.close()

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
            if len(record.outputs) > self.max_output_chunks:
                del record.outputs[: len(record.outputs) - self.max_output_chunks]
            record.ref = replace(record.ref, terminal_cursor=output.cursor)
            if self.runtime_store is not None:
                self.runtime_store.append_native_process_output(
                    NativeProcessOutputRecord(
                        process_id=process_id,
                        cursor=output.cursor,
                        stream=stream,
                        text=redacted_text,
                        created_at=output.created_at,
                    ),
                    owner_id=self.owner_id,
                    max_chunks=self.max_output_chunks,
                )
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

    def _owned_record(self, process_id: str) -> _OwnedNativeProcess:
        record = self._records.get(process_id)
        if record is not None:
            return record
        if self.runtime_store is not None:
            try:
                self.runtime_store.get_native_process(process_id)
            except NativeProcessRecordNotFoundError as exc:
                raise NativeProcessNotFoundError(process_id) from exc
            raise RuntimeError(
                "Native process input is unavailable because this API instance "
                "does not own the supervised process."
            )
        raise NativeProcessNotFoundError(process_id)

    def _refresh_locked(
        self,
        record: _OwnedNativeProcess,
        *,
        terminal_status: NativeProcessStatus | None = None,
        recovery_outcome: str | None = None,
    ) -> None:
        exit_code = record.process.poll()
        if exit_code is None:
            return
        if (
            terminal_status is None
            and record.ref.status is NativeProcessStatus.RUNNING
            and any(thread.is_alive() for thread in record.reader_threads)
        ):
            # A process can exit before its reader threads have appended the
            # final stdout/stderr chunks. Keep the public lifecycle running
            # until those readers drain so terminal status never races ahead
            # of terminal output.
            return
        if terminal_status is not None:
            status = terminal_status
        elif record.ref.status in {
            NativeProcessStatus.STOPPED,
            NativeProcessStatus.FAILED,
            NativeProcessStatus.TIMED_OUT,
        }:
            status = record.ref.status
        else:
            status = NativeProcessStatus.EXITED
        now = utc_now()
        record.ref = replace(
            record.ref,
            status=status,
            exit_code=exit_code,
            stopped_at=(
                now
                if status
                in {NativeProcessStatus.STOPPED, NativeProcessStatus.TIMED_OUT}
                else record.ref.stopped_at
            ),
            updated_at=now,
            heartbeat_at=now,
            recovery_outcome=recovery_outcome or record.ref.recovery_outcome,
        )
        if not record.exit_reported:
            record.exit_reported = True
            self._persist_terminal_locked(record)
            self._append_session_event_locked(
                record,
                "terminal_exit",
                "Native process exited.",
                {
                    "process_id": record.ref.id,
                    "exit_code": exit_code,
                    "status": status.value,
                    "recovery_outcome": record.ref.recovery_outcome,
                },
            )
        self._close_finished_resources_locked(record)

    def _close_finished_resources_locked(self, record: _OwnedNativeProcess) -> None:
        if record.ref.status is NativeProcessStatus.RUNNING or record.resources_closed:
            return
        if record.stdin is not None:
            try:
                record.stdin.close()
            except (OSError, ValueError):
                # The native process may already have closed its stdin pipe.
                pass
        if any(thread.is_alive() for thread in record.reader_threads):
            return
        for pipe in (record.process.stdout, record.process.stderr):
            if pipe is None:
                continue
            try:
                pipe.close()
            except (OSError, ValueError):
                # Reader teardown may have already closed the output pipe.
                pass
        if record.master_fd is not None:
            try:
                os.close(record.master_fd)
            except OSError:
                # PTY teardown may race with process exit or another cleanup path.
                pass
        record.resources_closed = True

    def _append_session_event_locked(
        self,
        record: _OwnedNativeProcess,
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

    def _supervise(self, process_id: str) -> None:
        while not self._shutdown.wait(self.heartbeat_seconds):
            with self._lock:
                record = self._records.get(process_id)
                if record is None:
                    return
                self._refresh_locked(record)
                if record.ref.status is not NativeProcessStatus.RUNNING:
                    return
                ref = record.ref
            durable = None
            if self.runtime_store is not None:
                durable = self.runtime_store.heartbeat_native_process(
                    process_id,
                    owner_id=self.owner_id,
                    lease_seconds=self.lease_seconds,
                    ref=native_process_ref_to_dict(ref),
                    terminal_cursor=ref.terminal_cursor,
                )
                with self._lock:
                    current = self._records.get(process_id)
                    if current is not None:
                        current.ref = replace(
                            current.ref,
                            heartbeat_at=durable.heartbeat_at,
                            leased_until=durable.leased_until,
                            cancel_requested_at=durable.cancel_requested_at,
                        )
            if durable is not None and durable.owner_id != self.owner_id:
                return
            if (
                durable is not None
                and durable.status != NativeProcessStatus.RUNNING.value
            ):
                self._terminate_process(record.process)
                with self._lock:
                    current = self._records.get(process_id)
                    if current is not None:
                        current.ref = _ref_from_durable(
                            durable,
                            reconnectable=False,
                        )
                        current.exit_reported = True
                        self._close_finished_resources_locked(current)
                return
            if durable is not None and durable.cancel_requested_at is not None:
                self._terminate_owned(
                    process_id,
                    status=NativeProcessStatus.STOPPED,
                    recovery_outcome="cancel_requested",
                )
                return
            timeout_at = ref.timeout_at
            if timeout_at is not None and _timestamp_expired(timeout_at):
                self._terminate_owned(
                    process_id,
                    status=NativeProcessStatus.TIMED_OUT,
                    recovery_outcome="timeout_expired",
                )
                return

    def _terminate_owned(
        self,
        process_id: str,
        *,
        status: NativeProcessStatus,
        recovery_outcome: str,
    ) -> NativeProcessRef:
        with self._lock:
            record = self._records.get(process_id)
            if record is None:
                raise NativeProcessNotFoundError(process_id)
            process = record.process
            running = process.poll() is None
        if running:
            self._terminate_process(process)
        with self._lock:
            self._refresh_locked(
                record,
                terminal_status=status,
                recovery_outcome=recovery_outcome,
            )
            self._close_finished_resources_locked(record)
            return record.ref

    def _terminate_process(self, process: subprocess.Popen) -> None:
        process.terminate()
        try:
            process.wait(timeout=self.stop_timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=self.stop_timeout_seconds)

    def _persist_terminal_locked(self, record: _OwnedNativeProcess) -> None:
        if self.runtime_store is None:
            return
        self.runtime_store.finish_native_process(
            record.ref.id,
            owner_id=self.owner_id,
            status=record.ref.status.value,
            ref=native_process_ref_to_dict(record.ref),
            terminal_cursor=record.ref.terminal_cursor,
            recovery_outcome=record.ref.recovery_outcome,
        )

    def _read_durable_outputs(
        self, process_id: str, last_seen: int
    ) -> NativeOutputChunk:
        if self.runtime_store is None:
            raise NativeProcessNotFoundError(process_id)
        try:
            durable = self.runtime_store.get_native_process(process_id)
            stored = self.runtime_store.read_native_process_outputs(
                process_id, after_cursor=last_seen
            )
        except NativeProcessRecordNotFoundError as exc:
            raise NativeProcessNotFoundError(process_id) from exc
        outputs = tuple(
            NativeProcessOutput(
                cursor=item.cursor,
                stream=item.stream,
                text=item.text,
                created_at=item.created_at,
            )
            for item in stored
        )
        oldest_cursor = outputs[0].cursor if outputs else None
        return NativeOutputChunk(
            process_id=process_id,
            cursor=outputs[-1].cursor if outputs else last_seen,
            outputs=outputs,
            status=NativeProcessStatus(durable.status),
            exit_code=_optional_int(durable.ref.get("exit_code")),
            oldest_cursor=oldest_cursor,
            truncated=(oldest_cursor is not None and last_seen < oldest_cursor - 1),
        )

    def _durable_ref(self, process_id: str) -> NativeProcessRef:
        if self.runtime_store is None:
            raise NativeProcessNotFoundError(process_id)
        try:
            durable = self.runtime_store.get_native_process(process_id)
        except NativeProcessRecordNotFoundError as exc:
            raise NativeProcessNotFoundError(process_id) from exc
        return _ref_from_durable(durable, reconnectable=False)

    def _wait_for_foreign_cancel(self, process_id: str) -> NativeProcessRef:
        if self.runtime_store is None:
            raise NativeProcessNotFoundError(process_id)
        deadline = time.monotonic() + self.stop_timeout_seconds
        ref = self._durable_ref(process_id)
        while ref.status is NativeProcessStatus.RUNNING and time.monotonic() < deadline:
            time.sleep(min(self.heartbeat_seconds, 0.05))
            ref = self.status(process_id)
        return ref

    def _reconcile_expired_records(self) -> tuple[NativeProcessRef, ...]:
        if self.runtime_store is None:
            return ()
        recovered: list[NativeProcessRef] = []
        for durable in self.runtime_store.list_expired_native_processes():
            if durable.id in self._records:
                continue
            process_state = _process_state(durable.process_id)
            if process_state == "alive":
                status = NativeProcessStatus.INTERRUPTED
                outcome = "owner_lease_expired_process_alive_not_adopted"
            elif process_state == "exited":
                status = NativeProcessStatus.EXITED
                outcome = "owner_lease_expired_process_not_running"
            else:
                status = NativeProcessStatus.UNKNOWN
                outcome = "owner_lease_expired_process_state_unknown"
            ref = replace(
                _ref_from_durable(durable, reconnectable=False),
                status=status,
                updated_at=utc_now(),
                recovery_outcome=outcome,
                reconnectable=False,
            )
            updated = self.runtime_store.recover_native_process(
                durable.id,
                status=status.value,
                ref=native_process_ref_to_dict(ref),
                recovery_outcome=outcome,
            )
            if updated.status == NativeProcessStatus.RUNNING.value:
                continue
            recovered_ref = _ref_from_durable(updated, reconnectable=False)
            recovered.append(recovered_ref)
            self._append_recovery_event(recovered_ref)
        return tuple(recovered)

    def _append_recovery_event(self, ref: NativeProcessRef) -> None:
        if self.session_store is None:
            return
        try:
            self.session_store.append_event(
                HarnessStoredEvent(
                    id=new_id("evt"),
                    session_id=ref.session_id,
                    run_id=ref.run_id,
                    type="terminal_recovery",
                    message="Native process owner lease expired; PTY adoption was not attempted.",
                    payload={
                        "process_id": ref.id,
                        "status": ref.status.value,
                        "recovery_outcome": ref.recovery_outcome,
                        "reconnectable": False,
                    },
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
        "owner_id": ref.owner_id,
        "owner_process_id": ref.owner_process_id,
        "process_group_id": ref.process_group_id,
        "heartbeat_at": ref.heartbeat_at,
        "leased_until": ref.leased_until,
        "timeout_at": ref.timeout_at,
        "cancel_requested_at": ref.cancel_requested_at,
        "terminal_cursor": ref.terminal_cursor,
        "recovery_outcome": ref.recovery_outcome,
        "reconnectable": ref.reconnectable,
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
        "oldest_cursor": chunk.oldest_cursor,
        "truncated": chunk.truncated,
        "outputs": [native_output_to_dict(output) for output in chunk.outputs],
    }


def _reader_thread(
    target: Any,
    args: tuple[Any, ...],
    *,
    name: str | None = None,
) -> threading.Thread:
    thread = threading.Thread(target=target, args=args, daemon=True, name=name)
    thread.start()
    return thread


def _default_use_pty() -> bool:
    return os.name == "posix" and pty_module is not None


def _metadata_text(metadata: Mapping[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if value is None or not str(value).strip():
        return None
    return str(value).strip()


def _durable_record_from_ref(ref: NativeProcessRef) -> NativeProcessRecord:
    if ref.owner_id is None or ref.owner_process_id is None:
        raise ValueError("native process owner identity is required")
    if ref.heartbeat_at is None or ref.leased_until is None:
        raise ValueError("native process lease identity is required")
    return NativeProcessRecord(
        id=ref.id,
        owner_id=ref.owner_id,
        owner_process_id=ref.owner_process_id,
        session_id=ref.session_id,
        run_id=ref.run_id,
        harness_id=ref.harness_id,
        status=ref.status.value,
        process_id=ref.pid,
        process_group_id=ref.process_group_id,
        transport=ref.transport,
        ref=native_process_ref_to_dict(ref),
        started_at=ref.started_at,
        updated_at=ref.updated_at,
        heartbeat_at=ref.heartbeat_at,
        leased_until=ref.leased_until,
        timeout_at=ref.timeout_at,
        cancel_requested_at=ref.cancel_requested_at,
        terminal_cursor=ref.terminal_cursor,
        recovery_outcome=ref.recovery_outcome,
    )


def _ref_from_durable(
    record: NativeProcessRecord,
    *,
    reconnectable: bool,
) -> NativeProcessRef:
    payload = record.ref
    raw_env = payload.get("env")
    metadata = payload.get("metadata")
    return NativeProcessRef(
        id=str(payload.get("id") or record.id),
        pid=_optional_int(payload.get("pid")) or record.process_id,
        harness_id=str(payload.get("harness_id") or record.harness_id),
        session_id=str(payload.get("session_id") or record.session_id),
        run_id=str(payload.get("run_id") or record.run_id),
        native_ref_id=_optional_text(payload.get("native_ref_id")),
        status=NativeProcessStatus(record.status),
        command=_text_tuple(payload.get("command")),
        display_command=_text_tuple(payload.get("display_command")),
        env=(
            {str(key): str(value) for key, value in raw_env.items()}
            if isinstance(raw_env, Mapping)
            else {}
        ),
        cwd=_optional_text(payload.get("cwd")),
        native_home=_optional_text(payload.get("native_home")),
        transport=str(payload.get("transport") or record.transport),
        started_at=str(payload.get("started_at") or record.started_at),
        updated_at=record.updated_at,
        stopped_at=_optional_text(payload.get("stopped_at")),
        exit_code=_optional_int(payload.get("exit_code")),
        metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
        owner_id=record.owner_id,
        owner_process_id=record.owner_process_id,
        process_group_id=record.process_group_id,
        heartbeat_at=record.heartbeat_at,
        leased_until=record.leased_until,
        timeout_at=record.timeout_at,
        cancel_requested_at=record.cancel_requested_at,
        terminal_cursor=record.terminal_cursor,
        recovery_outcome=record.recovery_outcome,
        reconnectable=reconnectable,
    )


def _future_utc(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _positive_timeout(value: float | None) -> float:
    timeout = float(value or 0)
    if timeout <= 0:
        raise ValueError("timeout_seconds must be positive")
    return timeout


def _terminal_dimension(
    value: int,
    *,
    name: str,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _timestamp_expired(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed <= datetime.now(timezone.utc)


def _process_group_id(process_id: int) -> int | None:
    if os.name != "posix":
        return None
    try:
        return os.getpgid(process_id)
    except OSError:
        return None


def _process_state(process_id: int | None) -> str:
    if process_id is None:
        return "unknown"
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return "exited"
    except PermissionError:
        return "unknown"
    except OSError:
        return "unknown"
    return "alive"


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_text(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    return str(value).strip()


def _optional_mapping_text(value: Mapping[str, Any], key: str) -> str | None:
    return _optional_text(value.get(key))


def _text_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value)


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
