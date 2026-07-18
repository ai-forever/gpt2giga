from __future__ import annotations

import json
import queue
import subprocess
import sys
import time
from typing import Any, Mapping

import pytest

from gpt2giga_harness.structured_processes import (
    JsonLineFrameDecoder,
    NormalizedStructuredEvent,
    ProtocolFrameFault,
    StdioJsonRpcTransport,
    StructuredBridgeError,
    StructuredBridgeKind,
    StructuredProcessError,
    StructuredProcessLost,
    StructuredProcessState,
    StructuredProcessSupervisor,
    StructuredRemoteError,
    StructuredRequestCancelled,
    StructuredRequestTimeout,
    StructuredTransportClosed,
)


_CLOSED = object()


class _FakeTransport:
    def __init__(self, runtime_id: str) -> None:
        self._runtime_id = runtime_id
        self.incoming: queue.Queue[bytes | Mapping[str, Any] | object] = queue.Queue()
        self.sent: list[dict[str, Any]] = []
        self._alive = False
        self.terminated = False
        self.killed = False

    @property
    def runtime_id(self):
        return self._runtime_id

    @property
    def alive(self):
        return self._alive

    def start(self):
        self._alive = True

    def send(self, payload):
        if not self._alive:
            raise StructuredTransportClosed("closed")
        self.sent.append(dict(payload))

    def receive(self, timeout):
        try:
            message = self.incoming.get(timeout=timeout)
        except queue.Empty:
            return None
        if message is _CLOSED:
            self._alive = False
            raise StructuredTransportClosed("closed")
        return message

    def terminate(self):
        self.terminated = True
        self._alive = False

    def kill(self):
        self.killed = True
        self._alive = False

    def wait(self, timeout):
        del timeout
        return 0

    def push(self, message):
        self.incoming.put(message)

    def lose(self):
        self.incoming.put(_CLOSED)


class _TransportFactory:
    def __init__(self):
        self.transports: list[_FakeTransport] = []

    def __call__(self):
        transport = _FakeTransport(f"runtime-{len(self.transports) + 1}")
        self.transports.append(transport)
        return transport


def _normalizer(method, params):
    if method == "event/fail":
        raise ValueError("provider-owned bad event")
    if method == "event/invalid":
        return "not-an-event"
    if method == "event/non-json":
        return NormalizedStructuredEvent(
            type="output_delta", payload={"value": object()}
        )
    if method != "event/update":
        return None
    return NormalizedStructuredEvent(
        type=str(params.get("type", "output_delta")),
        id=str(params["event_id"]) if "event_id" in params else None,
        payload={key: value for key, value in params.items() if key != "event_id"},
    )


def _supervisor(factory=None, **overrides):
    factory = factory or _TransportFactory()
    values = {
        "event_normalizer": _normalizer,
        "approval_methods": frozenset({"approval/request"}),
        "input_methods": frozenset({"input/request"}),
    }
    values.update(overrides)
    return StructuredProcessSupervisor(factory, **values), factory


