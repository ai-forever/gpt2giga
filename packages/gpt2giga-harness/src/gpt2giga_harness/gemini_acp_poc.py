"""Hermetic Gemini ACP proof of concept over the structured-process seam."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable, Mapping, Sequence

from gpt2giga_harness.structured_processes import (
    NormalizedStructuredEvent,
    StructuredBridgeKind,
    StructuredBridgeRequest,
    StructuredProcessSupervisor,
    StructuredRequestHandle,
    StructuredTransport,
)
from gpt2giga_harness.structured_sessions import AdapterCapabilitySnapshot


GEMINI_ACP_PROTOCOL = "agent-client-protocol"
GEMINI_ACP_PROTOCOL_VERSION = 1
GEMINI_ACP_PERMISSION_METHOD = "session/request_permission"
_IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@+~-]{0,255}\Z")


class GeminiAcpPocError(RuntimeError):
    """Raised when the reviewed Gemini ACP proof contract is violated."""


@dataclass(frozen=True)
class GeminiAcpHandshake:
    """Content-free reviewed projection of one ACP initialize response."""

    cli_version: str
    protocol_version: int
    auth_method_ids: tuple[str, ...]
    capability_snapshot: AdapterCapabilitySnapshot


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
        raise GeminiAcpPocError("installed Gemini CLI does not advertise --acp")
    _validate_identity(cli_version, field_name="Gemini CLI version")
    _validate_identity(adapter_version, field_name="adapter version")
    if not isinstance(result, Mapping):
        raise GeminiAcpPocError("ACP initialize result must be an object")
    protocol_version = result.get("protocolVersion")
    if protocol_version != GEMINI_ACP_PROTOCOL_VERSION:
        raise GeminiAcpPocError("Gemini ACP protocol version is not reviewed")
    agent_info = _mapping(result.get("agentInfo"), field_name="agentInfo")
    if agent_info.get("name") != "gemini-cli":
        raise GeminiAcpPocError("ACP agent identity is not Gemini CLI")
    if agent_info.get("version") != cli_version:
        raise GeminiAcpPocError("Gemini help and ACP versions differ")

    raw_auth_methods = result.get("authMethods")
    if not isinstance(raw_auth_methods, Sequence) or isinstance(
        raw_auth_methods, (str, bytes)
    ):
        raise GeminiAcpPocError("ACP authMethods must be an array")
    auth_method_ids: list[str] = []
    for item in raw_auth_methods:
        method = _mapping(item, field_name="auth method")
        method_id = method.get("id")
        _validate_identity(method_id, field_name="auth method id")
        auth_method_ids.append(method_id)
    if not auth_method_ids or len(set(auth_method_ids)) != len(auth_method_ids):
        raise GeminiAcpPocError("ACP auth method identities are empty or duplicated")

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
    dynamic_mcp = any(mcp_capabilities.get(name) is True for name in ("http", "sse"))
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
        dynamic_mcp=dynamic_mcp,
        recovery_after_process_loss=load_session,
        attachment_kinds=attachment_kinds,
        attachment_transports=("acp-inline", "acp-resource"),
    )
    return GeminiAcpHandshake(
        cli_version=cli_version,
        protocol_version=protocol_version,
        auth_method_ids=tuple(auth_method_ids),
        capability_snapshot=snapshot,
    )


class GeminiAcpPocClient:
    """Small non-product ACP client used to decide whether N2-03 may proceed."""

    def __init__(
        self,
        transport_factory: Callable[[], StructuredTransport],
        *,
        cli_help: str,
        cli_version: str,
        adapter_version: str,
        request_timeout_seconds: float = 2.0,
    ) -> None:
        if request_timeout_seconds <= 0:
            raise ValueError("ACP request timeout must be positive")
        self.cli_help = cli_help
        self.cli_version = cli_version
        self.adapter_version = adapter_version
        self.request_timeout_seconds = float(request_timeout_seconds)
        self.supervisor = StructuredProcessSupervisor(
            transport_factory,
            event_normalizer=normalize_gemini_acp_event,
            approval_methods=frozenset({GEMINI_ACP_PERMISSION_METHOD}),
        )
        self.handshake: GeminiAcpHandshake | None = None
        self.session_id: str | None = None

    def start(self) -> int:
        """Start the first ACP transport generation."""
        return self.supervisor.start()

    def initialize(self) -> GeminiAcpHandshake:
        """Handshake with ACP and retain only reviewed content-free evidence."""
        result = self.supervisor.request(
            "initialize",
            {
                "protocolVersion": GEMINI_ACP_PROTOCOL_VERSION,
                "clientInfo": {
                    "name": "gpt2giga-harness-poc",
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
        self.handshake = probe_gemini_acp_handshake(
            cli_help=self.cli_help,
            cli_version=self.cli_version,
            adapter_version=self.adapter_version,
            result=result,
        )
        return self.handshake

    def authenticate(
        self,
        method_id: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Authenticate ephemerally without retaining credential-bearing metadata."""
        handshake = self._require_handshake()
        if method_id not in handshake.auth_method_ids:
            raise GeminiAcpPocError("ACP auth method was not advertised")
        params: dict[str, Any] = {"methodId": method_id}
        if metadata is not None:
            if not isinstance(metadata, Mapping):
                raise ValueError("ACP auth metadata must be a mapping")
            params["_meta"] = dict(metadata)
        self.supervisor.request(
            "authenticate", params, timeout=self.request_timeout_seconds
        )

    def new_session(
        self,
        *,
        cwd: str,
        mcp_servers: Sequence[Mapping[str, Any]] = (),
    ) -> str:
        """Create one provider-owned ACP session and retain only its identity."""
        self._require_handshake()
        result = self.supervisor.request(
            "session/new",
            {
                "cwd": _require_text(cwd, field_name="cwd"),
                "mcpServers": list(mcp_servers),
            },
            timeout=self.request_timeout_seconds,
        )
        session_id = result.get("sessionId")
        _validate_identity(session_id, field_name="ACP session id")
        self.session_id = session_id
        return session_id

    def load_session(
        self,
        session_id: str,
        *,
        cwd: str,
        mcp_servers: Sequence[Mapping[str, Any]] = (),
    ) -> str:
        """Reload an exact provider session without accepting transcript input."""
        handshake = self._require_handshake()
        if not handshake.capability_snapshot.resume:
            raise GeminiAcpPocError("ACP loadSession was not advertised")
        _validate_identity(session_id, field_name="ACP session id")
        self.supervisor.request(
            "session/load",
            {
                "sessionId": session_id,
                "cwd": _require_text(cwd, field_name="cwd"),
                "mcpServers": list(mcp_servers),
            },
            timeout=self.request_timeout_seconds,
        )
        self.session_id = session_id
        return session_id

    def begin_prompt(self, *, turn_id: str, text: str) -> StructuredRequestHandle:
        """Begin an ACP prompt whose text remains only in the live transport."""
        session_id = self._require_session()
        _validate_identity(turn_id, field_name="ACP turn id")
        return self.supervisor.begin_request(
            "session/prompt",
            {
                "sessionId": session_id,
                "messageId": turn_id,
                "prompt": [
                    {"type": "text", "text": _require_text(text, field_name="prompt")}
                ],
            },
        )

    def cancel(self) -> None:
        """Send ACP's session-scoped cancellation notification."""
        self.supervisor.notify("session/cancel", {"sessionId": self._require_session()})

    def next_event(self, *, timeout: float) -> NormalizedStructuredEvent | None:
        """Return the next provider-neutral ephemeral ACP event."""
        return self.supervisor.next_event(timeout=timeout)

    def next_permission(self, *, timeout: float) -> StructuredBridgeRequest | None:
        """Return the next live ACP permission request."""
        request = self.supervisor.next_bridge_request(timeout=timeout)
        if request is not None and request.kind is not StructuredBridgeKind.APPROVAL:
            raise GeminiAcpPocError("unexpected ACP bridge kind")
        return request

    def respond_permission(
        self,
        request: StructuredBridgeRequest,
        *,
        option_id: str | None,
    ) -> None:
        """Select one offered permission option or return an explicit cancellation."""
        if request.method != GEMINI_ACP_PERMISSION_METHOD:
            raise GeminiAcpPocError("unexpected ACP permission method")
        if option_id is None:
            outcome: Mapping[str, Any] = {"outcome": "cancelled"}
        else:
            _validate_identity(option_id, field_name="ACP permission option id")
            options = request.params.get("options")
            if not isinstance(options, Sequence) or isinstance(options, (str, bytes)):
                raise GeminiAcpPocError("ACP permission options are invalid")
            offered = {
                item.get("optionId")
                for item in options
                if isinstance(item, Mapping) and isinstance(item.get("optionId"), str)
            }
            if option_id not in offered:
                raise GeminiAcpPocError("ACP permission option was not offered")
            outcome = {"outcome": "selected", "optionId": option_id}
        self.supervisor.respond_bridge(
            request.id,
            generation=request.generation,
            result={"outcome": outcome},
        )

    def restart_and_load(
        self,
        session_id: str,
        *,
        cwd: str,
        auth_method_id: str,
        auth_metadata: Mapping[str, Any] | None = None,
        mcp_servers: Sequence[Mapping[str, Any]] = (),
    ) -> str:
        """Start a fresh process generation and reload without prompt replay."""
        self.supervisor.restart()
        self.handshake = None
        self.session_id = None
        self.initialize()
        self.authenticate(auth_method_id, metadata=auth_metadata)
        return self.load_session(session_id, cwd=cwd, mcp_servers=mcp_servers)

    def close(self) -> None:
        """Stop the proof transport."""
        self.supervisor.close()

    def _require_handshake(self) -> GeminiAcpHandshake:
        if self.handshake is None:
            raise GeminiAcpPocError("ACP initialize handshake is required")
        return self.handshake

    def _require_session(self) -> str:
        if self.session_id is None:
            raise GeminiAcpPocError("ACP session is not open")
        return self.session_id


def normalize_gemini_acp_event(
    method: str, params: Mapping[str, Any]
) -> NormalizedStructuredEvent | None:
    """Normalize reviewed ACP session updates without retaining raw tool I/O."""
    if method != "session/update":
        return None
    session_id = params.get("sessionId")
    _validate_identity(session_id, field_name="ACP event session id")
    update = _mapping(params.get("update"), field_name="ACP session update")
    kind = update.get("sessionUpdate")
    if not isinstance(kind, str) or not kind:
        raise GeminiAcpPocError("ACP session update kind is invalid")
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
            raise GeminiAcpPocError("ACP tool status is invalid")
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
            raise GeminiAcpPocError("ACP plan entries are invalid")
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


def _mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GeminiAcpPocError(f"{field_name} must be an object")
    return value


def _require_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} is required")
    return value


def _validate_identity(value: Any, *, field_name: str) -> None:
    if not isinstance(value, str) or _IDENTITY_RE.fullmatch(value) is None:
        raise GeminiAcpPocError(f"{field_name} is invalid")
