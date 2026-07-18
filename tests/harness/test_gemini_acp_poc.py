from __future__ import annotations

import json
from pathlib import Path
import queue
import time
from typing import Any, Mapping

import pytest

from gpt2giga_harness.gemini_acp_poc import (
    GEMINI_ACP_PERMISSION_METHOD,
    GeminiAcpPocClient,
    GeminiAcpPocError,
    normalize_gemini_acp_event,
    probe_gemini_acp_handshake,
)
from gpt2giga_harness.structured_processes import StructuredTransportClosed


FIXTURE_ROOT = Path("tests/fixtures/harness_cli/gemini/0.46")
_CLOSED = object()


def _initialize_fixture() -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / "acp_initialize.json").read_text())


def _help_fixture() -> str:
    return (FIXTURE_ROOT / "acp_help.txt").read_text()


class _ScriptedAcpTransport:
    def __init__(self, runtime_id: str, initialize_result: Mapping[str, Any]) -> None:
        self._runtime_id = runtime_id
        self.initialize_result = dict(initialize_result)
        self.incoming: queue.Queue[Mapping[str, Any] | object] = queue.Queue()
        self.sent: list[dict[str, Any]] = []
        self._alive = False
        self.prompt_ids: list[str] = []

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
        message = dict(payload)
        self.sent.append(message)
        method = message.get("method")
        request_id = message.get("id")
        if method == "initialize":
            self._respond(request_id, self.initialize_result)
        elif method == "authenticate":
            self._respond(request_id, {})
        elif method == "session/new":
            self._respond(
                request_id,
                {
                    "sessionId": "11111111-1111-4111-8111-111111111111",
                    "modes": {"availableModes": [], "currentModeId": "default"},
                },
            )
        elif method == "session/load":
            self._respond(
                request_id,
                {"modes": {"availableModes": [], "currentModeId": "default"}},
            )
        elif method == "session/prompt":
            self.prompt_ids.append(request_id)
            if len(self.prompt_ids) == 1:
                self.incoming.put(
                    {
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "sessionId": "11111111-1111-4111-8111-111111111111",
                            "update": {
                                "sessionUpdate": "agent_message_chunk",
                                "content": {"type": "text", "text": "fixture output"},
                            },
                        },
                    }
                )
                self.incoming.put(
                    {
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "sessionId": "11111111-1111-4111-8111-111111111111",
                            "update": {
                                "sessionUpdate": "tool_call",
                                "toolCallId": "tool-1",
                                "status": "pending",
                                "title": "Write fixture",
                                "kind": "edit",
                                "rawInput": "must-not-be-normalized",
                            },
                        },
                    }
                )
                self.incoming.put(
                    {
                        "jsonrpc": "2.0",
                        "id": "permission-1",
                        "method": GEMINI_ACP_PERMISSION_METHOD,
                        "params": {
                            "sessionId": "11111111-1111-4111-8111-111111111111",
                            "options": [
                                {
                                    "optionId": "proceed_once",
                                    "name": "Allow once",
                                    "kind": "allow_once",
                                },
                                {
                                    "optionId": "cancel",
                                    "name": "Deny",
                                    "kind": "reject_once",
                                },
                            ],
                            "toolCall": {
                                "toolCallId": "tool-1",
                                "status": "pending",
                                "title": "Write fixture",
                            },
                        },
                    }
                )
        elif method == "session/cancel":
            self._respond(self.prompt_ids[-1], {"stopReason": "cancelled"})
        elif message.get("id") == "permission-1" and "result" in message:
            self.incoming.put(
                {
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": "11111111-1111-4111-8111-111111111111",
                        "update": {
                            "sessionUpdate": "tool_call_update",
                            "toolCallId": "tool-1",
                            "status": "completed",
                            "rawOutput": "must-not-be-normalized",
                        },
                    },
                }
            )
            self._respond(self.prompt_ids[0], {"stopReason": "end_turn"})

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
        self._alive = False

    def kill(self):
        self._alive = False

    def wait(self, timeout):
        del timeout
        return 0

    def lose(self):
        self.incoming.put(_CLOSED)

    def _respond(self, request_id, result):
        self.incoming.put({"jsonrpc": "2.0", "id": request_id, "result": result})


class _AcpTransportFactory:
    def __init__(self) -> None:
        self.transports: list[_ScriptedAcpTransport] = []

    def __call__(self):
        transport = _ScriptedAcpTransport(
            f"gemini-acp-{len(self.transports) + 1}", _initialize_fixture()
        )
        self.transports.append(transport)
        return transport


def _client(factory=None):
    factory = factory or _AcpTransportFactory()
    return (
        GeminiAcpPocClient(
            factory,
            cli_help=_help_fixture(),
            cli_version="0.46.0",
            adapter_version="0.1.0b1",
            request_timeout_seconds=1.0,
        ),
        factory,
    )


def _next_event(client, expected, *, timeout=1.0):
    deadline = time.monotonic() + timeout
    seen = []
    while time.monotonic() < deadline:
        event = client.next_event(timeout=deadline - time.monotonic())
        if event is None:
            break
        seen.append(event.type)
        if event.type == expected:
            return event
    raise AssertionError(f"event {expected!r} not found; saw {seen!r}")