def _wait_for(predicate, *, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not reached")


def _next_type(supervisor, expected, *, timeout=1.0):
    deadline = time.monotonic() + timeout
    seen = []
    while time.monotonic() < deadline:
        event = supervisor.next_event(timeout=deadline - time.monotonic())
        if event is None:
            break
        seen.append(event.type)
        if event.type == expected:
            return event
    raise AssertionError(f"event {expected!r} not found; saw {seen!r}")


def test_json_line_decoder_handles_partial_invalid_and_oversized_frames():
    decoder = JsonLineFrameDecoder(max_frame_bytes=64)

    assert decoder.feed(b'{"jsonrpc":"2.0",') == ()
    frames = decoder.feed(b'"method":"event/update"}\nnot-json\n')

    assert frames[0] == {"jsonrpc": "2.0", "method": "event/update"}
    assert frames[1] == ProtocolFrameFault("invalid_json")
    assert decoder.feed(b"x" * 65) == (ProtocolFrameFault("frame_too_large"),)
    assert decoder.feed(b"partial") == ()
    assert decoder.finish() == (ProtocolFrameFault("partial_frame_at_eof"),)


def test_sdk_messages_requests_and_normalized_events_are_byte_and_json_bounded():
    supervisor, factory = _supervisor(max_frame_bytes=128)
    supervisor.start()
    transport = factory.transports[0]
    _next_type(supervisor, "process_started")

    with pytest.raises(ValueError, match="size limit"):
        supervisor.begin_request("thread/open", {"value": "x" * 256})
    with pytest.raises(ValueError, match="JSON-compatible"):
        supervisor.begin_request("thread/open", {"value": float("nan")})
    assert supervisor.state is StructuredProcessState.RUNNING
    assert transport.sent == []

    transport.push(
        {
            "jsonrpc": "2.0",
            "method": "event/update",
            "params": {"value": "x" * 256},
        }
    )
    assert _next_type(supervisor, "protocol_error").payload == {
        "reason": "frame_too_large"
    }
    transport.push({"jsonrpc": "2.0", "method": "event/non-json", "params": {}})
    assert _next_type(supervisor, "protocol_error").payload == {
        "reason": "invalid_normalized_event"
    }
    supervisor.close()


def test_supervisor_correlates_fragmented_responses_and_bounds_protocol_faults():
    supervisor, factory = _supervisor()
    assert supervisor.start() == 1
    transport = factory.transports[0]
    assert _next_type(supervisor, "process_started").payload == {
        "runtime_id": "runtime-1"
    }

    handle = supervisor.begin_request("thread/open", {"private": "prompt-canary"})
    request_id = transport.sent[-1]["id"]
    encoded = (
        json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "result": {"thread": "one"}}
        ).encode()
        + b"\n"
    )
    transport.push(encoded[:9])
    transport.push(encoded[9:])

    assert handle.result(1.0) == {"thread": "one"}
    assert supervisor.pending_request_count == 0

    transport.push(b'{"private":"raw-canary" not-json}\n')
    transport.push({"jsonrpc": "2.0", "method": "event/update", "params": "bad"})
    transport.push({"jsonrpc": "1.0", "method": "event/update", "params": {}})
    transport.push({"jsonrpc": "2.0", "method": "event/fail", "params": {}})
    transport.push({"jsonrpc": "2.0", "method": "event/invalid", "params": {}})

    errors = [_next_type(supervisor, "protocol_error") for _ in range(5)]
    evidence = json.dumps([event.payload for event in errors], sort_keys=True)
    assert "canary" not in evidence
    assert {event.payload["reason"] for event in errors} == {
        "invalid_json",
        "invalid_params",
        "unsupported_protocol_version",
        "event_normalization_failed",
        "invalid_normalized_event",
    }
    supervisor.close()


def test_events_are_deduplicated_and_slow_consumers_get_resnapshot_marker():
    supervisor, factory = _supervisor(event_queue_size=2)
    supervisor.start()
    transport = factory.transports[0]
    _next_type(supervisor, "process_started")

    duplicate = {
        "jsonrpc": "2.0",
        "method": "event/update",
        "params": {"event_id": "same", "type": "turn_started"},
    }
    transport.push(duplicate)
    transport.push(duplicate)
    assert _next_type(supervisor, "turn_started").id == "same"
    assert supervisor.next_event(timeout=0.05) is None

    for index in range(3):
        transport.push(
            {
                "jsonrpc": "2.0",
                "method": "event/update",
                "params": {"event_id": f"event-{index}", "index": index},
            }
        )
    _wait_for(lambda: supervisor.event_queue_occupancy == 1)
    gap = supervisor.next_event(timeout=1.0)
    assert gap is not None
    assert gap.type == "resnapshot_required"
    assert gap.payload == {"dropped_event_count": 3}
    assert gap.synthetic is True
    assert supervisor.event_queue_occupancy <= 2
    supervisor.close()


