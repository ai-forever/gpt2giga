"""Provider-neutral structured transport supervision and event bridging."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
from enum import Enum
import json
import math
import queue
import re
import subprocess
import threading
import time
from typing import Any, Callable, Mapping, Protocol


DEFAULT_FRAME_BYTES = 1024 * 1024
DEFAULT_STDERR_BYTES = 64 * 1024
_EOF = object()
_RUNTIME_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@+~-]{0,255}\Z")


class StructuredProcessError(RuntimeError):
    """Base error for structured process and protocol supervision."""


class StructuredProcessLost(StructuredProcessError):
    """Raised when the owned transport is lost before an operation completes."""


class StructuredRequestTimeout(StructuredProcessError):
    """Raised when one correlated request exceeds its bounded deadline."""


class StructuredRequestCancelled(StructuredProcessError):
    """Raised when a caller wins the cancel/response race."""


class StructuredRemoteError(StructuredProcessError):
    """Raised for a content-free projection of a provider protocol error."""


class StructuredProtocolError(StructuredProcessError):
    """Raised when a structured protocol envelope is invalid."""


class StructuredBridgeError(StructuredProcessError):
    """Raised for stale, duplicate, expired, or unknown bridge responses."""


class StructuredTransportClosed(StructuredProcessError):
    """Raised by a transport after its receive surface reaches EOF."""


class StructuredProcessState(str, Enum):
    """Lifecycle state of one explicitly supervised transport generation."""

    NEW = "new"
    RUNNING = "running"
    LOST = "lost"
    STOPPED = "stopped"


class StructuredBridgeKind(str, Enum):
    """Provider request kinds admitted to the application bridge."""

    APPROVAL = "approval"
    USER_INPUT = "user_input"


@dataclass(frozen=True)
class NormalizedStructuredEvent:
    """One ephemeral provider-neutral event delivered to a driver consumer."""

    type: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    id: str | None = None
    generation: int = 0
    synthetic: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.type, str) or not self.type or len(self.type) > 128:
            raise ValueError("normalized event type is invalid")
        if self.id is not None and (
            not isinstance(self.id, str) or not self.id or len(self.id) > 256
        ):
            raise ValueError("normalized event id is invalid")
        if not isinstance(self.payload, Mapping):
            raise ValueError("normalized event payload must be a mapping")
        if not isinstance(self.generation, int) or isinstance(self.generation, bool):
            raise ValueError("normalized event generation is invalid")
        object.__setattr__(self, "payload", dict(self.payload))


@dataclass(frozen=True)
class StructuredBridgeRequest:
    """One ephemeral provider request awaiting an application-owned decision."""

    id: str | int
    kind: StructuredBridgeKind
    method: str
    params: Mapping[str, Any]
    generation: int
    timeout_seconds: float

    def __post_init__(self) -> None:
        _validate_message_id(self.id)
        if not isinstance(self.kind, StructuredBridgeKind):
            raise ValueError("bridge kind is invalid")
        _validate_method(self.method)
        if not isinstance(self.params, Mapping):
            raise ValueError("bridge params must be a mapping")
        if self.generation < 1:
            raise ValueError("bridge generation must be positive")
        if self.timeout_seconds <= 0:
            raise ValueError("bridge timeout must be positive")
        object.__setattr__(self, "params", dict(self.params))


@dataclass(frozen=True)
class ProtocolFrameFault:
    """Content-free reason one input frame could not be decoded."""

    reason: str


DecodedProtocolFrame = Mapping[str, Any] | ProtocolFrameFault
EventNormalizer = Callable[[str, Mapping[str, Any]], NormalizedStructuredEvent | None]


class StructuredTransport(Protocol):
    """Injected stdio, socket, or SDK transport owned by one supervisor."""

    @property
    def runtime_id(self) -> str:
        """Return a content-free transport identity."""

    @property
    def alive(self) -> bool:
        """Return whether the transport can currently exchange messages."""

    def start(self) -> None:
        """Acquire the underlying process or SDK session."""

    def send(self, payload: Mapping[str, Any]) -> None:
        """Send one structured protocol envelope."""

    def receive(self, timeout: float) -> bytes | Mapping[str, Any] | None:
        """Receive bytes, an SDK message, or ``None`` for a heartbeat timeout."""

    def terminate(self) -> None:
        """Request bounded graceful shutdown."""

    def kill(self) -> None:
        """Force shutdown after graceful termination fails."""

    def wait(self, timeout: float) -> int | None:
        """Wait for shutdown and return an optional process exit code."""


class JsonLineFrameDecoder:
    """Incrementally decode size-bounded JSON-lines without retaining raw faults."""

    def __init__(self, *, max_frame_bytes: int = DEFAULT_FRAME_BYTES) -> None:
        if max_frame_bytes < 64:
            raise ValueError("max_frame_bytes must be at least 64")
        self.max_frame_bytes = max_frame_bytes
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> tuple[DecodedProtocolFrame, ...]:
        """Decode all complete frames from one possibly partial byte chunk."""
        if not isinstance(chunk, bytes):
            raise TypeError("protocol chunks must be bytes")
        self._buffer.extend(chunk)
        frames: list[DecodedProtocolFrame] = []
        while True:
            newline = self._buffer.find(b"\n")
            if newline < 0:
                break
            raw = bytes(self._buffer[:newline])
            del self._buffer[: newline + 1]
            if not raw.strip():
                continue
            frames.append(self._decode(raw))
        if len(self._buffer) > self.max_frame_bytes:
            self._buffer.clear()
            frames.append(ProtocolFrameFault("frame_too_large"))
        return tuple(frames)

    def finish(self) -> tuple[DecodedProtocolFrame, ...]:
        """Discard an incomplete EOF fragment with a content-free fault."""
        if not self._buffer:
            return ()
        self._buffer.clear()
        return (ProtocolFrameFault("partial_frame_at_eof"),)

    def _decode(self, raw: bytes) -> DecodedProtocolFrame:
        if len(raw) > self.max_frame_bytes:
            return ProtocolFrameFault("frame_too_large")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return ProtocolFrameFault("invalid_json")
        if not isinstance(value, Mapping):
            return ProtocolFrameFault("invalid_envelope")
        return dict(value)


class StdioJsonRpcTransport:
    """Own one JSON-lines stdio subprocess behind the structured transport seam."""

    def __init__(
        self,
        *,
        command: tuple[str, ...],
        runtime_id: str,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
        read_queue_size: int = 128,
        max_stderr_bytes: int = DEFAULT_STDERR_BYTES,
    ) -> None:
        if not command:
            raise ValueError("structured stdio command is empty")
        _validate_runtime_id(runtime_id)
        if read_queue_size < 1:
            raise ValueError("read_queue_size must be positive")
        if max_stderr_bytes < 0:
            raise ValueError("max_stderr_bytes cannot be negative")
        self._command = command
        self._runtime_id = runtime_id
        self._env = dict(env) if env is not None else None
        self._cwd = cwd
        self.max_stderr_bytes = max_stderr_bytes
        self._chunks: queue.Queue[bytes | object] = queue.Queue(maxsize=read_queue_size)
        self._stderr: deque[bytes] = deque()
        self._stderr_bytes = 0
        self._stderr_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._closing = threading.Event()
        self._process: subprocess.Popen[bytes] | None = None

    @property
    def runtime_id(self) -> str:
        """Return the caller-supplied content-free runtime identity."""
        return self._runtime_id

    @property
    def alive(self) -> bool:
        """Return whether the subprocess is running."""
        return self._process is not None and self._process.poll() is None

    @property
    def stderr_byte_count(self) -> int:
        """Return retained stderr occupancy without exposing its content."""
        with self._stderr_lock:
            return self._stderr_bytes

    def start(self) -> None:
        """Spawn the configured process and begin bounded pipe readers."""
        if self._process is not None:
            raise StructuredProcessError("structured transport already started")
        try:
            self._process = subprocess.Popen(
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._env,
                cwd=self._cwd,
                start_new_session=True,
            )
        except OSError as exc:
            raise StructuredProcessError(
                "structured transport failed to start"
            ) from exc
        threading.Thread(
            target=self._read_stdout,
            daemon=True,
            name=f"structured-stdout-{self.runtime_id}",
        ).start()
        threading.Thread(
            target=self._read_stderr,
            daemon=True,
            name=f"structured-stderr-{self.runtime_id}",
        ).start()

    def send(self, payload: Mapping[str, Any]) -> None:
        """Serialize one compact JSON-RPC envelope to stdin."""
        process = self._require_process()
        if process.stdin is None or not self.alive:
            raise StructuredTransportClosed("structured stdio transport is closed")
        try:
            encoded = (
                json.dumps(
                    payload,
                    allow_nan=False,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise StructuredProtocolError(
                "structured protocol payload is not JSON-compatible"
            ) from exc
        try:
            with self._write_lock:
                process.stdin.write(encoded)
                process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise StructuredTransportClosed(
                "structured stdio transport is closed"
            ) from exc

    def receive(self, timeout: float) -> bytes | Mapping[str, Any] | None:
        """Receive one stdout chunk through a bounded reader queue."""
        try:
            chunk = self._chunks.get(timeout=max(timeout, 0.0))
        except queue.Empty:
            return None
        if chunk is _EOF:
            raise StructuredTransportClosed("structured stdio transport reached EOF")
        return chunk  # type: ignore[return-value]

    def terminate(self) -> None:
        """Request graceful process termination."""
        self._closing.set()
        if self.alive:
            self._require_process().terminate()

    def kill(self) -> None:
        """Force process termination."""
        self._closing.set()
        if self.alive:
            self._require_process().kill()

    def wait(self, timeout: float) -> int | None:
        """Wait for the process when it was started."""
        if self._process is None:
            return None
        return self._process.wait(timeout=max(timeout, 0.0))

    def _require_process(self) -> subprocess.Popen[bytes]:
        if self._process is None:
            raise StructuredProcessError("structured transport is not started")
        return self._process

    def _read_stdout(self) -> None:
        process = self._require_process()
        if process.stdout is not None:
            while True:
                chunk = process.stdout.read1(65536)
                if not chunk:
                    break
                if not self._offer_chunk(chunk):
                    return
        self._offer_chunk(_EOF)

    def _read_stderr(self) -> None:
        process = self._require_process()
        if process.stderr is None:
            return
        while True:
            chunk = process.stderr.read1(4096)
            if not chunk:
                return
            if self.max_stderr_bytes == 0:
                continue
            with self._stderr_lock:
                if len(chunk) >= self.max_stderr_bytes:
                    self._stderr.clear()
                    self._stderr.append(chunk[-self.max_stderr_bytes :])
                    self._stderr_bytes = self.max_stderr_bytes
                    continue
                self._stderr.append(chunk)
                self._stderr_bytes += len(chunk)
                while self._stderr and self._stderr_bytes > self.max_stderr_bytes:
                    excess = self._stderr_bytes - self.max_stderr_bytes
                    oldest = self._stderr.popleft()
                    if len(oldest) <= excess:
                        self._stderr_bytes -= len(oldest)
                    else:
                        self._stderr.appendleft(oldest[excess:])
                        self._stderr_bytes -= excess

    def _offer_chunk(self, chunk: bytes | object) -> bool:
        while not self._closing.is_set():
            try:
                self._chunks.put(chunk, timeout=0.05)
            except queue.Full:
                continue
            return True
        return False


@dataclass
class _PendingRequest:
    generation: int
    event: threading.Event = field(default_factory=threading.Event)
    result: Mapping[str, Any] | None = None
    error: BaseException | None = None


@dataclass(frozen=True)
class _PendingBridge:
    request: StructuredBridgeRequest
    deadline: float


class StructuredRequestHandle:
    """Caller handle for one generation-bound request/cancel race."""

    def __init__(
        self,
        supervisor: StructuredProcessSupervisor,
        request_id: str,
        pending: _PendingRequest,
    ) -> None:
        self._supervisor = supervisor
        self.id = request_id
        self._pending = pending

    @property
    def generation(self) -> int:
        """Return the transport generation that owns this request."""
        return self._pending.generation

    @property
    def done(self) -> bool:
        """Return whether a response, cancellation, timeout, or loss completed it."""
        return self._pending.event.is_set()

    def result(self, timeout: float) -> Mapping[str, Any]:
        """Wait for the correlated result with a bounded caller deadline."""
        return self._supervisor._wait_request(self.id, self._pending, timeout)

    def cancel(self) -> bool:
        """Cancel only if the response has not already won the race."""
        return self._supervisor.cancel_request(self.id, self._pending.generation)


class _BoundedEventBuffer:
    def __init__(self, size: int) -> None:
        if size < 1:
            raise ValueError("event_queue_size must be positive")
        self.size = size
        self._items: deque[NormalizedStructuredEvent] = deque()
        self._condition = threading.Condition()
        self._closed = False

    def put(self, event: NormalizedStructuredEvent) -> None:
        with self._condition:
            if self._closed:
                return
            if len(self._items) >= self.size:
                dropped = len(self._items) + 1
                self._items.clear()
                self._items.append(
                    NormalizedStructuredEvent(
                        type="resnapshot_required",
                        payload={"dropped_event_count": dropped},
                        generation=event.generation,
                        synthetic=True,
                    )
                )
            else:
                self._items.append(event)
            self._condition.notify()

    def get(self, timeout: float) -> NormalizedStructuredEvent | None:
        deadline = time.monotonic() + max(timeout, 0.0)
        with self._condition:
            while not self._items and not self._closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            return self._items.popleft() if self._items else None

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def __len__(self) -> int:
        with self._condition:
            return len(self._items)


class _BoundedBridgeBuffer:
    def __init__(self, size: int) -> None:
        if size < 1:
            raise ValueError("bridge_queue_size must be positive")
        self.size = size
        self._items: deque[StructuredBridgeRequest] = deque()
        self._condition = threading.Condition()

    def put_nowait(self, request: StructuredBridgeRequest) -> bool:
        with self._condition:
            if len(self._items) >= self.size:
                return False
            self._items.append(request)
            self._condition.notify()
            return True

    def get(self, timeout: float) -> StructuredBridgeRequest | None:
        deadline = time.monotonic() + max(timeout, 0.0)
        with self._condition:
            while not self._items:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            return self._items.popleft()

    def remove(self, generation: int, request_id: str | int) -> None:
        with self._condition:
            self._items = deque(
                item
                for item in self._items
                if not (item.generation == generation and item.id == request_id)
            )

    def clear_generation(self, generation: int) -> None:
        with self._condition:
            self._items = deque(
                item for item in self._items if item.generation != generation
            )


class StructuredProcessSupervisor:
    """Own, correlate, normalize, bridge, and explicitly restart one transport."""

    def __init__(
        self,
        transport_factory: Callable[[], StructuredTransport],
        *,
        event_normalizer: EventNormalizer,
        approval_methods: frozenset[str] = frozenset(),
        input_methods: frozenset[str] = frozenset(),
        event_queue_size: int = 64,
        bridge_queue_size: int = 16,
        bridge_timeout_seconds: float = 30.0,
        max_frame_bytes: int = DEFAULT_FRAME_BYTES,
        stop_timeout_seconds: float = 2.0,
        dedupe_window: int = 1024,
        max_pending_requests: int = 128,
    ) -> None:
        if bridge_timeout_seconds <= 0:
            raise ValueError("bridge_timeout_seconds must be positive")
        if not math.isfinite(bridge_timeout_seconds):
            raise ValueError("bridge_timeout_seconds must be finite")
        if stop_timeout_seconds <= 0:
            raise ValueError("stop_timeout_seconds must be positive")
        if not math.isfinite(stop_timeout_seconds):
            raise ValueError("stop_timeout_seconds must be finite")
        if dedupe_window < 1:
            raise ValueError("dedupe_window must be positive")
        if max_pending_requests < 1:
            raise ValueError("max_pending_requests must be positive")
        for method in (*approval_methods, *input_methods):
            _validate_method(method)
        if approval_methods & input_methods:
            raise ValueError("approval and input methods must not overlap")
        self.transport_factory = transport_factory
        self.event_normalizer = event_normalizer
        self.approval_methods = approval_methods
        self.input_methods = input_methods
        self.bridge_timeout_seconds = float(bridge_timeout_seconds)
        self.max_frame_bytes = max_frame_bytes
        JsonLineFrameDecoder(max_frame_bytes=max_frame_bytes)
        self.stop_timeout_seconds = float(stop_timeout_seconds)
        self.dedupe_window = dedupe_window
        self.max_pending_requests = max_pending_requests
        self._events = _BoundedEventBuffer(event_queue_size)
        self._bridges = _BoundedBridgeBuffer(bridge_queue_size)
        self._lock = threading.RLock()
        self._state = StructuredProcessState.NEW
        self._generation = 0
        self._request_number = 0
        self._transport: StructuredTransport | None = None
        self._pending: dict[str, _PendingRequest] = {}
        self._pending_bridges: dict[tuple[int, str | int], _PendingBridge] = {}
        self._retired_request_ids: deque[str] = deque()
        self._retired_request_id_set: set[str] = set()
        self._seen_event_ids: deque[tuple[int, str]] = deque()
        self._seen_event_id_set: set[tuple[int, str]] = set()
        self._reader_thread: threading.Thread | None = None

    @property
    def state(self) -> StructuredProcessState:
        """Return the current lifecycle state."""
        with self._lock:
            return self._state

    @property
    def generation(self) -> int:
        """Return the current monotonically increasing transport generation."""
        with self._lock:
            return self._generation

    @property
    def runtime_id(self) -> str | None:
        """Return the current content-free transport identity."""
        with self._lock:
            return self._transport.runtime_id if self._transport is not None else None

    @property
    def event_queue_occupancy(self) -> int:
        """Return bounded event occupancy for diagnostics and tests."""
        return len(self._events)

    @property
    def pending_request_count(self) -> int:
        """Return current outbound request occupancy."""
        with self._lock:
            return len(self._pending)

    @property
    def pending_bridge_count(self) -> int:
        """Return current inbound bridge occupancy."""
        with self._lock:
            return len(self._pending_bridges)

    def start(self) -> int:
        """Start only the first transport generation."""
        with self._lock:
            if self._state is not StructuredProcessState.NEW:
                raise StructuredProcessError("structured supervisor already started")
            return self._start_locked()

    def restart(self) -> int:
        """Explicitly start a fresh generation after loss or bounded stop."""
        with self._lock:
            if self._state not in {
                StructuredProcessState.LOST,
                StructuredProcessState.STOPPED,
            }:
                raise StructuredProcessError(
                    "structured supervisor can restart only after loss or stop"
                )
            return self._start_locked()

    def begin_request(
        self, method: str, params: Mapping[str, Any]
    ) -> StructuredRequestHandle:
        """Send one request and return its generation-bound wait handle."""
        _validate_method(method)
        if not isinstance(params, Mapping):
            raise ValueError("structured request params must be a mapping")
        safe_params = _json_mapping(
            params,
            field_name="structured request params",
            max_bytes=self.max_frame_bytes,
        )
        with self._lock:
            transport, generation = self._require_running_locked()
            if len(self._pending) >= self.max_pending_requests:
                raise StructuredProcessError("structured request capacity is exhausted")
            self._request_number += 1
            request_id = f"{generation}:{self._request_number}"
            pending = _PendingRequest(generation)
            self._pending[request_id] = pending
        try:
            transport.send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": safe_params,
                }
            )
        except Exception as exc:
            self._mark_lost(generation, "send_failed")
            raise StructuredProcessLost("structured transport was lost") from exc
        return StructuredRequestHandle(self, request_id, pending)

    def request(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        timeout: float,
    ) -> Mapping[str, Any]:
        """Send and synchronously await one correlated response."""
        return self.begin_request(method, params).result(timeout)

    def notify(self, method: str, params: Mapping[str, Any]) -> None:
        """Send one generation-bound notification without inventing a response."""
        _validate_method(method)
        if not isinstance(params, Mapping):
            raise ValueError("structured notification params must be a mapping")
        safe_params = _json_mapping(
            params,
            field_name="structured notification params",
            max_bytes=self.max_frame_bytes,
        )
        with self._lock:
            transport, generation = self._require_running_locked()
        try:
            transport.send(
                {
                    "jsonrpc": "2.0",
                    "method": method,
                    "params": safe_params,
                }
            )
        except Exception as exc:
            self._mark_lost(generation, "send_failed")
            raise StructuredProcessLost("structured transport was lost") from exc

    def cancel_request(self, request_id: str, generation: int) -> bool:
        """Cancel a pending request when cancellation wins the response race."""
        with self._lock:
            pending = self._pending.get(request_id)
            if pending is None or pending.generation != generation:
                return False
            self._pending.pop(request_id, None)
            self._retire_request_id_locked(request_id)
            pending.error = StructuredRequestCancelled("structured request canceled")
            pending.event.set()
            transport = self._transport if generation == self._generation else None
            running = self._state is StructuredProcessState.RUNNING
        if transport is not None and running:
            try:
                transport.send(
                    {
                        "jsonrpc": "2.0",
                        "method": "$/cancelRequest",
                        "params": {"id": request_id},
                    }
                )
            except Exception:
                self._mark_lost(generation, "cancel_send_failed")
        return True

    def next_event(self, *, timeout: float) -> NormalizedStructuredEvent | None:
        """Return the next normalized event or ``None`` on heartbeat timeout."""
        return self._events.get(timeout)

    def next_bridge_request(self, *, timeout: float) -> StructuredBridgeRequest | None:
        """Return the next live approval/input request, skipping stale entries."""
        deadline = time.monotonic() + max(timeout, 0.0)
        while True:
            self._expire_bridges()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            request = self._bridges.get(remaining)
            if request is None:
                return None
            with self._lock:
                if (request.generation, request.id) in self._pending_bridges:
                    return request

    def respond_bridge(
        self,
        request_id: str | int,
        *,
        generation: int,
        result: Mapping[str, Any] | None = None,
        error_code: int | None = None,
    ) -> None:
        """Respond exactly once to a live generation-bound provider request."""
        _validate_message_id(request_id)
        if result is not None and not isinstance(result, Mapping):
            raise ValueError("bridge result must be a mapping")
        if result is not None and error_code is not None:
            raise ValueError("bridge result and error are mutually exclusive")
        if isinstance(error_code, bool):
            raise ValueError("bridge error code must be an integer")
        safe_result = (
            _json_mapping(
                result,
                field_name="structured bridge result",
                max_bytes=self.max_frame_bytes,
            )
            if result is not None
            else {}
        )
        key = (generation, request_id)
        with self._lock:
            pending = self._pending_bridges.pop(key, None)
            if pending is None:
                raise StructuredBridgeError(
                    "structured bridge request is stale, expired, or unknown"
                )
            transport, current_generation = self._require_running_locked()
            if generation != current_generation:
                raise StructuredBridgeError("structured bridge generation is stale")
        self._bridges.remove(generation, request_id)
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
        if error_code is None:
            payload["result"] = safe_result
        else:
            payload["error"] = {
                "code": int(error_code),
                "message": "request rejected",
            }
        try:
            transport.send(payload)
        except Exception as exc:
            self._mark_lost(generation, "bridge_send_failed")
            raise StructuredProcessLost("structured transport was lost") from exc

    def close(self) -> None:
        """Fail pending work and stop the current transport with a kill fallback."""
        with self._lock:
            if self._state is StructuredProcessState.STOPPED:
                return
            generation = self._generation
            transport = self._transport
            self._state = StructuredProcessState.STOPPED
            self._fail_pending_locked(
                StructuredProcessLost("structured supervisor stopped")
            )
            self._pending_bridges.clear()
        self._bridges.clear_generation(generation)
        if transport is not None:
            transport.terminate()
            try:
                transport.wait(self.stop_timeout_seconds)
            except subprocess.TimeoutExpired:
                transport.kill()
                transport.wait(self.stop_timeout_seconds)
            except StructuredProcessError:
                # Closing is best-effort after pending work has already failed.
                pass
        self._events.put(
            NormalizedStructuredEvent(
                type="process_stopped",
                generation=generation,
                synthetic=True,
            )
        )

    def _start_locked(self) -> int:
        transport = self.transport_factory()
        _validate_runtime_id(transport.runtime_id)
        transport.start()
        self._generation += 1
        generation = self._generation
        self._transport = transport
        self._state = StructuredProcessState.RUNNING
        reader = threading.Thread(
            target=self._read_loop,
            args=(transport, generation),
            daemon=True,
            name=f"structured-supervisor-{transport.runtime_id}-{generation}",
        )
        self._reader_thread = reader
        reader.start()
        self._events.put(
            NormalizedStructuredEvent(
                type="process_started",
                payload={"runtime_id": transport.runtime_id},
                generation=generation,
                synthetic=True,
            )
        )
        return generation

    def _wait_request(
        self,
        request_id: str,
        pending: _PendingRequest,
        timeout: float,
    ) -> Mapping[str, Any]:
        if timeout <= 0:
            raise ValueError("request timeout must be positive")
        if not pending.event.wait(timeout):
            with self._lock:
                current = self._pending.get(request_id)
                if current is pending:
                    self._pending.pop(request_id, None)
                    self._retire_request_id_locked(request_id)
                    pending.error = StructuredRequestTimeout(
                        "structured request timed out"
                    )
                    pending.event.set()
        if pending.error is not None:
            raise pending.error
        if pending.result is None:
            raise StructuredProtocolError("structured response has no result")
        return dict(pending.result)

    def _read_loop(self, transport: StructuredTransport, generation: int) -> None:
        decoder = JsonLineFrameDecoder(max_frame_bytes=self.max_frame_bytes)
        try:
            while True:
                with self._lock:
                    if (
                        generation != self._generation
                        or self._state is not StructuredProcessState.RUNNING
                    ):
                        return
                self._expire_bridges()
                message = transport.receive(0.05)
                if message is None:
                    if not transport.alive:
                        raise StructuredTransportClosed(
                            "structured transport is not alive"
                        )
                    continue
                frames: tuple[DecodedProtocolFrame, ...]
                if isinstance(message, bytes):
                    frames = decoder.feed(message)
                elif isinstance(message, Mapping):
                    try:
                        frames = (
                            _json_mapping(
                                message,
                                field_name="SDK protocol message",
                                max_bytes=self.max_frame_bytes,
                            ),
                        )
                    except ValueError as exc:
                        reason = (
                            "frame_too_large"
                            if "size limit" in str(exc)
                            else "invalid_transport_message"
                        )
                        frames = (ProtocolFrameFault(reason),)
                else:
                    frames = (ProtocolFrameFault("invalid_transport_message"),)
                for frame in frames:
                    self._handle_frame(frame, transport, generation)
        except StructuredTransportClosed:
            for frame in decoder.finish():
                self._handle_frame(frame, transport, generation)
            self._mark_lost(generation, "transport_closed")
        except Exception:
            self._protocol_fault(generation, "reader_failed")
            self._mark_lost(generation, "reader_failed")

    def _handle_frame(
        self,
        frame: DecodedProtocolFrame,
        transport: StructuredTransport,
        generation: int,
    ) -> None:
        if isinstance(frame, ProtocolFrameFault):
            self._protocol_fault(generation, frame.reason)
            return
        if frame.get("jsonrpc", "2.0") != "2.0":
            self._protocol_fault(generation, "unsupported_protocol_version")
            return
        method = frame.get("method")
        request_id = frame.get("id")
        if method is None:
            self._handle_response(frame, generation)
            return
        if not isinstance(method, str) or not method or len(method) > 256:
            self._protocol_fault(generation, "invalid_method")
            return
        params = frame.get("params", {})
        if not isinstance(params, Mapping):
            self._protocol_fault(generation, "invalid_params")
            if request_id is not None:
                self._send_bridge_error(
                    transport, request_id, -32602, generation=generation
                )
            return
        if request_id is not None:
            self._handle_provider_request(
                transport,
                generation,
                request_id,
                method,
                params,
            )
            return
        try:
            event = self.event_normalizer(method, params)
        except Exception:
            self._protocol_fault(generation, "event_normalization_failed")
            return
        if event is None:
            return
        if not isinstance(event, NormalizedStructuredEvent):
            self._protocol_fault(generation, "invalid_normalized_event")
            return
        try:
            safe_payload = _json_mapping(
                event.payload,
                field_name="normalized event payload",
                max_bytes=self.max_frame_bytes,
            )
        except ValueError:
            self._protocol_fault(generation, "invalid_normalized_event")
            return
        event = replace(event, generation=generation, payload=safe_payload)
        if self._is_duplicate_event(event):
            return
        self._events.put(event)

    def _handle_response(self, frame: Mapping[str, Any], generation: int) -> None:
        request_id = frame.get("id")
        if not isinstance(request_id, str):
            self._protocol_fault(generation, "invalid_response_id")
            return
        with self._lock:
            pending = self._pending.pop(request_id, None)
            if pending is None or pending.generation != generation:
                self._protocol_fault(generation, "unknown_or_late_response")
                return
            self._retire_request_id_locked(request_id)
            if "result" in frame and "error" not in frame:
                result = frame.get("result")
                if not isinstance(result, Mapping):
                    pending.error = StructuredProtocolError(
                        "structured response result is invalid"
                    )
                else:
                    pending.result = dict(result)
            elif "error" in frame and "result" not in frame:
                error = frame.get("error")
                code = error.get("code") if isinstance(error, Mapping) else None
                suffix = f" ({code})" if isinstance(code, int) else ""
                pending.error = StructuredRemoteError(
                    f"structured provider request failed{suffix}"
                )
            else:
                pending.error = StructuredProtocolError(
                    "structured response envelope is invalid"
                )
            pending.event.set()

    def _handle_provider_request(
        self,
        transport: StructuredTransport,
        generation: int,
        request_id: Any,
        method: str,
        params: Mapping[str, Any],
    ) -> None:
        try:
            _validate_message_id(request_id)
        except ValueError:
            self._protocol_fault(generation, "invalid_provider_request_id")
            return
        if method in self.approval_methods:
            kind = StructuredBridgeKind.APPROVAL
        elif method in self.input_methods:
            kind = StructuredBridgeKind.USER_INPUT
        else:
            self._send_bridge_error(
                transport, request_id, -32601, generation=generation
            )
            self._protocol_fault(generation, "unsupported_provider_request")
            return
        key = (generation, request_id)
        request = StructuredBridgeRequest(
            id=request_id,
            kind=kind,
            method=method,
            params=params,
            generation=generation,
            timeout_seconds=self.bridge_timeout_seconds,
        )
        with self._lock:
            if key in self._pending_bridges:
                duplicate = True
            else:
                duplicate = False
                self._pending_bridges[key] = _PendingBridge(
                    request=request,
                    deadline=time.monotonic() + self.bridge_timeout_seconds,
                )
        if duplicate:
            self._send_bridge_error(
                transport, request_id, -32600, generation=generation
            )
            self._protocol_fault(generation, "duplicate_provider_request")
            return
        if not self._bridges.put_nowait(request):
            with self._lock:
                self._pending_bridges.pop(key, None)
            self._send_bridge_error(
                transport, request_id, -32002, generation=generation
            )
            self._events.put(
                NormalizedStructuredEvent(
                    type="bridge_rejected",
                    payload={"kind": kind.value, "reason": "capacity"},
                    generation=generation,
                    synthetic=True,
                )
            )

    def _expire_bridges(self) -> None:
        now = time.monotonic()
        with self._lock:
            if self._state is not StructuredProcessState.RUNNING:
                return
            transport = self._transport
            generation = self._generation
            expired = [
                (key, item)
                for key, item in self._pending_bridges.items()
                if key[0] == generation and item.deadline <= now
            ]
            for key, _ in expired:
                self._pending_bridges.pop(key, None)
        if transport is None:
            return
        for (_, request_id), item in expired:
            self._bridges.remove(generation, request_id)
            self._send_bridge_error(
                transport, request_id, -32001, generation=generation
            )
            self._events.put(
                NormalizedStructuredEvent(
                    type="bridge_timeout",
                    payload={"kind": item.request.kind.value},
                    generation=generation,
                    synthetic=True,
                )
            )

    def _send_bridge_error(
        self,
        transport: StructuredTransport,
        request_id: str | int,
        code: int,
        *,
        generation: int,
    ) -> None:
        try:
            transport.send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": code, "message": "request rejected"},
                }
            )
        except Exception:
            self._mark_lost(generation, "bridge_error_send_failed")

    def _protocol_fault(self, generation: int, reason: str) -> None:
        self._events.put(
            NormalizedStructuredEvent(
                type="protocol_error",
                payload={"reason": reason},
                generation=generation,
                synthetic=True,
            )
        )

    def _is_duplicate_event(self, event: NormalizedStructuredEvent) -> bool:
        if event.id is None:
            return False
        key = (event.generation, event.id)
        with self._lock:
            if key in self._seen_event_id_set:
                return True
            self._seen_event_ids.append(key)
            self._seen_event_id_set.add(key)
            while len(self._seen_event_ids) > self.dedupe_window:
                self._seen_event_id_set.discard(self._seen_event_ids.popleft())
        return False

    def _mark_lost(self, generation: int, reason: str) -> None:
        with self._lock:
            if (
                generation != self._generation
                or self._state is not StructuredProcessState.RUNNING
            ):
                return
            self._state = StructuredProcessState.LOST
            self._fail_pending_locked(
                StructuredProcessLost("structured transport was lost")
            )
            self._pending_bridges = {
                key: value
                for key, value in self._pending_bridges.items()
                if key[0] != generation
            }
            transport = self._transport
        self._bridges.clear_generation(generation)
        self._events.put(
            NormalizedStructuredEvent(
                type="process_lost",
                payload={"reason": reason},
                generation=generation,
                synthetic=True,
            )
        )
        self._stop_transport(transport)

    def _fail_pending_locked(self, error: BaseException) -> None:
        pending = tuple(self._pending.items())
        self._pending.clear()
        for request_id, item in pending:
            self._retire_request_id_locked(request_id)
            item.error = error
            item.event.set()

    def _retire_request_id_locked(self, request_id: str) -> None:
        if request_id in self._retired_request_id_set:
            return
        self._retired_request_ids.append(request_id)
        self._retired_request_id_set.add(request_id)
        while len(self._retired_request_ids) > self.dedupe_window:
            self._retired_request_id_set.discard(self._retired_request_ids.popleft())

    def _require_running_locked(self) -> tuple[StructuredTransport, int]:
        if self._state is not StructuredProcessState.RUNNING or self._transport is None:
            raise StructuredProcessLost("structured transport is not running")
        return self._transport, self._generation

    def _stop_transport(self, transport: StructuredTransport | None) -> None:
        if transport is None or not transport.alive:
            return
        try:
            transport.terminate()
            transport.wait(self.stop_timeout_seconds)
        except subprocess.TimeoutExpired:
            transport.kill()
            try:
                transport.wait(self.stop_timeout_seconds)
            except Exception:
                return
        except Exception:
            return


def _validate_method(method: str) -> None:
    if not isinstance(method, str) or not method or len(method) > 256:
        raise ValueError("structured method is invalid")


def _validate_runtime_id(runtime_id: str) -> None:
    if not isinstance(runtime_id, str) or _RUNTIME_ID_RE.fullmatch(runtime_id) is None:
        raise ValueError("structured runtime_id is invalid")


def _validate_message_id(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("structured message id is invalid")
    if isinstance(value, str) and (not value or len(value) > 256):
        raise ValueError("structured message id is invalid")


def _json_mapping(
    value: Mapping[str, Any],
    *,
    field_name: str,
    max_bytes: int,
) -> dict[str, Any]:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be JSON-compatible") from exc
    if len(encoded) > max_bytes:
        raise ValueError(f"{field_name} exceeds the size limit")
    decoded = json.loads(encoded)
    if not isinstance(decoded, dict):
        raise ValueError(f"{field_name} must be a mapping")
    return decoded