def test_installed_046_initialize_fixture_freezes_only_proven_capabilities():
    handshake = probe_gemini_acp_handshake(
        cli_help=_help_fixture(),
        cli_version="0.46.0",
        adapter_version="0.1.0b1",
        result=_initialize_fixture(),
    )

    assert handshake.protocol_version == 1
    assert handshake.auth_method_ids == (
        "oauth-personal",
        "gemini-api-key",
        "vertex-ai",
        "gateway",
    )
    capabilities = handshake.capability_snapshot
    assert capabilities.protocol == "agent-client-protocol"
    assert capabilities.resume is True
    assert capabilities.recovery_after_process_loss is True
    assert capabilities.live_approvals is True
    assert capabilities.interrupt is True
    assert capabilities.dynamic_mcp is True
    assert capabilities.attachment_kinds == ("audio", "embedded-context", "image")
    assert capabilities.durable_approval is False
    assert capabilities.steer is False
    assert capabilities.fork is False
    assert capabilities.session_list is False
    assert capabilities.session_close is False
    assert capabilities.dynamic_model is False

    with pytest.raises(GeminiAcpPocError, match="does not advertise"):
        probe_gemini_acp_handshake(
            cli_help="gemini help without structured mode",
            cli_version="0.46.0",
            adapter_version="0.1.0b1",
            result=_initialize_fixture(),
        )
    mismatched = _initialize_fixture()
    mismatched["agentInfo"]["version"] = "0.47.0"
    with pytest.raises(GeminiAcpPocError, match="versions differ"):
        probe_gemini_acp_handshake(
            cli_help=_help_fixture(),
            cli_version="0.46.0",
            adapter_version="0.1.0b1",
            result=mismatched,
        )


def test_acp_session_prompt_permission_events_and_cancel_are_deterministic():
    client, factory = _client()
    client.start()
    _next_event(client, "process_started")
    client.initialize()
    client.authenticate("gemini-api-key", metadata={"api-key": "fixture-secret"})
    session_id = client.new_session(cwd="/fixture/worktree")
    assert session_id == "11111111-1111-4111-8111-111111111111"

    prompt = client.begin_prompt(turn_id="turn-1", text="prompt-canary")
    assert _next_event(client, "output_delta").payload["content"]["text"] == (
        "fixture output"
    )
    tool = _next_event(client, "tool_approval_pending")
    assert tool.payload["tool_call_id"] == "tool-1"
    assert "rawInput" not in tool.payload
    permission = client.next_permission(timeout=1.0)
    assert permission is not None
    with pytest.raises(GeminiAcpPocError, match="was not offered"):
        client.respond_permission(permission, option_id="invented")
    client.respond_permission(permission, option_id="proceed_once")
    completed = _next_event(client, "tool_completed")
    assert "rawOutput" not in completed.payload
    assert prompt.result(1.0) == {"stopReason": "end_turn"}
    permission_response = next(
        item for item in factory.transports[0].sent if item.get("id") == "permission-1"
    )
    assert permission_response["result"] == {
        "outcome": {"outcome": "selected", "optionId": "proceed_once"}
    }

    cancelled = client.begin_prompt(turn_id="turn-2", text="cancel-canary")
    client.cancel()
    assert cancelled.result(1.0) == {"stopReason": "cancelled"}
    assert factory.transports[0].sent[-1] == {
        "jsonrpc": "2.0",
        "method": "session/cancel",
        "params": {"sessionId": session_id},
    }
    client.close()


def test_process_loss_reinitializes_and_loads_exact_session_without_replay():
    client, factory = _client()
    client.start()
    _next_event(client, "process_started")
    client.initialize()
    client.authenticate("gateway", metadata={"gateway": {"baseUrl": "fixture"}})
    session_id = client.new_session(cwd="/fixture/worktree")

    factory.transports[0].lose()
    _next_event(client, "process_lost")
    assert (
        client.restart_and_load(
            session_id,
            cwd="/fixture/worktree",
            auth_method_id="gateway",
            auth_metadata={"gateway": {"baseUrl": "fixture"}},
        )
        == session_id
    )

    recovery_messages = factory.transports[1].sent
    assert [item.get("method") for item in recovery_messages] == [
        "initialize",
        "authenticate",
        "session/load",
    ]
    load_params = recovery_messages[-1]["params"]
    assert load_params == {
        "sessionId": session_id,
        "cwd": "/fixture/worktree",
        "mcpServers": [],
    }
    assert "prompt" not in json.dumps(recovery_messages)
    assert "auth_metadata" not in client.__dict__
    client.close()


def test_event_normalization_rejects_malformed_updates_and_bounds_state():
    event = normalize_gemini_acp_event(
        "session/update",
        {
            "sessionId": "session-1",
            "update": {
                "sessionUpdate": "available_commands_update",
                "availableCommands": [{"name": "private command"}],
            },
        },
    )
    assert event is not None
    assert event.type == "session_state"
    assert event.payload == {
        "session_id": "session-1",
        "kind": "available_commands_update",
    }
    with pytest.raises(GeminiAcpPocError, match="tool status"):
        normalize_gemini_acp_event(
            "session/update",
            {
                "sessionId": "session-1",
                "update": {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "tool-1",
                    "status": "future-status",
                },
            },
        )
