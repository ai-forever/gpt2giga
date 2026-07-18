from __future__ import annotations

import json
from pathlib import Path
import queue
import stat
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from gpt2giga_harness.execution import (
    EMPTY_EXTENSION_SNAPSHOT_HASH,
    ExecutionTransport,
    InteractionMode,
    ProviderRef,
    RouteRef,
    RuntimeOwnership,
    create_execution_snapshot,
)
from gpt2giga_harness.gemini_acp import (
    GEMINI_ACP_PERMISSION_METHOD,
    GeminiAcpDriver,
    GeminiAcpError,
    create_gemini_acp_stdio_scope,
)
from gpt2giga_harness.harnesses.gemini_cli import GeminiCliHarness
from gpt2giga_harness.structured_processes import (
    StructuredProcessState,
    StructuredTransportClosed,
)
from gpt2giga_harness.structured_sessions import (
    StructuredSessionConfigSnapshot,
    StructuredSessionCoordinator,
    StructuredSessionLinkStore,
    StructuredTurnInput,
    UnsupportedSessionCapability,
    structured_session_link_to_dict,
)
from gpt2giga_harness.types import HarnessContext, HarnessRequest
from gpt2giga_harness.workbench_execution import workbench_transport_projection


FIXTURE_ROOT = Path("tests/fixtures/harness_cli/gemini/0.46")
SESSION_ID = "11111111-1111-4111-8111-111111111111"
OTHER_SESSION_ID = "22222222-2222-4222-8222-222222222222"
_CLOSED = object()


def _initialize_fixture() -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / "acp_initialize.json").read_text())


def _help_fixture() -> str:
    return (FIXTURE_ROOT / "acp_help.txt").read_text()


class _ProductionAcpTransport:
    def __init__(
        self,
        runtime_id: str,
        *,
        session_id: str,
        request_filesystem: bool = False,
    ) -> None:
        self._runtime_id = runtime_id
        self.session_id = session_id
        self.request_filesystem = request_filesystem
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
            self._respond(request_id, _initialize_fixture())
        elif method == "authenticate":
            self._respond(request_id, {})
        elif method == "session/new":
            self._respond(request_id, {"sessionId": self.session_id})
        elif method == "session/load":
            self._respond(request_id, {})
        elif method == "session/prompt":
            self.prompt_ids.append(request_id)
            self._event(
                {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "fixture output"},
                }
            )
            if self.request_filesystem:
                self.incoming.put(
                    {
                        "jsonrpc": "2.0",
                        "id": "fs-1",
                        "method": "fs/read_text_file",
                        "params": {"sessionId": self.session_id, "path": "/private"},
                    }
                )
                self._respond(request_id, {"stopReason": "end_turn"})
            else:
                self._event(
                    {
                        "sessionUpdate": "tool_call",
                        "toolCallId": "tool-1",
                        "status": "pending",
                        "title": "Write fixture",
                        "rawInput": "must-not-be-normalized",
                    }
                )
                self.incoming.put(
                    {
                        "jsonrpc": "2.0",
                        "id": "permission-1",
                        "method": GEMINI_ACP_PERMISSION_METHOD,
                        "params": {
                            "sessionId": self.session_id,
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
                                "rawInput": "must-not-be-bridged",
                            },
                        },
                    }
                )
        elif method == "session/cancel":
            self._respond(self.prompt_ids[-1], {"stopReason": "cancelled"})
        elif message.get("id") == "permission-1" and "result" in message:
            self._event(
                {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "tool-1",
                    "status": "completed",
                    "rawOutput": "must-not-be-normalized",
                }
            )
            self._respond(self.prompt_ids[-1], {"stopReason": "end_turn"})

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

    def _event(self, update):
        self.incoming.put(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {"sessionId": self.session_id, "update": update},
            }
        )


class _TransportFactory:
    def __init__(
        self,
        *,
        session_id: str = SESSION_ID,
        request_filesystem: bool = False,
    ) -> None:
        self.session_id = session_id
        self.request_filesystem = request_filesystem
        self.transports: list[_ProductionAcpTransport] = []

    def __call__(self):
        transport = _ProductionAcpTransport(
            f"gemini-acp-production-{len(self.transports) + 1}",
            session_id=self.session_id,
            request_filesystem=self.request_filesystem,
        )
        self.transports.append(transport)
        return transport


def _driver(
    factory=None,
    *,
    mcp_provider=None,
    clock=None,
    idle_ttl_seconds=300.0,
):
    factory = factory or _TransportFactory()
    driver = GeminiAcpDriver(
        factory,
        cli_help=_help_fixture(),
        cli_version="0.46.0",
        adapter_version="0.1.0b1",
        cwd="/fixture/worktree",
        auth_provider=lambda: (
            "gateway",
            {"gateway": {"baseUrl": "fixture-secret-route"}},
        ),
        mcp_provider=mcp_provider,
        request_timeout_seconds=1.0,
        prompt_timeout_seconds=1.0,
        idle_ttl_seconds=idle_ttl_seconds,
        bridge_timeout_seconds=1.0,
        **({"clock": clock} if clock is not None else {}),
    )
    return driver, factory