def test_approval_and_input_bridge_round_trip_timeout_duplicate_and_capacity():
    supervisor, factory = _supervisor(
        bridge_queue_size=1,
        bridge_timeout_seconds=0.08,
    )
    supervisor.start()
    transport = factory.transports[0]
    _next_type(supervisor, "process_started")

    transport.push(
        {
            "jsonrpc": "2.0",
            "id": "approval-1",
            "method": "approval/request",
            "params": {"command": "private-canary"},
        }
    )
    approval = supervisor.next_bridge_request(timeout=1.0)
    assert approval is not None
    assert approval.kind is StructuredBridgeKind.APPROVAL
    assert approval.params == {"command": "private-canary"}
    supervisor.respond_bridge(
        approval.id,
        generation=approval.generation,
        result={"decision": "deny"},
    )
    assert transport.sent[-1] == {
        "jsonrpc": "2.0",
        "id": "approval-1",
        "result": {"decision": "deny"},
    }
    with pytest.raises(StructuredBridgeError, match="stale, expired, or unknown"):
        supervisor.respond_bridge(
            approval.id,
            generation=approval.generation,
            result={"decision": "allow"},
        )

    transport.push(
        {
            "jsonrpc": "2.0",
            "id": "input-1",
            "method": "input/request",
            "params": {"question": "private"},
        }
    )
    transport.push(
        {
            "jsonrpc": "2.0",
            "id": "input-2",
            "method": "input/request",
            "params": {"question": "also-private"},
        }
    )
    rejected = _next_type(supervisor, "bridge_rejected")
    assert rejected.payload == {"kind": "user_input", "reason": "capacity"}
    assert any(
        item.get("id") == "input-2" and item.get("error", {}).get("code") == -32002
        for item in transport.sent
    )
    request = supervisor.next_bridge_request(timeout=1.0)
    assert request is not None and request.id == "input-1"

    transport.push(
        {
            "jsonrpc": "2.0",
            "id": "input-1",
            "method": "input/request",
            "params": {},
        }
    )
    duplicate = _next_type(supervisor, "protocol_error")
    assert duplicate.payload == {"reason": "duplicate_provider_request"}

    timeout = _next_type(supervisor, "bridge_timeout")
    assert timeout.payload == {"kind": "user_input"}
    assert any(
        item.get("id") == "input-1" and item.get("error", {}).get("code") == -32001
        for item in transport.sent
    )
    with pytest.raises(StructuredBridgeError):
        supervisor.respond_bridge(
            request.id,
            generation=request.generation,
            result={"answer": "late"},
        )
    supervisor.close()


def test_request_timeout_cancel_response_race_and_remote_errors_are_bounded():
    supervisor, factory = _supervisor(max_pending_requests=1)
    supervisor.start()
    transport = factory.transports[0]
    _next_type(supervisor, "process_started")

    timed_out = supervisor.begin_request("slow/request", {})
    with pytest.raises(StructuredProcessError, match="capacity is exhausted"):
        supervisor.begin_request("over-capacity", {})
    with pytest.raises(StructuredRequestTimeout):
        timed_out.result(0.02)
    transport.push({"jsonrpc": "2.0", "id": timed_out.id, "result": {"too": "late"}})
    assert _next_type(supervisor, "protocol_error").payload == {
        "reason": "unknown_or_late_response"
    }

    canceled = supervisor.begin_request("cancel/request", {})
    assert canceled.cancel() is True
    assert canceled.cancel() is False
    with pytest.raises(StructuredRequestCancelled):
        canceled.result(0.1)
    assert transport.sent[-1] == {
        "jsonrpc": "2.0",
        "method": "$/cancelRequest",
        "params": {"id": canceled.id},
    }
    transport.push({"jsonrpc": "2.0", "id": canceled.id, "result": {"too": "late"}})
    _next_type(supervisor, "protocol_error")

    completed = supervisor.begin_request("fast/request", {})
    transport.push({"jsonrpc": "2.0", "id": completed.id, "result": {"ok": True}})
    assert completed.result(1.0) == {"ok": True}
    assert completed.cancel() is False

    failed = supervisor.begin_request("failed/request", {})
    transport.push(
        {
            "jsonrpc": "2.0",
            "id": failed.id,
            "error": {"code": 500, "message": "remote-secret-canary"},
        }
    )
    with pytest.raises(StructuredRemoteError) as exc_info:
        failed.result(1.0)
    assert "remote-secret-canary" not in str(exc_info.value)
    assert "500" in str(exc_info.value)
    supervisor.close()


