"""Production Gemini ACP structured-session driver."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Callable, Mapping, Sequence
from uuid import UUID

from gpt2giga_harness.execution import ExecutionSnapshot, SnapshotEvidenceRef
from gpt2giga_harness.structured_processes import (
    NormalizedStructuredEvent,
    StdioJsonRpcTransport,
    StructuredBridgeKind,
    StructuredBridgeRequest,
    StructuredProcessState,
    StructuredProcessSupervisor,
    StructuredRequestHandle,
    StructuredTransport,
)
from gpt2giga_harness.structured_sessions import (
    AdapterCapabilitySnapshot,
    StructuredSessionError,
    StructuredSessionLink,
    StructuredSessionState,
    StructuredTurnInput,
    StructuredTurnResult,
    UnsupportedSessionCapability,
)


GEMINI_ACP_PROTOCOL = "agent-client-protocol"
GEMINI_ACP_PROTOCOL_VERSION = 1
GEMINI_ACP_PERMISSION_METHOD = "session/request_permission"
_IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@+~-]{0,255}\Z")
_MCP_TRANSPORTS = frozenset({"http", "sse"})
_ALLOW_KINDS = ("allow_once", "allow_always")
_REJECT_KINDS = ("reject_once", "reject_always")


class GeminiAcpError(StructuredSessionError):
    """Raised when the reviewed Gemini ACP contract is violated."""


@dataclass(frozen=True)
class GeminiAcpHandshake:
    """Content-free reviewed projection of one ACP initialize response."""

    cli_version: str
    protocol_version: int
    auth_method_ids: tuple[str, ...]
    mcp_transports: tuple[str, ...]
    capability_snapshot: AdapterCapabilitySnapshot


@dataclass(frozen=True)
class GeminiAcpStdioScope:
    """One session-scoped private HOME and fresh-process transport factory."""

    scope_id: str
    managed_home: Path
    managed_home_id: str
    transport_factory: Callable[[], StructuredTransport] = field(
        repr=False,
        compare=False,
    )


AuthProvider = Callable[[], tuple[str, Mapping[str, Any] | None]]
McpProvider = Callable[[], Sequence[Mapping[str, Any]]]
Clock = Callable[[], float]


def probe_gemini_acp_handshake(
    *,
    cli_help: str,
    cli_version: str,
    adapter_version: str,
    result: Mapping[str, Any],
) -> GeminiAcpHandshake:
    """Validate installed help/initialize evidence and freeze reviewed claims."""
    if not isinstance(cli_help, str) or not re.search(
        r"(?:^|\s)--acp(?:\s|$)", cli_help
    ):
        raise GeminiAcpError("installed Gemini CLI does not advertise --acp")
    _validate_identity(cli_version, field_name="Gemini CLI version")
    _validate_identity(adapter_version, field_name="adapter version")
    if not isinstance(result, Mapping):
        raise GeminiAcpError("ACP initialize result must be an object")
    protocol_version = result.get("protocolVersion")
    if protocol_version != GEMINI_ACP_PROTOCOL_VERSION:
        raise GeminiAcpError("Gemini ACP protocol version is not reviewed")
    agent_info = _mapping(result.get("agentInfo"), field_name="agentInfo")
    if agent_info.get("name") != "gemini-cli":
        raise GeminiAcpError("ACP agent identity is not Gemini CLI")
    if agent_info.get("version") != cli_version:
        raise GeminiAcpError("Gemini help and ACP versions differ")

    raw_auth_methods = result.get("authMethods")
    if not isinstance(raw_auth_methods, Sequence) or isinstance(
        raw_auth_methods, (str, bytes)
    ):
        raise GeminiAcpError("ACP authMethods must be an array")
    auth_method_ids: list[str] = []
    for item in raw_auth_methods:
        method = _mapping(item, field_name="auth method")
        method_id = method.get("id")
        _validate_identity(method_id, field_name="auth method id")
        auth_method_ids.append(method_id)
    if not auth_method_ids or len(set(auth_method_ids)) != len(auth_method_ids):
        raise GeminiAcpError("ACP auth method identities are empty or duplicated")

    capabilities = _mapping(
        result.get("agentCapabilities"), field_name="agentCapabilities"
    )
    prompt_capabilities = _mapping(
        capabilities.get("promptCapabilities", {}),
        field_name="promptCapabilities",
    )
    mcp_capabilities = _mapping(
        capabilities.get("mcpCapabilities", {}),
        field_name="mcpCapabilities",
    )
    load_session = capabilities.get("loadSession") is True
    attachment_kinds = tuple(
        name
        for name, enabled in (
            ("audio", prompt_capabilities.get("audio") is True),
            ("embedded-context", prompt_capabilities.get("embeddedContext") is True),
            ("image", prompt_capabilities.get("image") is True),
        )
        if enabled
    )
    mcp_transports = tuple(
        name for name in sorted(_MCP_TRANSPORTS) if mcp_capabilities.get(name) is True
    )
    snapshot = AdapterCapabilitySnapshot(
        adapter_id="gemini-cli",
        adapter_version=adapter_version,
        protocol=GEMINI_ACP_PROTOCOL,
        protocol_version=str(protocol_version),
        structured_events=True,
        partial_output=True,
        interactive_input=False,
        live_approvals=True,
        durable_approval=False,
        interrupt=True,
        steer=False,
        resume=load_session,
        fork=False,
        session_list=False,
        session_close=False,
        native_auth=True,
        provider_ui_handoff=False,
        dynamic_model=False,
        dynamic_mcp=bool(mcp_transports),
        recovery_after_process_loss=load_session,
        attachment_kinds=attachment_kinds,
        attachment_transports=("acp-inline", "acp-resource"),
    )
    return GeminiAcpHandshake(
        cli_version=cli_version,
        protocol_version=protocol_version,
        auth_method_ids=tuple(auth_method_ids),
        mcp_transports=mcp_transports,
        capability_snapshot=snapshot,
    )


def create_gemini_acp_stdio_scope(
    *,
    command: Sequence[str],
    env: Mapping[str, str],
    workspace: str | Path,
    data_dir: str | Path,
    scope_id: str,
) -> GeminiAcpStdioScope:
    """Create one isolated Gemini ACP process scope without using the real HOME."""
    _validate_identity(scope_id, field_name="ACP scope id")
    command_tuple = tuple(command)
    if not command_tuple or any(
        not isinstance(item, str) or not item for item in command_tuple
    ):
        raise ValueError("Gemini ACP command is invalid")
    workspace_path = Path(workspace).expanduser().resolve()
    if not workspace_path.is_dir():
        raise ValueError("Gemini ACP workspace must be an existing directory")
    root = (
        Path(data_dir).expanduser().resolve()
        / "structured_sessions"
        / "gemini_acp"
        / "homes"
    )
    scope_hash = hashlib.sha256(scope_id.encode("utf-8")).hexdigest()
    managed_home = root / scope_hash
    if managed_home.is_symlink():
        raise GeminiAcpError("Gemini ACP managed HOME cannot be a symlink")
    managed_home.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not managed_home.is_dir():
        raise GeminiAcpError("Gemini ACP managed HOME is not a directory")
    os.chmod(managed_home, 0o700)
    safe_env = _string_mapping(env, field_name="Gemini ACP environment")
    safe_env["HOME"] = str(managed_home)
    acp_command = (
        command_tuple if "--acp" in command_tuple else (*command_tuple, "--acp")
    )
    counter = 0
    counter_lock = threading.Lock()

    def transport_factory() -> StructuredTransport:
        nonlocal counter
        with counter_lock:
            counter += 1
            generation = counter
        return StdioJsonRpcTransport(
            command=acp_command,
            runtime_id=f"gemini-acp-{scope_hash[:16]}-{generation}",
            env=safe_env,
            cwd=str(workspace_path),
        )

    return GeminiAcpStdioScope(
        scope_id=scope_id,
        managed_home=managed_home,
        managed_home_id=f"gemini-acp-{scope_hash[:24]}",
        transport_factory=transport_factory,
    )


class GeminiAcpDriver:
    """Operate one Gemini ACP session through an isolated supervised process."""

    def __init__(
        self,
        transport_factory: Callable[[], StructuredTransport],
        *,
        cli_help: str,
        cli_version: str,
        adapter_version: str,
        cwd: str,
        auth_provider: AuthProvider,
        mcp_provider: McpProvider | None = None,
        request_timeout_seconds: float = 5.0,
        prompt_timeout_seconds: float = 300.0,
        idle_ttl_seconds: float = 300.0,
        bridge_timeout_seconds: float = 30.0,
        clock: Clock = time.monotonic,
    ) -> None:
        for name, value in (
            ("request_timeout_seconds", request_timeout_seconds),
            ("prompt_timeout_seconds", prompt_timeout_seconds),
            ("idle_ttl_seconds", idle_ttl_seconds),
            ("bridge_timeout_seconds", bridge_timeout_seconds),
        ):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"{name} must be numeric")
            if value <= 0 or not math.isfinite(value):
                raise ValueError(f"{name} must be finite and positive")
        self.cli_help = cli_help
        self.cli_version = cli_version
        self.adapter_version = adapter_version
        self.cwd = _require_text(cwd, field_name="cwd")
        self.auth_provider = auth_provider
        self.mcp_provider = mcp_provider or (lambda: ())
        self.request_timeout_seconds = float(request_timeout_seconds)
        self.prompt_timeout_seconds = float(prompt_timeout_seconds)
        self.idle_ttl_seconds = float(idle_ttl_seconds)
        self.clock = clock
        self.supervisor = StructuredProcessSupervisor(
            transport_factory,
            event_normalizer=normalize_gemini_acp_event,
            approval_methods=frozenset({GEMINI_ACP_PERMISSION_METHOD}),
            bridge_timeout_seconds=bridge_timeout_seconds,
        )
        self.handshake: GeminiAcpHandshake | None = None
        self.session_id: str | None = None
        self.active_turn_id: str | None = None
        self._last_activity = self.clock()
        self._pending_permissions: dict[str, StructuredBridgeRequest] = {}
        self._permission_lock = threading.Lock()

    def probe(self) -> AdapterCapabilitySnapshot:
        """Return capabilities proven by the current installed ACP handshake."""
        return self._ensure_ready().capability_snapshot

    def open_or_resume(
        self,
        execution_snapshot: ExecutionSnapshot,
        session_link: StructuredSessionLink | None,
    ) -> StructuredSessionState:
        """Open a new UUID session or load the exact linked UUID without replay."""
        del execution_snapshot
        handshake = self._ensure_ready()
        mcp_servers = self._mcp_servers(handshake)
        if session_link is None:
            result = self.supervisor.request(
                "session/new",
                {"cwd": self.cwd, "mcpServers": mcp_servers},
                timeout=self.request_timeout_seconds,
            )
            session_id = _canonical_uuid(
                result.get("sessionId"), field_name="ACP session id"
            )
        else:
            if not handshake.capability_snapshot.resume:
                raise UnsupportedSessionCapability(
                    "Gemini ACP loadSession is unsupported"
                )
            session_id = _canonical_uuid(
                session_link.external_session_id,
                field_name="ACP linked session id",
            )
            self.supervisor.request(
                "session/load",
                {
                    "sessionId": session_id,
                    "cwd": self.cwd,
                    "mcpServers": mcp_servers,
                },
                timeout=self.request_timeout_seconds,
            )
        self.session_id = session_id
        self._touch()
        return StructuredSessionState(
            session_id,
            session_link.latest_external_turn_id if session_link is not None else None,
            _degradation_evidence(self.cli_version),
        )

    def start_turn(
        self,
        turn_input: StructuredTurnInput,
        event_sink: Callable[[Mapping[str, Any]], None],
        approval_bridge: Callable[[Mapping[str, Any]], str],
    ) -> StructuredTurnResult:
        """Run one ACP prompt while servicing permission requests and events."""
        session_id = self._require_session()
        if self.active_turn_id is not None:
            raise GeminiAcpError("Gemini ACP already has an active turn")
        handle = self.supervisor.begin_request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": turn_input.content}],
            },
        )
        turn_id = handle.id
        self.active_turn_id = turn_id
        deadline = self.clock() + self.prompt_timeout_seconds
        try:
            while not handle.done:
                remaining = deadline - self.clock()
                if remaining <= 0:
                    self.supervisor.notify("session/cancel", {"sessionId": session_id})
                    return self._finish_timed_out(handle, turn_id)
                wait = min(remaining, 0.05)
                permission = self.supervisor.next_bridge_request(timeout=wait / 2)
                if permission is not None:
                    self._bridge_permission(permission, approval_bridge)
                event = self.supervisor.next_event(timeout=wait / 2)
                if event is not None:
                    self._publish_event(event, event_sink)
            result = handle.result(0.001)
            self._drain_events(event_sink)
            stop_reason = result.get("stopReason")
            status = _turn_status(stop_reason)
            self._touch()
            return StructuredTurnResult(turn_id, status)
        finally:
            self.active_turn_id = None

    def respond_to_input(self, request_id: str, answer: str) -> None:
        """Reject general elicitation because only permission requests are proven."""
        del request_id, answer
        raise UnsupportedSessionCapability("Gemini ACP elicitation is unsupported")

    def respond_to_approval(self, request_id: str, decision: str) -> None:
        """Respond to one exact live permission request from another caller."""
        with self._permission_lock:
            request = self._pending_permissions.pop(request_id, None)
        if request is None:
            raise GeminiAcpError("Gemini ACP permission request is stale or unknown")
        self._respond_permission(request, decision)

    def interrupt(self, turn_id: str) -> None:
        """Cancel only the exact active ACP session prompt."""
        if turn_id != self.active_turn_id:
            raise GeminiAcpError("Gemini ACP turn is not active")
        self.supervisor.notify("session/cancel", {"sessionId": self._require_session()})
        self._touch()

    def recover(self, session_link: StructuredSessionLink) -> StructuredSessionState:
        """Start a fresh generation and load the exact UUID without prompt replay."""
        session_id = _canonical_uuid(
            session_link.external_session_id,
            field_name="ACP linked session id",
        )
        handshake = self._restart_ready()
        if not handshake.capability_snapshot.recovery_after_process_loss:
            raise UnsupportedSessionCapability("Gemini ACP recovery is unsupported")
        self.supervisor.request(
            "session/load",
            {
                "sessionId": session_id,
                "cwd": self.cwd,
                "mcpServers": self._mcp_servers(handshake),
            },
            timeout=self.request_timeout_seconds,
        )
        self.session_id = session_id
        self._touch()
        return StructuredSessionState(
            session_id,
            session_link.latest_external_turn_id,
            _degradation_evidence(self.cli_version),
        )

    def recycle_if_idle(self) -> bool:
        """Recycle an inactive process after its bounded idle TTL."""
        if self.active_turn_id is not None:
            return False
        if self.supervisor.state is not StructuredProcessState.RUNNING:
            return False
        if self.clock() - self._last_activity < self.idle_ttl_seconds:
            return False
        self.supervisor.close()
        self.handshake = None
        self.session_id = None
        return True

    def close(self) -> None:
        """Stop process resources without claiming provider session-close support."""
        self.supervisor.close()
        self.handshake = None
        self.session_id = None
        self.active_turn_id = None

    def _ensure_ready(self) -> GeminiAcpHandshake:
        if self.supervisor.state is StructuredProcessState.NEW:
            self.supervisor.start()
        elif self.supervisor.state in {
            StructuredProcessState.LOST,
            StructuredProcessState.STOPPED,
        }:
            self.supervisor.restart()
        if self.handshake is None:
            self.handshake = self._initialize_and_authenticate()
        return self.handshake

    def _restart_ready(self) -> GeminiAcpHandshake:
        state = self.supervisor.state
        if state is StructuredProcessState.RUNNING:
            self.supervisor.close()
        self.handshake = None
        self.session_id = None
        return self._ensure_ready()

    def _initialize_and_authenticate(self) -> GeminiAcpHandshake:
        result = self.supervisor.request(
            "initialize",
            {
                "protocolVersion": GEMINI_ACP_PROTOCOL_VERSION,
                "clientInfo": {
                    "name": "gpt2giga-harness",
                    "version": self.adapter_version,
                },
                "clientCapabilities": {
                    "auth": {"terminal": False},
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                },
            },
            timeout=self.request_timeout_seconds,
        )
        handshake = probe_gemini_acp_handshake(
            cli_help=self.cli_help,
            cli_version=self.cli_version,
            adapter_version=self.adapter_version,
            result=result,
        )
        method_id, metadata = self.auth_provider()
        if method_id not in handshake.auth_method_ids:
            raise GeminiAcpError("ACP auth method was not advertised")
        params: dict[str, Any] = {"methodId": method_id}
        if metadata is not None:
            if not isinstance(metadata, Mapping):
                raise ValueError("ACP auth metadata must be a mapping")
            params["_meta"] = dict(metadata)
        self.supervisor.request(
            "authenticate", params, timeout=self.request_timeout_seconds
        )
        self._touch()
        return handshake

    def _mcp_servers(self, handshake: GeminiAcpHandshake) -> list[dict[str, Any]]:
        raw = self.mcp_provider()
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise ValueError("Gemini ACP MCP provider must return a sequence")
        servers: list[dict[str, Any]] = []
        names: set[str] = set()
        for item in raw:
            server = _json_mapping(item, field_name="Gemini ACP MCP server")
            name = server.get("name")
            _validate_identity(name, field_name="Gemini ACP MCP server name")
            if name in names:
                raise GeminiAcpError("Gemini ACP MCP server names are duplicated")
            names.add(name)
            transport = server.get("type")
            if transport not in handshake.mcp_transports:
                raise UnsupportedSessionCapability(
                    "Gemini ACP MCP transport was not advertised"
                )
            servers.append(server)
        return servers

    def _bridge_permission(
        self,
        request: StructuredBridgeRequest,
        approval_bridge: Callable[[Mapping[str, Any]], str],
    ) -> None:
        if request.kind is not StructuredBridgeKind.APPROVAL:
            raise GeminiAcpError("unexpected Gemini ACP bridge kind")
        key = str(request.id)
        contract = _approval_contract(
            request,
            session_id=self._require_session(),
            turn_id=self.active_turn_id,
        )
        with self._permission_lock:
            self._pending_permissions[key] = request
        try:
            decision = approval_bridge(contract)
            with self._permission_lock:
                pending = self._pending_permissions.pop(key, None)
            if pending is not None:
                self._respond_permission(pending, decision)
        except Exception:
            with self._permission_lock:
                pending = self._pending_permissions.pop(key, None)
            if pending is not None:
                self._respond_permission(pending, "deny")
            raise

    def _respond_permission(
        self,
        request: StructuredBridgeRequest,
        decision: str,
    ) -> None:
        option_id = _permission_option(request.params, decision)
        outcome: Mapping[str, Any]
        if option_id is None:
            outcome = {"outcome": "cancelled"}
        else:
            outcome = {"outcome": "selected", "optionId": option_id}
        self.supervisor.respond_bridge(
            request.id,
            generation=request.generation,
            result={"outcome": outcome},
        )
        self._touch()

    def _publish_event(
        self,
        event: NormalizedStructuredEvent,
        event_sink: Callable[[Mapping[str, Any]], None],
    ) -> None:
        event_session_id = event.payload.get("session_id")
        if event_session_id is not None and event_session_id != self._require_session():
            raise GeminiAcpError("Gemini ACP event session UUID does not match")
        event_sink(
            {
                "type": event.type,
                "payload": dict(event.payload),
                "generation": event.generation,
                "synthetic": event.synthetic,
            }
        )

    def _drain_events(self, event_sink: Callable[[Mapping[str, Any]], None]) -> None:
        while (event := self.supervisor.next_event(timeout=0.0)) is not None:
            self._publish_event(event, event_sink)

    def _finish_timed_out(
        self,
        handle: StructuredRequestHandle,
        turn_id: str,
    ) -> StructuredTurnResult:
        try:
            result = handle.result(self.request_timeout_seconds)
        except Exception as exc:
            raise GeminiAcpError("Gemini ACP prompt timed out") from exc
        self._touch()
        return StructuredTurnResult(turn_id, _turn_status(result.get("stopReason")))

    def _require_session(self) -> str:
        if self.session_id is None:
            raise GeminiAcpError("Gemini ACP session is not open")
        return self.session_id

    def _touch(self) -> None:
        self._last_activity = self.clock()


def normalize_gemini_acp_event(
    method: str, params: Mapping[str, Any]
) -> NormalizedStructuredEvent | None:
    """Normalize reviewed ACP updates without retaining raw tool input/output."""
    if method != "session/update":
        return None
    session_id = _canonical_uuid(
        params.get("sessionId"), field_name="ACP event session id"
    )
    update = _mapping(params.get("update"), field_name="ACP session update")
    kind = update.get("sessionUpdate")
    if not isinstance(kind, str) or not kind:
        raise GeminiAcpError("ACP session update kind is invalid")
    if kind in {"agent_message_chunk", "agent_thought_chunk", "user_message_chunk"}:
        content = _mapping(update.get("content"), field_name="ACP message content")
        event_type = {
            "agent_message_chunk": "output_delta",
            "agent_thought_chunk": "reasoning_delta",
            "user_message_chunk": "input_echo",
        }[kind]
        return NormalizedStructuredEvent(
            type=event_type,
            payload={"session_id": session_id, "content": dict(content)},
        )
    if kind in {"tool_call", "tool_call_update"}:
        tool_call_id = update.get("toolCallId")
        _validate_identity(tool_call_id, field_name="ACP tool call id")
        status = update.get("status")
        if status not in {None, "pending", "in_progress", "completed", "failed"}:
            raise GeminiAcpError("ACP tool status is invalid")
        event_type = {
            "pending": "tool_approval_pending",
            "in_progress": "tool_started",
            "completed": "tool_completed",
            "failed": "tool_failed",
            None: "tool_updated",
        }[status]
        payload = {
            "session_id": session_id,
            "tool_call_id": tool_call_id,
            "status": status,
        }
        for field_name in ("title", "kind", "content", "locations"):
            if field_name in update:
                payload[field_name] = update[field_name]
        return NormalizedStructuredEvent(type=event_type, payload=payload)
    if kind == "plan":
        entries = update.get("entries")
        if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
            raise GeminiAcpError("ACP plan entries are invalid")
        return NormalizedStructuredEvent(
            type="plan_update",
            payload={"session_id": session_id, "entries": list(entries)},
        )
    if kind == "usage_update":
        return NormalizedStructuredEvent(
            type="usage_update",
            payload={
                "session_id": session_id,
                "used": update.get("used"),
                "size": update.get("size"),
            },
        )
    return NormalizedStructuredEvent(
        type="session_state", payload={"session_id": session_id, "kind": kind}
    )


def _approval_contract(
    request: StructuredBridgeRequest,
    *,
    session_id: str,
    turn_id: str | None,
) -> dict[str, Any]:
    if request.method != GEMINI_ACP_PERMISSION_METHOD:
        raise GeminiAcpError("unexpected Gemini ACP permission method")
    request_session_id = _canonical_uuid(
        request.params.get("sessionId"), field_name="ACP permission session id"
    )
    if request_session_id != session_id:
        raise GeminiAcpError("Gemini ACP permission session UUID does not match")
    options = _permission_options(request.params)
    tool_call = _mapping(
        request.params.get("toolCall", {}), field_name="ACP permission toolCall"
    )
    tool_call_id = tool_call.get("toolCallId")
    _validate_identity(tool_call_id, field_name="ACP permission tool call id")
    safe_options = [
        {"option_id": option_id, "kind": kind} for option_id, kind in options
    ]
    binding = {
        "protocol": GEMINI_ACP_PROTOCOL,
        "method": request.method,
        "provider_request_id": str(request.id),
        "session_id": session_id,
        "turn_id": turn_id,
        "tool_call_id": tool_call_id,
        "options": safe_options,
    }
    return {
        **binding,
        "binding_hash": hashlib.sha256(
            json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def _permission_options(params: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    raw_options = params.get("options")
    if not isinstance(raw_options, Sequence) or isinstance(raw_options, (str, bytes)):
        raise GeminiAcpError("ACP permission options are invalid")
    options: list[tuple[str, str]] = []
    for item in raw_options:
        option = _mapping(item, field_name="ACP permission option")
        option_id = option.get("optionId")
        kind = option.get("kind")
        _validate_identity(option_id, field_name="ACP permission option id")
        _validate_identity(kind, field_name="ACP permission option kind")
        options.append((option_id, kind))
    option_ids = [option_id for option_id, _ in options]
    if not options or len(set(option_ids)) != len(option_ids):
        raise GeminiAcpError("ACP permission options are empty or duplicated")
    return tuple(options)


def _permission_option(params: Mapping[str, Any], decision: str) -> str | None:
    options = _permission_options(params)
    exact = str(decision).strip()
    option_ids = {option_id for option_id, _ in options}
    if exact in option_ids:
        return exact
    normalized = exact.lower().replace("-", "_")
    kinds = (
        _ALLOW_KINDS
        if normalized in {"accept", "allow", "allow_once"}
        else _REJECT_KINDS
    )
    if normalized not in {
        "accept",
        "allow",
        "allow_once",
        "deny",
        "reject",
        "cancel",
    }:
        raise GeminiAcpError("Gemini ACP approval decision is invalid")
    for wanted in kinds:
        for option_id, kind in options:
            if kind == wanted:
                return option_id
    return None


def _degradation_evidence(cli_version: str) -> tuple[SnapshotEvidenceRef, ...]:
    return tuple(
        SnapshotEvidenceRef(
            id=f"gemini-acp-{capability}",
            revision=cli_version,
            status="unsupported",
            source="acp-initialize",
        )
        for capability in (
            "elicitation",
            "filesystem-client",
            "model-switch",
            "session-close",
            "session-list",
        )
    )


def _turn_status(value: Any) -> str:
    if value is None:
        return "completed"
    _validate_identity(value, field_name="ACP stop reason")
    return {
        "end_turn": "completed",
        "cancelled": "interrupted",
    }.get(value, value)


def _canonical_uuid(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise GeminiAcpError(f"{field_name} is invalid")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise GeminiAcpError(f"{field_name} is invalid") from exc
    canonical = str(parsed)
    if value.lower() != canonical:
        raise GeminiAcpError(f"{field_name} must be a canonical UUID")
    return canonical


def _mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GeminiAcpError(f"{field_name} must be an object")
    return value


def _require_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} is required")
    return value


def _validate_identity(value: Any, *, field_name: str) -> None:
    if not isinstance(value, str) or _IDENTITY_RE.fullmatch(value) is None:
        raise GeminiAcpError(f"{field_name} is invalid")


def _string_mapping(value: Mapping[str, str], *, field_name: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) or not isinstance(item, str)
        for key, item in value.items()
    ):
        raise ValueError(f"{field_name} must contain strings")
    return dict(value)


def _json_mapping(value: Any, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping")
    try:
        encoded = json.dumps(value, allow_nan=False, separators=(",", ":"))
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be JSON-compatible") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"{field_name} must be a mapping")
    return decoded