def _execution():
    provider = ProviderRef("provider-gemini", "1")
    return create_execution_snapshot(
        provider=provider,
        route=RouteRef("route-gemini", "1", provider),
        harness_id="gemini-cli",
        harness_version="0.1.0b1",
        transport=ExecutionTransport.NATIVE_STRUCTURED,
        interaction_mode=InteractionMode.INTERACTIVE,
        runtime_ownership=RuntimeOwnership.DURABLE,
        workspace_id="workspace-fixture",
        worktree_id="worktree-fixture",
        permission_profile="workspace-write",
        extension_snapshot_hash=EMPTY_EXTENSION_SNAPSHOT_HASH,
    )


def _config(managed_home_id="gemini-acp-home-fixture"):
    return StructuredSessionConfigSnapshot(
        adapter_id="gemini-cli",
        adapter_version="0.1.0b1",
        protocol="agent-client-protocol",
        protocol_version="1",
        cli_sdk_version="0.46.0",
        managed_home_id=managed_home_id,
    )


def test_production_driver_maps_uuid_and_permission_through_generic_coordinator(
    tmp_path,
):
    driver, factory = _driver()
    store = StructuredSessionLinkStore(tmp_path)
    coordinator = StructuredSessionCoordinator(
        driver, store, owner_id="gemini-worker-1"
    )
    link = coordinator.open_or_resume(
        link_id="gemini-link-1",
        harness_session_id="harness-session-1",
        harness_run_id="harness-run-1",
        execution_snapshot=_execution(),
        config_snapshot=_config(),
    )
    events = []
    approvals = []

    def approve(contract):
        approvals.append(contract)
        return "allow"

    link, result = coordinator.start_turn(
        link,
        StructuredTurnInput("turn-fixture-1", "prompt-canary"),
        events.append,
        approve,
    )

    assert link.external_session_id == SESSION_ID
    assert result.status == "completed"
    assert link.latest_external_turn_id == result.external_turn_id
    assert approvals[0]["session_id"] == SESSION_ID
    assert approvals[0]["tool_call_id"] == "tool-1"
    assert approvals[0]["options"] == [
        {"option_id": "proceed_once", "kind": "allow_once"},
        {"option_id": "cancel", "kind": "reject_once"},
    ]
    assert "rawInput" not in json.dumps(approvals)
    assert any(event["type"] == "output_delta" for event in events)
    assert any(event["type"] == "tool_completed" for event in events)
    permission_response = next(
        item for item in factory.transports[0].sent if item.get("id") == "permission-1"
    )
    assert permission_response["result"] == {
        "outcome": {"outcome": "selected", "optionId": "proceed_once"}
    }
    payload = structured_session_link_to_dict(link)
    encoded = json.dumps(payload)
    assert "prompt-canary" not in encoded
    assert "fixture-secret-route" not in encoded
    assert {item["id"] for item in payload["degradation_evidence"]} == {
        "gemini-acp-elicitation",
        "gemini-acp-filesystem-client",
        "gemini-acp-model-switch",
        "gemini-acp-session-close",
        "gemini-acp-session-list",
    }
    assert link.capability_snapshot.session_close is False
    assert link.capability_snapshot.session_list is False
    assert link.capability_snapshot.dynamic_model is False
    assert link.capability_snapshot.interactive_input is False
    driver.close()