def test_process_loss_fails_pending_work_and_restart_is_generation_isolated():
    supervisor, factory = _supervisor()
    assert supervisor.start() == 1
    first = factory.transports[0]
    _next_type(supervisor, "process_started")
    pending = supervisor.begin_request("thread/open", {})
    first.push(
        {
            "jsonrpc": "2.0",
            "id": "old-bridge",
            "method": "approval/request",
            "params": {},
        }
    )
    _wait_for(lambda: supervisor.pending_bridge_count == 1)
    first.lose()

    with pytest.raises(StructuredProcessLost):
        pending.result(1.0)
    lost = _next_type(supervisor, "process_lost")
    assert lost.generation == 1
    assert supervisor.state is StructuredProcessState.LOST
    assert supervisor.pending_request_count == 0
    assert supervisor.pending_bridge_count == 0

    assert supervisor.restart() == 2
    second = factory.transports[1]
    started = _next_type(supervisor, "process_started")
    assert started.generation == 2
    assert supervisor.runtime_id == "runtime-2"

    second.push(
        {
            "jsonrpc": "2.0",
            "id": "new-bridge",
            "method": "approval/request",
            "params": {},
        }
    )
    bridge = supervisor.next_bridge_request(timeout=1.0)
    assert bridge is not None and bridge.id == "new-bridge"
    supervisor.respond_bridge(
        bridge.id,
        generation=bridge.generation,
        result={"decision": "deny"},
    )

    fresh = supervisor.begin_request("thread/resume", {})
    assert fresh.id.startswith("2:")
    second.push({"jsonrpc": "2.0", "id": fresh.id, "result": {"thread": "resumed"}})
    assert fresh.result(1.0) == {"thread": "resumed"}
    with pytest.raises(StructuredBridgeError):
        supervisor.respond_bridge(
            "old-bridge",
            generation=1,
            result={"decision": "deny"},
        )
    supervisor.close()


def test_real_stdio_transport_owns_fragmented_json_rpc_and_bounded_cleanup():
    child = """
import json
import sys
import time

line = sys.stdin.buffer.readline()
request = json.loads(line)
payload = json.dumps({
    "jsonrpc": "2.0",
    "id": request["id"],
    "result": {"echo": request["params"]["value"]},
}, separators=(",", ":")).encode() + b"\\n"
sys.stdout.buffer.write(payload[:7])
sys.stdout.buffer.flush()
time.sleep(0.02)
sys.stdout.buffer.write(payload[7:])
sys.stdout.buffer.flush()
sys.stderr.buffer.write(b"private-stderr-canary")
sys.stderr.buffer.flush()
sys.stdin.buffer.read()
"""
    transports = []

    def factory():
        transport = StdioJsonRpcTransport(
            command=(sys.executable, "-c", child),
            runtime_id="fake-stdio-1",
            read_queue_size=2,
            max_stderr_bytes=8,
        )
        transports.append(transport)
        return transport

    supervisor = StructuredProcessSupervisor(
        factory,
        event_normalizer=_normalizer,
        stop_timeout_seconds=0.5,
    )
    supervisor.start()
    _next_type(supervisor, "process_started")

    assert supervisor.request("echo", {"value": 7}, timeout=2.0) == {"echo": 7}
    _wait_for(lambda: transports[0].stderr_byte_count > 0)
    assert transports[0].stderr_byte_count <= 8

    supervisor.close()
    assert supervisor.state is StructuredProcessState.STOPPED
    assert transports[0].alive is False
    assert transports[0].stderr_byte_count <= 8


def test_close_uses_kill_fallback_when_graceful_wait_times_out():
    class _StubbornTransport(_FakeTransport):
        def wait(self, timeout):
            del timeout
            if not self.killed:
                raise subprocess.TimeoutExpired("fake", 0.01)
            return -9

        def terminate(self):
            self.terminated = True

    transport = _StubbornTransport("stubborn")
    supervisor = StructuredProcessSupervisor(
        lambda: transport,
        event_normalizer=_normalizer,
        stop_timeout_seconds=0.01,
    )
    supervisor.start()
    _next_type(supervisor, "process_started")
    supervisor.close()

    assert transport.terminated is True
    assert transport.killed is True