def test_session_scopes_get_distinct_private_homes_and_fresh_runtime_ids(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    first = create_gemini_acp_stdio_scope(
        command=("gemini",),
        env={"PATH": "/fixture/bin", "SECRET": "ephemeral"},
        workspace=workspace,
        data_dir=tmp_path / "state",
        scope_id="harness-session-1",
    )
    second = create_gemini_acp_stdio_scope(
        command=("gemini",),
        env={"PATH": "/fixture/bin", "SECRET": "ephemeral"},
        workspace=workspace,
        data_dir=tmp_path / "state",
        scope_id="harness-session-2",
    )

    assert first.managed_home != second.managed_home
    assert first.managed_home_id != second.managed_home_id
    assert stat.S_IMODE(first.managed_home.stat().st_mode) == 0o700
    first_transport = first.transport_factory()
    recycled_transport = first.transport_factory()
    second_transport = second.transport_factory()
    assert (
        len(
            {
                first_transport.runtime_id,
                recycled_transport.runtime_id,
                second_transport.runtime_id,
            }
        )
        == 3
    )
    assert first_transport._env["HOME"] == str(first.managed_home)
    assert second_transport._env["HOME"] == str(second.managed_home)
    assert first_transport._command[-1] == "--acp"


def test_builtin_adapter_registers_probed_product_driver_without_runtime_admission(
    tmp_path,
    monkeypatch,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    harness = GeminiCliHarness()
    monkeypatch.setattr(
        harness,
        "capability_probe",
        lambda: SimpleNamespace(
            compatible=True,
            capabilities={"--acp": True},
            parsed_version="0.46.0",
        ),
    )
    monkeypatch.setattr(
        harness,
        "executable_resolution",
        lambda: SimpleNamespace(command=("gemini",)),
    )

    driver, scope = harness.create_acp_driver(
        HarnessRequest(prompt="ephemeral", workspace=str(workspace)),
        HarnessContext(
            proxy_url="http://127.0.0.1:8090",
            data_dir=str(tmp_path / "state"),
        ),
        scope_id="harness-session-registered",
        auth_provider=lambda: ("gateway", None),
    )

    assert driver.cli_version == "0.46.0"
    assert driver.cwd == str(workspace)
    assert scope.managed_home_id.startswith("gemini-acp-")
    assert driver.supervisor.state is StructuredProcessState.NEW


def test_unavailable_cli_projects_blocked_structured_transport(monkeypatch):
    harness = GeminiCliHarness()
    monkeypatch.setattr(
        harness,
        "capability_probe",
        lambda: SimpleNamespace(
            compatible=False,
            capabilities={},
            parsed_version=None,
        ),
    )

    projection = workbench_transport_projection(harness)

    assert projection["default"] == "native_structured"
    structured = projection["options"][0]
    assert structured["status"] == "blocked"
    assert structured["blocker"] == "structured_driver_unavailable"
    assert structured["provider_native_continuity"] is False


def test_idle_recycle_reauthenticates_and_loads_exact_uuid_without_replay(tmp_path):
    now = [100.0]
    driver, factory = _driver(clock=lambda: now[0], idle_ttl_seconds=5.0)
    coordinator = StructuredSessionCoordinator(
        driver,
        StructuredSessionLinkStore(tmp_path),
        owner_id="gemini-worker-1",
    )
    link = coordinator.open_or_resume(
        link_id="gemini-link-1",
        harness_session_id="harness-session-1",
        harness_run_id="harness-run-1",
        execution_snapshot=_execution(),
        config_snapshot=_config(),
    )
    now[0] = 106.0

    assert driver.recycle_if_idle() is True
    assert driver.supervisor.state is StructuredProcessState.STOPPED
    state = driver.open_or_resume(_execution(), link)

    assert state.external_session_id == SESSION_ID
    assert len(factory.transports) == 2
    recovery = factory.transports[1].sent
    assert [message.get("method") for message in recovery] == [
        "initialize",
        "authenticate",
        "session/load",
    ]
    assert recovery[-1]["params"]["sessionId"] == SESSION_ID
    assert "prompt" not in json.dumps(recovery)
    assert not hasattr(driver, "auth_metadata")
    driver.close()


def test_mcp_transports_are_probe_bound_and_filesystem_requests_fail_closed():
    def mcp():
        return ({"name": "reviewed-http", "type": "http", "url": "http://fixture"},)

    driver, factory = _driver(mcp_provider=mcp)
    state = driver.open_or_resume(_execution(), None)

    assert state.external_session_id == SESSION_ID
    new_request = next(
        message
        for message in factory.transports[0].sent
        if message.get("method") == "session/new"
    )
    assert new_request["params"]["mcpServers"] == list(mcp())
    driver.close()

    unsupported, _ = _driver(mcp_provider=lambda: ({"name": "local", "type": "stdio"},))
    with pytest.raises(UnsupportedSessionCapability, match="was not advertised"):
        unsupported.open_or_resume(_execution(), None)
    unsupported.close()

    fs_factory = _TransportFactory(request_filesystem=True)
    fs_driver, _ = _driver(fs_factory)
    fs_driver.open_or_resume(_execution(), None)
    result = fs_driver.start_turn(
        StructuredTurnInput("turn-fs", "read outside scope"),
        lambda event: None,
        lambda contract: "deny",
    )
    assert result.status == "completed"
    fs_error = next(
        message
        for message in fs_factory.transports[0].sent
        if message.get("id") == "fs-1"
    )
    assert fs_error["error"]["code"] == -32601
    initialize = next(
        message
        for message in fs_factory.transports[0].sent
        if message.get("method") == "initialize"
    )
    assert initialize["params"]["clientCapabilities"]["fs"] == {
        "readTextFile": False,
        "writeTextFile": False,
    }
    with pytest.raises(UnsupportedSessionCapability, match="elicitation"):
        fs_driver.respond_to_input("input-1", "answer")
    fs_driver.close()


def test_noncanonical_or_cross_session_uuid_fails_closed():
    non_uuid_factory = _TransportFactory(session_id="not-a-uuid")
    driver, _ = _driver(non_uuid_factory)
    with pytest.raises(GeminiAcpError, match="session id is invalid"):
        driver.open_or_resume(_execution(), None)
    driver.close()

    factory = _TransportFactory(session_id=OTHER_SESSION_ID)
    driver, _ = _driver(factory)
    driver.open_or_resume(_execution(), None)
    factory.transports[0].session_id = SESSION_ID
    with pytest.raises(GeminiAcpError, match="session UUID does not match"):
        driver.start_turn(
            StructuredTurnInput("turn-cross-session", "prompt"),
            lambda event: None,
            lambda contract: "deny",
        )
    driver.close()
