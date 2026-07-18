"""Supervised Codex app-server continuity for normalized Harness sessions."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable, Mapping, Protocol
from uuid import uuid4

from gpt2giga_harness.executables import ExecutableResolution
from gpt2giga_harness.execution import (
    EMPTY_EXTENSION_SNAPSHOT_HASH,
    ExecutionClassification,
    ExecutionClassificationStatus,
    ExecutionSnapshot,
    ExecutionTransport,
    InteractionMode,
    ProviderRef,
    RouteRef,
    RuntimeOwnership,
    SnapshotEvidenceRef,
    create_execution_snapshot,
)
from gpt2giga_harness.harnesses.agent_cli import build_safe_env
from gpt2giga_harness.managed_mcp import (
    clear_headless_mcp_materialization,
    materialize_headless_mcp_snapshot,
    write_startup_config,
)
from gpt2giga_harness.runtime.models import ApprovalStatus
from gpt2giga_harness.runtime.policy import (
    ApprovalDecision,
    EnforcementLevel,
    PermissionAction,
    PolicyContext,
    PolicyResolution,
)
from gpt2giga_harness.runtime.store import RuntimeCoordinationStore
from gpt2giga_harness.sessions.locking import exclusive_file_lock
from gpt2giga_harness.sessions.store import utc_now
from gpt2giga_harness.structured_sessions import (
    AdapterCapabilitySnapshot,
    StructuredSessionConfigSnapshot,
    StructuredSessionCoordinator,
    StructuredSessionError,
    StructuredSessionLink,
    StructuredSessionLinkStore,
    StructuredSessionState,
    StructuredTurnInput,
    StructuredTurnResult,
    UnsupportedSessionCapability,
    structured_session_link_to_dict,
)
from gpt2giga_harness.tools.policy import PolicyDecision
from gpt2giga_harness.types import (
    HarnessContext,
    HarnessEvent,
    HarnessEventType,
    HarnessRequest,
    HarnessResult,
    emit_event,
    redact_secrets,
)

APP_SERVER_PROTOCOL = "codex-app-server-json-rpc-v2"
APP_SERVER_LINK_SCHEMA_VERSION = 1
APP_SERVER_TIMEOUT_SECONDS = 10.0
APP_SERVER_MESSAGE_POLL_SECONDS = 0.1
APP_SERVER_STDERR_CHARS = 8000
APP_SERVER_DRIVER_PROTOCOL_VERSION = "2"
APP_SERVER_APPROVAL_OWNER = "codex_app_server.approval"
APP_SERVER_APPROVAL_POLL_SECONDS = 0.05
_APPROVAL_METHODS = frozenset(
    {
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
        "item/permissions/requestApproval",
    }
)


class AppServerProtocolError(RuntimeError):
    """Raised when app-server violates the reviewed JSON-RPC contract."""


class AppServerClient(Protocol):
    """Minimal synchronous JSON-RPC client used by the supervisor."""

    runtime_id: str

    @property
    def alive(self) -> bool:
        """Return whether the owning app-server process is still usable."""

    def request(
        self, method: str, params: Mapping[str, Any], *, timeout: float
    ) -> Mapping[str, Any]:
        """Send one request and return its result object."""

    def next_message(self, *, timeout: float) -> Mapping[str, Any] | None:
        """Return the next server notification or server-initiated request."""

    def respond(
        self,
        request_id: str | int,
        *,
        result: Mapping[str, Any] | None = None,
        error: Mapping[str, Any] | None = None,
    ) -> None:
        """Answer a server-initiated request."""

    def close(self) -> None:
        """Stop the owned transport."""


@dataclass
class _Runtime:
    scope_id: str
    client: AppServerClient
    loaded_threads: set[str] = field(default_factory=set)
    turn_lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass
class _PendingApproval:
    request_id: str | int
    method: str
    params: Mapping[str, Any]
    durable_approval_id: str | None = None


class CodexAppServerLinkStore:
    """Persist redaction-safe thread links and prompt delivery state atomically."""

    def __init__(self, data_dir: str | Path) -> None:
        self.root = Path(data_dir).expanduser().resolve() / "app_server" / "links"

    def load(self, session_id: str) -> dict[str, Any] | None:
        """Load one link, returning ``None`` when it has not been created."""
        path = self._path(session_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, OSError) as exc:
            raise AppServerProtocolError("Codex app-server link is unreadable") from exc
        if not isinstance(value, Mapping):
            raise AppServerProtocolError("Codex app-server link must be an object")
        return dict(value)

    def save(self, session_id: str, link: Mapping[str, Any]) -> dict[str, Any]:
        """Write one public link without prompt text, stdio, credentials, or PIDs."""
        payload = dict(redact_secrets(dict(link)))
        path = self._path(session_id)
        with exclusive_file_lock(self.root / f".{_safe_id(session_id)}"):
            _atomic_write(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return payload

    def _path(self, session_id: str) -> Path:
        return self.root / f"{_safe_id(session_id)}.json"


class CodexAppServerSupervisor:
    """Reuse compatible app-server processes while persisting thread ownership."""

    def __init__(
        self,
        data_dir: str | Path,
        *,
        client_factory: Callable[..., AppServerClient] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.link_store = CodexAppServerLinkStore(self.data_dir)
        self.structured_link_store = StructuredSessionLinkStore(self.data_dir)
        self.runtime_store = RuntimeCoordinationStore(self.data_dir)
        self.client_factory = client_factory or _StdioJsonRpcClient
        self._runtimes: dict[str, _Runtime] = {}
        self._runtime_lock = threading.Lock()
        self._active_drivers: dict[str, CodexAppServerDriver] = {}
        self._active_driver_lock = threading.Lock()

    def interrupt_turn(self, session_id: str) -> None:
        """Interrupt the exact active provider turn for one Harness session."""
        driver = self._active_driver(session_id)
        turn_id = driver.active_turn_id
        if turn_id is None:
            raise StructuredSessionError("Codex session has no active turn")
        driver.interrupt(turn_id)

    def steer_turn(self, session_id: str, turn_input: StructuredTurnInput) -> None:
        """Steer the exact active provider turn without transcript replay."""
        driver = self._active_driver(session_id)
        turn_id = driver.active_turn_id
        if turn_id is None:
            raise StructuredSessionError("Codex session has no active turn")
        driver.steer(turn_id, turn_input)

    def _active_driver(self, session_id: str) -> CodexAppServerDriver:
        with self._active_driver_lock:
            driver = self._active_drivers.get(session_id)
        if driver is None:
            raise StructuredSessionError("Codex session has no active driver")
        return driver

    def run_turn(
        self,
        request: HarnessRequest,
        context: HarnessContext,
        *,
        resolution: ExecutableResolution,
        prompt: str,
        continuation: Mapping[str, Any],
    ) -> HarnessResult:
        """Start, continue, recover, or fork one structured Codex thread."""
        if request.session_id is None:
            raise ValueError(
                "Codex app-server continuity requires a Harness session id"
            )
        snapshot = _mapping(continuation.get("snapshot"))
        snapshot_hash = str(snapshot.get("snapshot_hash") or "")
        if len(snapshot_hash) != 64:
            raise ValueError("Codex app-server execution snapshot is invalid")
        prompt_id = str(continuation.get("prompt_id") or "").strip()
        if not prompt_id:
            raise ValueError("Codex app-server prompt id is required")
        command = resolution.command
        if not command:
            raise ValueError("Codex app-server executable is unavailable")
        scope_id = _scope_id(
            command,
            {
                **snapshot,
                "cli_version": _driver_version(
                    continuation.get("cli_version")
                    or continuation.get("adapter_version")
                ),
            },
        )
        runtime = self._runtime_for(
            scope_id,
            command=command,
            request=request,
            context=context,
            snapshot=snapshot,
        )
        command_display = (*command, "app-server", "--stdio", "--strict-config")
        with runtime.turn_lock:
            return self._run_through_driver(
                runtime,
                request,
                context,
                prompt=prompt,
                prompt_id=prompt_id,
                continuation=continuation,
                snapshot=snapshot,
                command_display=command_display,
            )

    def _run_through_driver(
        self,
        runtime: _Runtime,
        request: HarnessRequest,
        context: HarnessContext,
        *,
        prompt: str,
        prompt_id: str,
        continuation: Mapping[str, Any],
        snapshot: Mapping[str, Any],
        command_display: tuple[str, ...],
    ) -> HarnessResult:
        assert request.session_id is not None
        stored_link = self.link_store.load(request.session_id)
        supplied_link = _mapping(continuation.get("link"))
        link = stored_link or supplied_link or None
        if link is not None:
            _validate_link_snapshot(link, snapshot)
            if link.get("last_prompt_id") == prompt_id:
                return HarnessResult(
                    ok=False,
                    text="",
                    raw={"app_server_thread": _public_link(link)},
                    command=command_display,
                    error=(
                        "Codex app-server prompt was already submitted; refusing "
                        "duplicate delivery."
                    ),
                )

        adapter_version = _adapter_version()
        cli_version = _driver_version(
            continuation.get("cli_version") or continuation.get("adapter_version")
        )
        execution_snapshot = build_structured_execution_snapshot(
            snapshot,
            adapter_version=adapter_version,
            cli_version=cli_version,
        )
        config_snapshot = StructuredSessionConfigSnapshot(
            adapter_id="codex-cli",
            adapter_version=adapter_version,
            protocol=APP_SERVER_PROTOCOL,
            protocol_version=APP_SERVER_DRIVER_PROTOCOL_VERSION,
            cli_sdk_version=cli_version,
            managed_home_id=_optional_text(snapshot.get("managed_home_id")),
        )
        driver = CodexAppServerDriver(
            supervisor=self,
            runtime=runtime,
            request=request,
            context=context,
            command_display=command_display,
            continuation=continuation,
            legacy_snapshot=snapshot,
            legacy_link=link,
            adapter_version=adapter_version,
        )
        coordinator = StructuredSessionCoordinator(
            driver,
            self.structured_link_store,
            owner_id=runtime.client.runtime_id,
        )
        link_id = _structured_link_id(request.session_id)
        existing = self.structured_link_store.load(link_id)
        collected: list[HarnessEvent] = []

        def event_sink(event: Mapping[str, Any]) -> None:
            normalized = HarnessEvent(
                type=str(event.get("type") or "unknown"),
                message=str(event.get("message") or ""),
                payload=_mapping(event.get("payload")),
            )
            _publish(request, collected, normalized)

        try:
            structured_link = coordinator.open_or_resume(
                link_id=link_id,
                harness_session_id=request.session_id,
                harness_run_id=request.run_id or f"run-{_safe_id(prompt_id)}",
                execution_snapshot=execution_snapshot,
                config_snapshot=config_snapshot,
                existing_link=existing,
            )
            with self._active_driver_lock:
                self._active_drivers[request.session_id] = driver
            try:
                structured_link, _turn = coordinator.start_turn(
                    structured_link,
                    StructuredTurnInput(prompt_id, prompt),
                    event_sink,
                    lambda provider_request: self._await_durable_approval(
                        request,
                        context,
                        collected,
                        provider_request,
                    ),
                )
            finally:
                with self._active_driver_lock:
                    if self._active_drivers.get(request.session_id) is driver:
                        self._active_drivers.pop(request.session_id, None)
            result = driver.result
            if result is None:
                raise AppServerProtocolError(
                    "Codex app-server driver returned no turn result"
                )
            return replace(
                result,
                raw={
                    **dict(result.raw),
                    "structured_session_link": structured_session_link_to_dict(
                        structured_link
                    ),
                    "structured_session_driver": "codex-app-server",
                },
                events=tuple(collected),
            )
        except Exception as exc:
            link = driver.mark_interrupted(prompt_id)
            return HarnessResult(
                ok=False,
                text="",
                raw={
                    "app_server_thread": _public_link(link),
                    **(
                        {
                            "structured_session_link": structured_session_link_to_dict(
                                current
                            )
                        }
                        if (current := self.structured_link_store.load(link_id))
                        is not None
                        else {}
                    ),
                },
                events=tuple(collected),
                command=command_display,
                error=str(redact_secrets(str(exc))),
            )

    def _await_durable_approval(
        self,
        request: HarnessRequest,
        context: HarnessContext,
        collected: list[HarnessEvent],
        provider_request: Mapping[str, Any],
    ) -> str:
        """Persist one provider request and await its Approval Center decision."""
        method = str(provider_request.get("method") or "")
        params = _mapping(provider_request.get("params"))
        request_id = provider_request.get("id")
        action, reason, preview = _approval_contract(method, params)
        approval_binding = _provider_approval_binding(method, request_id, params)
        existing = self.runtime_store.find_approval_request_by_binding(approval_binding)
        timeout_seconds = max(
            min(
                float(provider_request.get("timeout_seconds") or 0.0),
                max(context.timeout_seconds, 0.1),
            ),
            0.1,
        )
        if existing is None:
            runtime = _mapping(request.extra.get("runtime"))
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)
            ).isoformat()
            approval = self.runtime_store.create_approval_request(
                PolicyResolution(
                    action=action,
                    decision=PolicyDecision.ASK,
                    enforcement=EnforcementLevel.ENFORCED_BY_HARNESS,
                    policy_source="codex_app_server:on_request",
                ),
                PolicyContext(
                    project_id=_optional_text(request.extra.get("project_id")),
                    session_id=request.session_id,
                    run_id=request.run_id,
                    job_id=_optional_text(runtime.get("job_id")),
                    reason=reason,
                    preview=preview,
                    approval_binding=approval_binding,
                    enforcement_owner=APP_SERVER_APPROVAL_OWNER,
                ),
                expires_at=expires_at,
            )
        else:
            approval = existing
        with self._active_driver_lock:
            active_driver = (
                self._active_drivers.get(request.session_id)
                if request.session_id is not None
                else None
            )
        if active_driver is not None:
            active_driver.bind_durable_approval(str(request_id), approval.id)
        _publish(
            request,
            collected,
            HarnessEvent(
                type="approval_requested",
                message="Codex app-server is waiting for Approval Center.",
                payload={
                    "approval_id": approval.id,
                    "action": approval.action.value,
                    "method": method,
                    "reused": existing is not None,
                },
            ),
        )
        deadline = time.monotonic() + timeout_seconds
        while True:
            current = self.runtime_store.get_approval_request(approval.id)
            if current.status is ApprovalStatus.APPROVED:
                decision = "accept"
                break
            if current.status in {
                ApprovalStatus.DENIED,
                ApprovalStatus.EXPIRED,
                ApprovalStatus.CANCELED,
            }:
                decision = "decline"
                break
            if _cancel_requested(request.cancel_event):
                decision = "cancel"
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                decision = "decline"
                break
            time.sleep(min(APP_SERVER_APPROVAL_POLL_SECONDS, remaining))
        _publish(
            request,
            collected,
            HarnessEvent(
                type="approval_decided",
                message="Codex app-server approval received a durable outcome.",
                payload={
                    "approval_id": approval.id,
                    "action": approval.action.value,
                    "decision": decision,
                },
            ),
        )
        return decision

    def _wait_for_turn(
        self,
        runtime: _Runtime,
        request: HarnessRequest,
        context: HarnessContext,
        *,
        thread_id: str,
        turn_id: str,
        link: Mapping[str, Any],
        command_display: tuple[str, ...],
        server_request_handler: Callable[
            [Mapping[str, Any], HarnessRequest, list[HarnessEvent], float], None
        ],
    ) -> HarnessResult:
        collected: list[HarnessEvent] = []
        final_text = ""
        deadline = time.monotonic() + max(context.timeout_seconds, 0.1)
        interrupt_sent = False
        subagent_parents: dict[str, str] = {}
        seen_subagent_events: set[tuple[str, str, str]] = set()
        while time.monotonic() < deadline:
            if _cancel_requested(request.cancel_event) and not interrupt_sent:
                runtime.client.request(
                    "turn/interrupt",
                    {"threadId": thread_id, "turnId": turn_id},
                    timeout=APP_SERVER_TIMEOUT_SECONDS,
                )
                interrupt_sent = True
            message = runtime.client.next_message(
                timeout=min(
                    APP_SERVER_MESSAGE_POLL_SECONDS,
                    max(deadline - time.monotonic(), 0.0),
                )
            )
            if message is None:
                if not runtime.client.alive:
                    raise AppServerProtocolError(
                        "Codex app-server owner exited before turn completion"
                    )
                continue
            method = str(message.get("method") or "")
            params = _mapping(message.get("params"))
            if "id" in message:
                server_request_handler(
                    message,
                    request,
                    collected,
                    max(deadline - time.monotonic(), 0.1),
                )
                continue
            if params.get("threadId") not in {None, thread_id}:
                continue
            if params.get("turnId") not in {None, turn_id}:
                continue
            subagent_snapshots: tuple[dict[str, Any], ...] = ()
            item = _mapping(params.get("item"))
            if (
                method in {"item/started", "item/completed"}
                and str(item.get("type") or "") == "collabToolCall"
            ):
                subagent_snapshots = _read_collab_subagents(runtime.client, item)
                if subagent_snapshots:
                    enriched_item = {
                        **item,
                        "subagents": [
                            _public_collab_subagent(snapshot)
                            for snapshot in subagent_snapshots
                        ],
                    }
                    params = {**params, "item": enriched_item}
                    item = enriched_item
                if _collab_tool(item) == "spawn_agent":
                    parent_id = str(item.get("id") or "")
                    for child_id in _collab_thread_ids(item):
                        if parent_id:
                            subagent_parents[child_id] = parent_id
            if method == "turn/completed":
                emitted_tool_ids = {
                    str(event.payload.get("tool_call_id") or "")
                    for event in collected
                    if event.payload.get("tool_call_id")
                }
                for rollout_event in _rollout_multi_agent_events(
                    runtime.client,
                    home=self.data_dir / "app_server" / "homes" / runtime.scope_id,
                    thread_id=thread_id,
                    turn_id=turn_id,
                    seen_tool_call_ids=emitted_tool_ids,
                ):
                    _publish(request, collected, rollout_event)
            event, item_text = _normalize_notification(method, params)
            if item_text is not None:
                final_text = item_text
            if event is not None:
                _publish(request, collected, event)
            if method == "item/completed" and subagent_snapshots:
                for child_event in _collab_child_tool_events(
                    subagent_snapshots,
                    subagent_parents=subagent_parents,
                    seen=seen_subagent_events,
                ):
                    _publish(request, collected, child_event)
            if method == "turn/completed":
                turn = _mapping(params.get("turn"))
                status = str(turn.get("status") or "failed")
                final_text = _turn_text(turn) or final_text
                completed_link = self.link_store.save(
                    request.session_id or "",
                    {
                        **link,
                        "runtime_status": "loaded",
                        "updated_at": utc_now(),
                        "last_prompt_status": status,
                    },
                )
                ok = status == "completed"
                return HarnessResult(
                    ok=ok,
                    text=final_text if ok else "",
                    raw={
                        "app_server_thread": _public_link(completed_link),
                        "continuation_strategy": "structured_thread",
                    },
                    events=tuple(collected),
                    command=command_display,
                    error=None if ok else f"Codex app-server turn {status}.",
                )
        runtime.client.request(
            "turn/interrupt",
            {"threadId": thread_id, "turnId": turn_id},
            timeout=APP_SERVER_TIMEOUT_SECONDS,
        )
        raise TimeoutError("Codex app-server turn timed out and was interrupted")

    def _runtime_for(
        self,
        scope_id: str,
        *,
        command: tuple[str, ...],
        request: HarnessRequest,
        context: HarnessContext,
        snapshot: Mapping[str, Any],
    ) -> _Runtime:
        with self._runtime_lock:
            current = self._runtimes.get(scope_id)
            if current is not None and current.client.alive:
                return current
            if current is not None:
                current.client.close()
            home = self.data_dir / "app_server" / "homes" / scope_id
            home.mkdir(parents=True, exist_ok=True)
            _write_provider_config(home, request, context)
            managed_mcp = _mapping(request.extra.get("managed_mcp_snapshot")) or None
            if managed_mcp is not None:
                materialize_headless_mcp_snapshot(
                    "codex-cli",
                    home,
                    managed_mcp,
                    data_dir=self.data_dir,
                )
            env = build_safe_env(
                context,
                extra={
                    "CODEX_HOME": str(home),
                    "GPT2GIGA_API_KEY": context.api_key or "0",
                    "GPT2GIGA_HARNESS_PROXY_URL": context.proxy_url,
                    "GPT2GIGA_HARNESS_API_MODE": request.api_mode.value,
                },
            )
            try:
                client = self.client_factory(
                    command=(*command, "app-server", "--stdio", "--strict-config"),
                    env=env,
                    cwd=str(self.data_dir),
                    runtime_id=f"asrv_{scope_id}_{uuid4().hex[:16]}",
                )
            finally:
                if managed_mcp is not None:
                    clear_headless_mcp_materialization("codex-cli", home)
            runtime = _Runtime(scope_id=scope_id, client=client)
            self._runtimes[scope_id] = runtime
            return runtime


class CodexAppServerDriver:
    """Adapt Codex app-server thread/turn continuity to the generic driver."""

    def __init__(
        self,
        *,
        supervisor: CodexAppServerSupervisor,
        runtime: _Runtime,
        request: HarnessRequest,
        context: HarnessContext,
        command_display: tuple[str, ...],
        continuation: Mapping[str, Any],
        legacy_snapshot: Mapping[str, Any],
        legacy_link: Mapping[str, Any] | None,
        adapter_version: str,
    ) -> None:
        self.supervisor = supervisor
        self.runtime = runtime
        self.request = request
        self.context = context
        self.command_display = command_display
        self.continuation = dict(continuation)
        self.legacy_snapshot = dict(legacy_snapshot)
        self.legacy_link = dict(legacy_link) if legacy_link is not None else None
        self.adapter_version = adapter_version
        self.thread_id: str | None = None
        self.active_turn_id: str | None = None
        self.result: HarnessResult | None = None
        self._approval_bridge: Callable[[Mapping[str, Any]], str] | None = None
        self._pending_approvals: dict[str, _PendingApproval] = {}
        self._pending_approval_lock = threading.Lock()

    def probe(self) -> AdapterCapabilitySnapshot:
        """Project reviewed app-server v2 behavior into neutral capabilities."""
        return AdapterCapabilitySnapshot(
            adapter_id="codex-cli",
            adapter_version=self.adapter_version,
            protocol=APP_SERVER_PROTOCOL,
            protocol_version=APP_SERVER_DRIVER_PROTOCOL_VERSION,
            structured_events=True,
            partial_output=True,
            interactive_input=False,
            live_approvals=True,
            durable_approval=True,
            interrupt=True,
            steer=True,
            resume=True,
            fork=True,
            session_list=False,
            session_close=False,
            native_auth=False,
            provider_ui_handoff=False,
            dynamic_model=False,
            dynamic_mcp=False,
            recovery_after_process_loss=True,
        )

    def open_or_resume(
        self,
        execution_snapshot: ExecutionSnapshot,
        session_link: StructuredSessionLink | None,
    ) -> StructuredSessionState:
        """Start, import, resume, or explicitly fork one provider thread."""
        del execution_snapshot
        action = str(self.continuation.get("action") or "start")
        recovery_outcome = "not_required"
        forked_from: str | None = None
        if action == "fork":
            source_thread_id = str(
                self.continuation.get("fork_thread_id")
                or _mapping(self.continuation.get("fork")).get("thread_id")
                or ""
            ).strip()
            if not source_thread_id:
                raise ValueError("Codex app-server fork requires a source thread id")
            response = self.runtime.client.request(
                "thread/fork",
                {
                    **_thread_identity_params(self.request),
                    "threadId": source_thread_id,
                    "lastTurnId": self.continuation.get("fork_turn_id"),
                },
                timeout=APP_SERVER_TIMEOUT_SECONDS,
            )
            thread_id = _thread_id(response)
            forked_from = source_thread_id
            recovery_outcome = "forked"
        else:
            legacy_thread_id = _optional_text((self.legacy_link or {}).get("thread_id"))
            generic_thread_id = (
                session_link.external_session_id if session_link is not None else None
            )
            if (
                legacy_thread_id is not None
                and generic_thread_id is not None
                and legacy_thread_id != generic_thread_id
            ):
                raise StructuredSessionError(
                    "Codex compatibility and structured links disagree"
                )
            thread_id = generic_thread_id or legacy_thread_id
            forked_from = _optional_text(
                (self.legacy_link or {}).get("forked_from_thread_id")
            )
            if thread_id is None:
                response = self.runtime.client.request(
                    "thread/start",
                    {
                        **_thread_identity_params(self.request),
                        "ephemeral": False,
                    },
                    timeout=APP_SERVER_TIMEOUT_SECONDS,
                )
                thread_id = _thread_id(response)
            elif (
                str((self.legacy_link or {}).get("runtime_id") or "")
                != self.runtime.client.runtime_id
                or thread_id not in self.runtime.loaded_threads
            ):
                previous_status = str(
                    (self.legacy_link or {}).get("last_prompt_status") or ""
                )
                if previous_status == "submitted":
                    recovery_outcome = self._resolve_inflight_owner_loss(thread_id)
                else:
                    self._resume_thread(thread_id)
                    recovery_outcome = "resumed_after_owner_change"
        self.thread_id = thread_id
        self.runtime.loaded_threads.add(thread_id)
        now = utc_now()
        previous = self.legacy_link or {}
        self.legacy_link = self.supervisor.link_store.save(
            self.request.session_id or "",
            {
                "schema_version": APP_SERVER_LINK_SCHEMA_VERSION,
                "protocol": APP_SERVER_PROTOCOL,
                "runtime_id": self.runtime.client.runtime_id,
                "thread_id": thread_id,
                "latest_turn_id": (
                    session_link.latest_external_turn_id
                    if session_link is not None
                    else previous.get("latest_turn_id")
                ),
                "forked_from_thread_id": forked_from,
                "snapshot": dict(self.legacy_snapshot),
                "snapshot_hash": self.legacy_snapshot["snapshot_hash"],
                "runtime_status": "loaded",
                "recovery_outcome": recovery_outcome,
                "created_at": previous.get("created_at") or now,
                "resumed_at": (now if recovery_outcome.startswith("resumed") else None),
                "updated_at": now,
                "last_prompt_id": previous.get("last_prompt_id"),
                "last_prompt_status": previous.get("last_prompt_status"),
            },
        )
        return StructuredSessionState(
            thread_id,
            _optional_text(self.legacy_link.get("latest_turn_id")),
        )

    def start_turn(
        self,
        turn_input: StructuredTurnInput,
        event_sink: Callable[[Mapping[str, Any]], None],
        approval_bridge: Callable[[Mapping[str, Any]], str],
    ) -> StructuredTurnResult:
        """Run one Codex turn and publish normalized events through the driver sink."""
        if self.thread_id is None or self.legacy_link is None:
            raise StructuredSessionError("Codex structured session is not open")
        self._approval_bridge = approval_bridge
        response = self.runtime.client.request(
            "turn/start",
            {
                "threadId": self.thread_id,
                "input": [{"type": "text", "text": turn_input.content}],
                "clientUserMessageId": turn_input.id,
                "model": self.request.model,
                "cwd": self.request.workspace,
                "approvalPolicy": "on-request",
                "approvalsReviewer": "user",
            },
            timeout=APP_SERVER_TIMEOUT_SECONDS,
        )
        turn_id = _turn_id(response)
        self.active_turn_id = turn_id
        self.legacy_link = self.supervisor.link_store.save(
            self.request.session_id or "",
            {
                **self.legacy_link,
                "latest_turn_id": turn_id,
                "runtime_status": "turn_running",
                "updated_at": utc_now(),
                "last_prompt_id": turn_input.id,
                "last_prompt_status": "submitted",
            },
        )

        def publish(event: HarnessEvent) -> None:
            event_sink(
                {
                    "type": event.type,
                    "message": event.message,
                    "payload": dict(event.payload),
                }
            )

        request = replace(self.request, event_sink=publish)
        self.result = self.supervisor._wait_for_turn(
            self.runtime,
            request,
            self.context,
            thread_id=self.thread_id,
            turn_id=turn_id,
            link=self.legacy_link,
            command_display=self.command_display,
            server_request_handler=self._handle_server_request,
        )
        status = "completed" if self.result.ok else "failed"
        raw_link = _mapping(self.result.raw.get("app_server_thread"))
        status = str(raw_link.get("last_prompt_status") or status)
        return StructuredTurnResult(turn_id, status)

    def respond_to_input(self, request_id: str, answer: str) -> None:
        """Reject unproven provider input requests in the N2-00 driver."""
        del request_id, answer
        raise UnsupportedSessionCapability("interactive input is not supported")

    def respond_to_approval(self, request_id: str, decision: str) -> None:
        """Persist one exact pending decision for the blocked durable bridge."""
        normalized = _normalize_provider_decision(decision)
        with self._pending_approval_lock:
            pending = self._pending_approvals.get(request_id)
        if pending is None or pending.durable_approval_id is None:
            raise StructuredSessionError("Codex approval request is stale or unknown")
        self.supervisor.runtime_store.decide_approval_request(
            pending.durable_approval_id,
            (
                ApprovalDecision.ALLOW_ONCE
                if normalized == "accept"
                else ApprovalDecision.DENY
            ),
        )

    def bind_durable_approval(self, request_id: str, approval_id: str) -> None:
        """Bind the provider callback to its persisted Approval Center item."""
        with self._pending_approval_lock:
            pending = self._pending_approvals.get(request_id)
            if pending is None:
                raise StructuredSessionError(
                    "Codex approval request is stale or unknown"
                )
            pending.durable_approval_id = approval_id

    def interrupt(self, turn_id: str) -> None:
        """Interrupt an exact active Codex turn."""
        if self.thread_id is None:
            raise StructuredSessionError("Codex structured session is not open")
        self.runtime.client.request(
            "turn/interrupt",
            {"threadId": self.thread_id, "turnId": turn_id},
            timeout=APP_SERVER_TIMEOUT_SECONDS,
        )

    def steer(self, turn_id: str, turn_input: StructuredTurnInput) -> None:
        """Steer the exact active turn through the reviewed v2 precondition."""
        if self.thread_id is None or self.active_turn_id != turn_id:
            raise StructuredSessionError("Codex turn is not active for steering")
        self.runtime.client.request(
            "turn/steer",
            {
                "threadId": self.thread_id,
                "expectedTurnId": turn_id,
                "input": [{"type": "text", "text": turn_input.content}],
                "clientUserMessageId": turn_input.id,
            },
            timeout=APP_SERVER_TIMEOUT_SECONDS,
        )

    def recover(self, session_link: StructuredSessionLink) -> StructuredSessionState:
        """Recover the same provider thread without replaying normalized history."""
        self._resume_thread(session_link.external_session_id)
        self.thread_id = session_link.external_session_id
        self.runtime.loaded_threads.add(self.thread_id)
        return StructuredSessionState(
            self.thread_id,
            session_link.latest_external_turn_id,
        )

    def fork(
        self,
        session_link: StructuredSessionLink,
        turn_id: str | None,
    ) -> StructuredSessionState:
        """Create one provider-native fork without transcript replay."""
        response = self.runtime.client.request(
            "thread/fork",
            {
                **_thread_identity_params(self.request),
                "threadId": session_link.external_session_id,
                "lastTurnId": turn_id,
            },
            timeout=APP_SERVER_TIMEOUT_SECONDS,
        )
        thread_id = _thread_id(response)
        self.thread_id = thread_id
        self.runtime.loaded_threads.add(thread_id)
        return StructuredSessionState(thread_id)

    def close(self) -> None:
        """Leave the shared supervised runtime available for other sessions."""

    def mark_interrupted(self, prompt_id: str) -> dict[str, Any] | None:
        """Persist a bounded compatibility outcome after one driver failure."""
        if self.legacy_link is None or self.thread_id is None:
            return self.legacy_link
        self.legacy_link = self.supervisor.link_store.save(
            self.request.session_id or "",
            {
                **self.legacy_link,
                "runtime_status": "interrupted",
                "recovery_outcome": (
                    self.legacy_link.get("recovery_outcome")
                    if self.legacy_link.get("recovery_outcome")
                    == "ambiguous_after_owner_loss"
                    else "owner_error"
                ),
                "updated_at": utc_now(),
                "last_prompt_status": (
                    "interrupted"
                    if self.legacy_link.get("last_prompt_id") == prompt_id
                    else self.legacy_link.get("last_prompt_status")
                ),
            },
        )
        return self.legacy_link

    def _resume_thread(self, thread_id: str) -> None:
        self._read_thread(thread_id, include_turns=False)
        self.runtime.client.request(
            "thread/resume",
            {
                **_thread_identity_params(self.request),
                "threadId": thread_id,
            },
            timeout=APP_SERVER_TIMEOUT_SECONDS,
        )

    def _read_thread(
        self,
        thread_id: str,
        *,
        include_turns: bool,
    ) -> Mapping[str, Any]:
        response = self.runtime.client.request(
            "thread/read",
            {"threadId": thread_id, "includeTurns": include_turns},
            timeout=APP_SERVER_TIMEOUT_SECONDS,
        )
        return _mapping(response.get("thread"))

    def _resolve_inflight_owner_loss(self, thread_id: str) -> str:
        """Recover only a provider-proven terminal turn after owner loss."""
        thread = self._read_thread(thread_id, include_turns=True)
        latest_turn_id = _optional_text((self.legacy_link or {}).get("latest_turn_id"))
        status = _matching_turn_status(thread, latest_turn_id)
        if status not in {
            "completed",
            "failed",
            "canceled",
            "cancelled",
            "interrupted",
        }:
            now = utc_now()
            self.legacy_link = self.supervisor.link_store.save(
                self.request.session_id or "",
                {
                    **(self.legacy_link or {}),
                    "runtime_id": self.runtime.client.runtime_id,
                    "runtime_status": "interrupted",
                    "recovery_outcome": "ambiguous_after_owner_loss",
                    "updated_at": now,
                    "last_prompt_status": "ambiguous",
                },
            )
            raise AppServerProtocolError(
                "Codex owner loss left the active turn outcome ambiguous; "
                "refusing duplicate delivery"
            )
        self.runtime.client.request(
            "thread/resume",
            {
                **_thread_identity_params(self.request),
                "threadId": thread_id,
            },
            timeout=APP_SERVER_TIMEOUT_SECONDS,
        )
        if self.legacy_link is not None:
            self.legacy_link = {
                **self.legacy_link,
                "last_prompt_status": status,
            }
        return f"resumed_after_terminal_{status}"

    def _handle_server_request(
        self,
        message: Mapping[str, Any],
        request: HarnessRequest,
        collected: list[HarnessEvent],
        timeout_seconds: float,
    ) -> None:
        request_id = message.get("id")
        method = str(message.get("method") or "")
        params = _mapping(message.get("params"))
        if (
            method not in _APPROVAL_METHODS
            or not isinstance(request_id, (str, int))
            or self.thread_id is None
            or self.active_turn_id is None
            or params.get("threadId") != self.thread_id
            or params.get("turnId") != self.active_turn_id
        ):
            _decline_server_request(
                self.runtime.client,
                message,
                collected,
                request,
            )
            return
        key = str(request_id)
        pending = _PendingApproval(request_id, method, params)
        with self._pending_approval_lock:
            if key in self._pending_approvals:
                _decline_server_request(
                    self.runtime.client,
                    message,
                    collected,
                    request,
                )
                return
            self._pending_approvals[key] = pending
        try:
            if self._approval_bridge is None:
                raise UnsupportedSessionCapability(
                    "Codex approval bridge is unavailable"
                )
            decision = self._approval_bridge(
                {
                    "id": request_id,
                    "method": method,
                    "params": params,
                    "timeout_seconds": timeout_seconds,
                }
            )
            normalized = _normalize_provider_decision(decision)
        except Exception:
            normalized = "decline"
            _publish(
                request,
                collected,
                HarnessEvent(
                    type=HarnessEventType.WARNING.value,
                    message="Codex approval bridge failed closed.",
                    payload={"method": method, "enforcement": "fail_closed"},
                ),
            )
        with self._pending_approval_lock:
            current = self._pending_approvals.pop(key, None)
        if current is None:
            return
        self.runtime.client.respond(
            request_id,
            result=_approval_response(method, normalized, params),
        )


class _StdioJsonRpcClient:
    """Own one app-server stdio process and demultiplex JSON-RPC messages."""

    def __init__(
        self,
        *,
        command: tuple[str, ...],
        env: Mapping[str, str],
        cwd: str,
        runtime_id: str,
    ) -> None:
        self.runtime_id = runtime_id
        self.command = command
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=dict(env),
            cwd=cwd,
            start_new_session=True,
            bufsize=1,
        )
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[str | int, queue.Queue[Mapping[str, Any]]] = {}
        self._messages: queue.Queue[Mapping[str, Any]] = queue.Queue()
        self._next_id = 1
        self._stderr: list[str] = []
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "gpt2giga-harness",
                    "title": "gpt2giga Harness",
                    "version": "1",
                },
                "capabilities": {"experimentalApi": False},
            },
            timeout=APP_SERVER_TIMEOUT_SECONDS,
        )
        self._send({"method": "initialized"})

    @property
    def alive(self) -> bool:
        return self._process.poll() is None

    def request(
        self, method: str, params: Mapping[str, Any], *, timeout: float
    ) -> Mapping[str, Any]:
        request_id = self._allocate_id()
        response_queue: queue.Queue[Mapping[str, Any]] = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._pending[request_id] = response_queue
        self._send({"id": request_id, "method": method, "params": dict(params)})
        try:
            response = response_queue.get(timeout=timeout)
        except queue.Empty as exc:
            raise AppServerProtocolError(
                f"Codex app-server request timed out: {method}"
            ) from exc
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)
        if "error" in response:
            raise AppServerProtocolError(
                f"Codex app-server {method} failed: "
                f"{redact_secrets(response.get('error'))}"
            )
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise AppServerProtocolError(
                f"Codex app-server {method} returned an invalid result"
            )
        return dict(result)

    def next_message(self, *, timeout: float) -> Mapping[str, Any] | None:
        try:
            return self._messages.get(timeout=max(timeout, 0.0))
        except queue.Empty:
            return None

    def respond(
        self,
        request_id: str | int,
        *,
        result: Mapping[str, Any] | None = None,
        error: Mapping[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {"id": request_id}
        if error is not None:
            payload["error"] = dict(error)
        else:
            payload["result"] = dict(result or {})
        self._send(payload)

    def close(self) -> None:
        if self._process.poll() is not None:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=2.0)

    def _allocate_id(self) -> int:
        with self._pending_lock:
            request_id = self._next_id
            self._next_id += 1
            return request_id

    def _send(self, payload: Mapping[str, Any]) -> None:
        if self._process.stdin is None or not self.alive:
            raise AppServerProtocolError("Codex app-server transport is closed")
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._write_lock:
            self._process.stdin.write(line)
            self._process.stdin.flush()

    def _read_stdout(self) -> None:
        if self._process.stdout is None:
            return
        for line in self._process.stdout:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, Mapping):
                continue
            request_id = payload.get("id")
            if request_id is not None and "method" not in payload:
                with self._pending_lock:
                    target = self._pending.get(request_id)
                if target is not None:
                    target.put(dict(payload))
                    continue
            self._messages.put(dict(payload))

    def _read_stderr(self) -> None:
        if self._process.stderr is None:
            return
        for line in self._process.stderr:
            self._stderr.append(line)
            total = sum(len(item) for item in self._stderr)
            while self._stderr and total > APP_SERVER_STDERR_CHARS:
                total -= len(self._stderr.pop(0))


def build_execution_snapshot(
    request: HarnessRequest,
    *,
    managed_home_id: str,
) -> dict[str, Any]:
    """Build the immutable public identity required for continued turns."""
    managed_mcp = _mapping(request.extra.get("managed_mcp_snapshot"))
    workspace_execution = _mapping(request.extra.get("workspace_execution"))
    content = {
        "schema_version": 1,
        "harness_id": "codex-cli",
        "api_mode": request.api_mode.value,
        "model": request.model,
        "workspace": request.workspace,
        "source_workspace": workspace_execution.get("source_workspace"),
        "permission_mode": request.mode,
        "managed_home_id": managed_home_id,
        "tool_snapshot_id": managed_mcp.get("snapshot_id"),
        "tool_snapshot_hash": managed_mcp.get("snapshot_hash"),
    }
    return {**content, "snapshot_hash": _json_hash(content)}


def build_structured_execution_snapshot(
    legacy_snapshot: Mapping[str, Any],
    *,
    adapter_version: str,
    cli_version: str | None = None,
) -> ExecutionSnapshot:
    """Project one verified Codex continuity snapshot into the neutral contract."""
    snapshot = dict(legacy_snapshot)
    supplied_hash = str(snapshot.pop("snapshot_hash", ""))
    if supplied_hash != _json_hash(snapshot):
        raise ValueError("Codex app-server execution snapshot hash mismatch")
    if snapshot.get("harness_id") != "codex-cli":
        raise ValueError("Codex structured snapshot has the wrong adapter identity")
    api_mode = str(snapshot.get("api_mode") or "unknown")
    model = str(snapshot.get("model") or "unknown")
    route_revision = _json_hash({"api_mode": api_mode, "model": model})
    provider = ProviderRef(
        "gpt2giga-harness",
        _identity_value(f"api-{api_mode}", prefix="provider"),
    )
    route = RouteRef(
        f"route-{route_revision[:24]}",
        route_revision,
        provider,
    )
    source_workspace = str(
        snapshot.get("source_workspace") or snapshot.get("workspace") or "unknown"
    )
    effective_workspace = str(snapshot.get("workspace") or source_workspace)
    workspace_id = f"workspace-{_json_hash({'path': source_workspace})[:24]}"
    worktree_id = (
        f"worktree-{_json_hash({'path': effective_workspace})[:24]}"
        if effective_workspace != source_workspace
        else None
    )
    extension_hash = str(snapshot.get("tool_snapshot_hash") or "")
    if len(extension_hash) != 64:
        extension_hash = EMPTY_EXTENSION_SNAPSHOT_HASH
    capability_evidence = (
        SnapshotEvidenceRef(
            "codex-app-server",
            cli_version or adapter_version,
            "supported",
            "codex-cli-probe",
        ),
    )
    return create_execution_snapshot(
        provider=provider,
        route=route,
        harness_id="codex-cli",
        harness_version=adapter_version,
        transport=ExecutionTransport.NATIVE_STRUCTURED,
        interaction_mode=InteractionMode.INTERACTIVE,
        runtime_ownership=RuntimeOwnership.DURABLE,
        workspace_id=workspace_id,
        worktree_id=worktree_id,
        permission_profile=_identity_value(
            snapshot.get("permission_mode"),
            prefix="permission",
        ),
        extension_snapshot_hash=extension_hash,
        capability_evidence=capability_evidence,
        classification=ExecutionClassification(
            status=ExecutionClassificationStatus.EXPLICIT,
            source="codex_app_server_driver",
            evidence=(f"snapshot-{supplied_hash[:24]}",),
        ),
    )


def _thread_identity_params(request: HarnessRequest) -> dict[str, Any]:
    return {
        "cwd": request.workspace,
        "model": request.model,
        "modelProvider": "gpt2giga_harness",
        "sandbox": "workspace-write" if request.mode == "edit" else "read-only",
        "approvalPolicy": "on-request",
    }


def _approval_contract(
    method: str,
    params: Mapping[str, Any],
) -> tuple[PermissionAction, str, dict[str, Any]]:
    """Map a reviewed Codex request family to one bounded Harness decision."""
    if method == "item/commandExecution/requestApproval":
        network = bool(_mapping(params.get("networkApprovalContext")))
        action = (
            PermissionAction.NETWORK_CONNECT
            if network
            else PermissionAction.PROCESS_SPAWN
        )
        return (
            action,
            "Codex requested approval for a command execution.",
            {
                "provider_method": method,
                "item_id": _bounded_text(params.get("itemId"), 256),
                "command": _bounded_text(params.get("command"), 2048),
                "cwd": _bounded_text(params.get("cwd"), 1024),
                "network_access": network,
            },
        )
    if method == "item/fileChange/requestApproval":
        return (
            PermissionAction.WORKSPACE_WRITE,
            "Codex requested approval for a file change.",
            {
                "provider_method": method,
                "item_id": _bounded_text(params.get("itemId"), 256),
                "reason": _bounded_text(params.get("reason"), 1024),
                "grant_root": _bounded_text(params.get("grantRoot"), 1024),
            },
        )
    if method == "item/permissions/requestApproval":
        permissions = _mapping(params.get("permissions"))
        network = bool(_mapping(permissions.get("network")).get("enabled"))
        return (
            (
                PermissionAction.NETWORK_CONNECT
                if network
                else PermissionAction.WORKSPACE_WRITE
            ),
            "Codex requested additional sandbox permissions.",
            {
                "provider_method": method,
                "item_id": _bounded_text(params.get("itemId"), 256),
                "network_access": network,
                "permission_snapshot_sha256": _json_hash(permissions),
            },
        )
    raise UnsupportedSessionCapability("Codex approval request method is unsupported")


def _provider_approval_binding(
    method: str,
    request_id: Any,
    params: Mapping[str, Any],
) -> str:
    """Build an ephemeral exact-operation binding; only its hash is persisted."""
    return json.dumps(
        {
            "protocol": APP_SERVER_PROTOCOL,
            "method": method,
            "request_id": request_id,
            "thread_id": params.get("threadId"),
            "turn_id": params.get("turnId"),
            "item_id": params.get("itemId"),
            "params_sha256": _json_hash(params),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _approval_response(
    method: str,
    decision: str,
    params: Mapping[str, Any],
) -> dict[str, Any]:
    """Project one normalized decision into the exact Codex response shape."""
    normalized = _normalize_provider_decision(decision)
    if method in {
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
    }:
        return {"decision": normalized}
    if method == "item/permissions/requestApproval":
        return {
            "permissions": (
                _mapping(params.get("permissions")) if normalized == "accept" else {}
            ),
            "scope": "turn",
        }
    raise UnsupportedSessionCapability("Codex approval response method is unsupported")


def _normalize_provider_decision(value: Any) -> str:
    aliases = {
        "accept": "accept",
        "allow": "accept",
        ApprovalDecision.ALLOW_ONCE.value: "accept",
        "decline": "decline",
        "deny": "decline",
        ApprovalDecision.DENY.value: "decline",
        "cancel": "cancel",
        "timeout": "decline",
    }
    try:
        return aliases[str(value)]
    except KeyError as exc:
        raise ValueError("Codex approval decision is invalid") from exc


def _bounded_text(value: Any, limit: int) -> str | None:
    text = _optional_text(value)
    return text[:limit] if text is not None else None


def _matching_turn_status(
    thread: Mapping[str, Any],
    turn_id: str | None,
) -> str | None:
    if turn_id is None:
        return None
    turns = thread.get("turns")
    if not isinstance(turns, list):
        return None
    for item in reversed(turns):
        turn = _mapping(item)
        if str(turn.get("id") or "") != turn_id:
            continue
        status = str(turn.get("status") or "").strip().lower()
        return status or None
    return None


def _normalize_notification(
    method: str, params: Mapping[str, Any]
) -> tuple[HarnessEvent | None, str | None]:
    if method == "thread/started":
        thread = _mapping(params.get("thread"))
        return (
            HarnessEvent(
                type=HarnessEventType.EXTERNAL_THREAD_STARTED.value,
                message="Codex app-server thread started.",
                payload={"thread_id": thread.get("id") or params.get("threadId")},
            ),
            None,
        )
    if method == "thread/status/changed":
        return (
            HarnessEvent(
                type=HarnessEventType.EXTERNAL_THREAD_STATUS.value,
                message="Codex app-server thread status changed.",
                payload={"status": params.get("status")},
            ),
            None,
        )
    if method == "thread/tokenUsage/updated":
        token_usage = _mapping(params.get("tokenUsage"))
        usage = _mapping(token_usage.get("last")) or token_usage
        aliases = {
            "input_tokens": "inputTokens",
            "output_tokens": "outputTokens",
            "total_tokens": "totalTokens",
            "cached_input_tokens": "cachedInputTokens",
            "reasoning_output_tokens": "reasoningOutputTokens",
        }
        payload = {
            target: usage[source]
            for target, source in aliases.items()
            if isinstance(usage.get(source), int)
        }
        return (
            HarnessEvent(
                type=HarnessEventType.USAGE.value,
                message="Codex app-server updated token usage.",
                payload=payload,
            )
            if payload
            else None,
            None,
        )
    if method == "turn/started":
        turn = _mapping(params.get("turn"))
        return (
            HarnessEvent(
                type=HarnessEventType.EXTERNAL_TURN_STARTED.value,
                message="Codex app-server turn started.",
                payload={"turn_id": turn.get("id"), "status": turn.get("status")},
            ),
            None,
        )
    if method == "turn/plan/updated":
        plan = []
        for item in params.get("plan") or ():
            if not isinstance(item, Mapping):
                continue
            step = str(item.get("step") or "").strip()
            if not step:
                continue
            status = {
                "inProgress": "in_progress",
                "completed": "completed",
                "pending": "pending",
            }.get(str(item.get("status") or ""), "pending")
            plan.append({"step": step, "status": status})
        return (
            HarnessEvent(
                type="plan_updated",
                message="Codex app-server updated the execution plan.",
                payload={
                    "tool_call_id": f"plan:{params.get('turnId') or 'current'}",
                    "name": "update_plan",
                    "status": "running",
                    "arguments": {"plan": plan},
                },
            ),
            None,
        )
    if method == "turn/completed":
        turn = _mapping(params.get("turn"))
        return (
            HarnessEvent(
                type=HarnessEventType.EXTERNAL_TURN_COMPLETED.value,
                message="Codex app-server turn completed.",
                payload={"turn_id": turn.get("id"), "status": turn.get("status")},
            ),
            _turn_text(turn) or None,
        )
    if method == "error":
        error = params.get("error") or params.get("message") or "Codex app-server error"
        return (
            HarnessEvent(
                type=HarnessEventType.ERROR.value,
                message="Codex app-server reported an error.",
                payload={"error": error},
            ),
            None,
        )
    if method == "item/agentMessage/delta":
        delta = str(params.get("delta") or "")
        return (
            HarnessEvent(
                type=HarnessEventType.MESSAGE_DELTA.value,
                message="Codex app-server streamed assistant text.",
                payload={"delta": delta},
            )
            if delta
            else None,
            None,
        )
    if method in {
        "item/reasoning/summaryTextDelta",
        "item/reasoning/textDelta",
    }:
        delta = str(params.get("delta") or "")
        return (
            HarnessEvent(
                type=HarnessEventType.REASONING_DELTA.value,
                message="Codex app-server streamed reasoning text.",
                payload={
                    "delta": delta,
                    "item_id": params.get("itemId"),
                    "kind": (
                        "summary" if method.endswith("summaryTextDelta") else "text"
                    ),
                },
            )
            if delta
            else None,
            None,
        )
    if method not in {"item/started", "item/completed"}:
        return None, None
    item = _mapping(params.get("item"))
    item_type = str(item.get("type") or "")
    if item_type == "agentMessage":
        text = str(item.get("text") or "")
        return None, text or None
    if item_type == "fileChange" and method == "item/completed":
        return (
            HarnessEvent(
                type=HarnessEventType.FILE_CHANGED.value,
                message="Codex app-server completed a file change.",
                payload={
                    "item_id": item.get("id"),
                    "status": item.get("status"),
                    "changes": item.get("changes") or [],
                },
            ),
            None,
        )
    tool_name = _tool_name(item)
    if tool_name is None:
        return None, None
    event_type = (
        HarnessEventType.TOOL_CALL_STARTED.value
        if method == "item/started"
        else HarnessEventType.TOOL_CALL_FINISHED.value
    )
    return (
        HarnessEvent(
            type=event_type,
            message=(
                f"Codex app-server started {tool_name}."
                if method == "item/started"
                else f"Codex app-server finished {tool_name}."
            ),
            payload={
                "tool_call_id": item.get("id"),
                "name": tool_name,
                "status": item.get("status"),
                "arguments": _tool_arguments(item),
                **(
                    {"result": result}
                    if method == "item/completed"
                    and (result := _tool_result(item)) is not None
                    else {}
                ),
            },
        ),
        None,
    )


def _decline_server_request(
    client: AppServerClient,
    message: Mapping[str, Any],
    collected: list[HarnessEvent],
    request: HarnessRequest,
) -> None:
    request_id = message.get("id")
    if not isinstance(request_id, (str, int)):
        return
    method = str(message.get("method") or "")
    if method in {
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
    }:
        client.respond(request_id, result={"decision": "decline"})
    elif method == "item/permissions/requestApproval":
        client.respond(request_id, result={"permissions": {}, "scope": "turn"})
    elif method == "mcpServer/elicitation/request":
        client.respond(request_id, result={"action": "decline"})
    elif method == "item/tool/requestUserInput":
        client.respond(request_id, result={"answers": {}})
    else:
        client.respond(
            request_id,
            error={"code": -32001, "message": "Harness client input unavailable"},
        )
    _publish(
        request,
        collected,
        HarnessEvent(
            type=HarnessEventType.WARNING.value,
            message="Codex app-server request was declined by the headless client.",
            payload={"method": method, "enforcement": "fail_closed"},
        ),
    )


def _tool_name(item: Mapping[str, Any]) -> str | None:
    item_type = str(item.get("type") or "")
    if item_type == "commandExecution":
        return "shell"
    if item_type == "mcpToolCall":
        return f"{item.get('server')}.{item.get('tool')}"
    if item_type == "dynamicToolCall":
        return str(item.get("tool") or "dynamic_tool")
    if item_type == "webSearch":
        return "web_search"
    if item_type == "collabToolCall":
        return _collab_tool(item)
    return None


def _tool_arguments(item: Mapping[str, Any]) -> Any:
    item_type = str(item.get("type") or "")
    if item_type == "commandExecution":
        return {"command": item.get("command"), "cwd": item.get("cwd")}
    if item_type == "webSearch":
        return {"query": item.get("query")}
    if item_type == "collabToolCall":
        return {
            "prompt": item.get("prompt"),
            "subagents": item.get("subagents") or _collab_agent_states(item),
        }
    return item.get("arguments") or {}


def _tool_result(item: Mapping[str, Any]) -> Any:
    for key in (
        "aggregatedOutput",
        "aggregated_output",
        "output",
        "result",
        "error",
    ):
        value = item.get(key)
        if value not in (None, "", (), [], {}):
            return value
    if str(item.get("status") or "").lower() in {"failed", "error"}:
        failure = {
            key: item[key]
            for key in (
                "exitCode",
                "exit_code",
                "stderr",
                "failureReason",
                "failure_reason",
            )
            if item.get(key) not in (None, "", (), [], {})
        }
        return failure or {"error": "Tool failed without diagnostic output."}
    return None


def _collab_tool(item: Mapping[str, Any]) -> str | None:
    value = str(item.get("tool") or "").strip()
    if not value:
        return None
    aliases = {
        "spawnAgent": "spawn_agent",
        "sendInput": "send_input",
        "resumeAgent": "resume_agent",
        "closeAgent": "close_agent",
    }
    return aliases.get(value, value)


def _collab_thread_ids(item: Mapping[str, Any]) -> tuple[str, ...]:
    values = item.get("receiverThreadIds") or item.get("receiver_thread_ids") or ()
    if not isinstance(values, (list, tuple)):
        values = (values,)
    candidates = [
        *values,
        item.get("receiverThreadId"),
        item.get("receiver_thread_id"),
        item.get("newThreadId"),
        item.get("new_thread_id"),
    ]
    return tuple(
        dict.fromkeys(
            text for value in candidates if (text := str(value or "").strip())
        )
    )


def _collab_agent_states(item: Mapping[str, Any]) -> list[dict[str, Any]]:
    states = _mapping(item.get("agentsStates") or item.get("agents_states"))
    return [
        {
            "id": thread_id,
            "status": _mapping(state).get("status"),
            "message": _mapping(state).get("message"),
        }
        for thread_id, state in states.items()
    ]


def _read_collab_subagents(
    client: AppServerClient,
    item: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    states = {str(entry.get("id")): entry for entry in _collab_agent_states(item)}
    snapshots: list[dict[str, Any]] = []
    for thread_id in _collab_thread_ids(item):
        try:
            response = client.request(
                "thread/read",
                {"threadId": thread_id, "includeTurns": True},
                timeout=APP_SERVER_TIMEOUT_SECONDS,
            )
        except (AppServerProtocolError, OSError, RuntimeError, ValueError):
            thread = {}
        else:
            thread = _mapping(response.get("thread"))
        state = states.get(thread_id, {})
        snapshots.append(
            {
                "id": thread_id,
                "name": (
                    thread.get("agentNickname")
                    or thread.get("agent_nickname")
                    or thread_id[:8]
                ),
                "role": thread.get("agentRole") or thread.get("agent_role"),
                "status": state.get("status")
                or _mapping(thread.get("status")).get("type"),
                "message": state.get("message"),
                "prompt": item.get("prompt"),
                "turns": thread.get("turns") or [],
            }
        )
    return tuple(snapshots)


def _public_collab_subagent(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: snapshot.get(key)
        for key in ("id", "name", "role", "status", "message", "prompt")
        if snapshot.get(key) is not None
    }


def _collab_child_tool_events(
    snapshots: tuple[dict[str, Any], ...],
    *,
    subagent_parents: Mapping[str, str],
    seen: set[tuple[str, str, str]],
) -> tuple[HarnessEvent, ...]:
    events: list[HarnessEvent] = []
    for snapshot in snapshots:
        child_id = str(snapshot.get("id") or "")
        parent_id = subagent_parents.get(child_id)
        if not child_id or not parent_id:
            continue
        for turn in snapshot.get("turns") or ():
            if not isinstance(turn, Mapping):
                continue
            for item in turn.get("items") or ():
                if not isinstance(item, Mapping):
                    continue
                name = _tool_name(item)
                item_id = str(item.get("id") or "").strip()
                if name is None or not item_id:
                    continue
                status = str(item.get("status") or "completed")
                event_type = (
                    HarnessEventType.TOOL_CALL_STARTED.value
                    if status in {"inProgress", "in_progress", "running"}
                    else HarnessEventType.TOOL_CALL_FINISHED.value
                )
                identity = (child_id, item_id, event_type)
                if identity in seen:
                    continue
                seen.add(identity)
                payload = {
                    "tool_call_id": f"{child_id}:{item_id}",
                    "parent_tool_call_id": parent_id,
                    "name": name,
                    "status": status,
                    "arguments": _tool_arguments(item),
                    "source": "codex-app-server-subagent",
                    "subagent_id": child_id,
                    "subagent_name": snapshot.get("name"),
                    "subagent_role": snapshot.get("role"),
                    "subagent_description": snapshot.get("prompt"),
                }
                result = _tool_result(item)
                if (
                    event_type == HarnessEventType.TOOL_CALL_FINISHED.value
                    and result is not None
                ):
                    payload["result"] = result
                events.append(
                    HarnessEvent(
                        type=event_type,
                        message=f"Codex subagent {snapshot.get('name')} ran {name}.",
                        payload=payload,
                    )
                )
    return tuple(events)


def _rollout_multi_agent_events(
    client: AppServerClient,
    *,
    home: Path,
    thread_id: str,
    turn_id: str,
    seen_tool_call_ids: set[str],
) -> tuple[HarnessEvent, ...]:
    """Recover multi-agent calls omitted from Codex app-server thread items."""
    try:
        response = client.request(
            "thread/read",
            {"threadId": thread_id, "includeTurns": True},
            timeout=APP_SERVER_TIMEOUT_SECONDS,
        )
    except (AppServerProtocolError, OSError, RuntimeError, ValueError):
        return ()
    thread = _mapping(response.get("thread"))
    rollout_path = _managed_rollout_path(home, thread.get("path"))
    if rollout_path is None:
        return ()

    events: list[HarnessEvent] = []
    child_seen: set[tuple[str, str, str]] = set()
    for call in _read_rollout_multi_agent_calls(rollout_path, turn_id=turn_id):
        call_id = str(call.get("call_id") or call.get("id") or "").strip()
        if not call_id or call_id in seen_tool_call_ids:
            continue
        name = str(call.get("name") or "").strip()
        arguments = _json_value(call.get("arguments"), fallback={})
        if not isinstance(arguments, Mapping):
            arguments = {"value": arguments}
        public_arguments: dict[str, Any] = dict(arguments)
        result = _json_value(call.get("output"), fallback=call.get("output"))
        child_snapshots: tuple[dict[str, Any], ...] = ()
        if name == "spawn_agent" and isinstance(result, Mapping):
            child_id = str(
                result.get("agent_id") or result.get("thread_id") or ""
            ).strip()
            if child_id:
                prompt = str(
                    public_arguments.get("message")
                    or public_arguments.get("prompt")
                    or ""
                ).strip()
                child_snapshots = (
                    _read_function_subagent(
                        client,
                        thread_id=child_id,
                        prompt=prompt or None,
                        fallback_name=str(result.get("nickname") or "").strip() or None,
                    ),
                )
                public_arguments.update(
                    {
                        "prompt": prompt or None,
                        "subagents": [
                            _public_collab_subagent(snapshot)
                            for snapshot in child_snapshots
                        ],
                    }
                )
        payload: dict[str, Any] = {
            "tool_call_id": call_id,
            "name": name,
            "status": "completed",
            "arguments": public_arguments,
            "source": "codex-app-server-rollout",
        }
        if result not in (None, "", (), [], {}):
            payload["result"] = result
        events.append(
            HarnessEvent(
                type=HarnessEventType.TOOL_CALL_FINISHED.value,
                message=f"Codex app-server finished {name}.",
                payload=payload,
            )
        )
        seen_tool_call_ids.add(call_id)
        if child_snapshots:
            child_id = str(child_snapshots[0].get("id") or "")
            events.extend(
                _collab_child_tool_events(
                    child_snapshots,
                    subagent_parents={child_id: call_id},
                    seen=child_seen,
                )
            )
    return tuple(events)


def _managed_rollout_path(home: Path, value: Any) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        resolved_home = home.expanduser().resolve()
        path = Path(text).expanduser().resolve(strict=True)
    except OSError:
        return None
    if not path.is_file() or not path.is_relative_to(resolved_home):
        return None
    return path


def _read_rollout_multi_agent_calls(
    path: Path,
    *,
    turn_id: str,
) -> tuple[dict[str, Any], ...]:
    calls: dict[str, dict[str, Any]] = {}
    active_turn_id: str | None = None
    try:
        lines = path.open(encoding="utf-8")
    except OSError:
        return ()
    try:
        with lines:
            for line in lines:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, Mapping):
                    continue
                record_type = str(record.get("type") or "")
                payload = _mapping(record.get("payload"))
                if record_type == "event_msg" and payload.get("type") == "task_started":
                    active_turn_id = str(payload.get("turn_id") or "") or None
                    continue
                if record_type == "turn_context":
                    active_turn_id = str(payload.get("turn_id") or "") or active_turn_id
                    continue
                if record_type != "response_item":
                    continue
                metadata = _mapping(
                    payload.get("internal_chat_message_metadata_passthrough")
                )
                payload_turn_id = str(metadata.get("turn_id") or active_turn_id or "")
                if payload_turn_id != turn_id:
                    continue
                payload_type = str(payload.get("type") or "")
                call_id = str(payload.get("call_id") or "").strip()
                if payload_type == "function_call":
                    if str(payload.get("namespace") or "") != "multi_agent_v1":
                        continue
                    if not call_id:
                        call_id = str(payload.get("id") or "").strip()
                    if not call_id:
                        continue
                    calls[call_id] = {
                        "id": payload.get("id"),
                        "call_id": call_id,
                        "name": _multi_agent_tool_name(payload.get("name")),
                        "arguments": payload.get("arguments"),
                    }
                elif payload_type == "function_call_output" and call_id in calls:
                    calls[call_id]["output"] = payload.get("output")
    except OSError:
        return ()
    return tuple(calls.values())


def _multi_agent_tool_name(value: Any) -> str:
    name = str(value or "").strip()
    for prefix in ("multi_agent_v1__", "multi_agent_v1."):
        if name.startswith(prefix):
            name = name[len(prefix) :]
            break
    aliases = {
        "spawnAgent": "spawn_agent",
        "sendInput": "send_input",
        "resumeAgent": "resume_agent",
        "closeAgent": "close_agent",
    }
    return aliases.get(name, name)


def _json_value(value: Any, *, fallback: Any) -> Any:
    if not isinstance(value, str):
        return value if value is not None else fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _read_function_subagent(
    client: AppServerClient,
    *,
    thread_id: str,
    prompt: str | None,
    fallback_name: str | None,
) -> dict[str, Any]:
    try:
        response = client.request(
            "thread/read",
            {"threadId": thread_id, "includeTurns": True},
            timeout=APP_SERVER_TIMEOUT_SECONDS,
        )
    except (AppServerProtocolError, OSError, RuntimeError, ValueError):
        thread = {}
    else:
        thread = _mapping(response.get("thread"))
    turns = thread.get("turns") or []
    latest_turn = _mapping(turns[-1]) if turns else {}
    return {
        "id": thread_id,
        "name": (
            thread.get("agentNickname")
            or thread.get("agent_nickname")
            or fallback_name
            or thread_id[:8]
        ),
        "role": thread.get("agentRole") or thread.get("agent_role"),
        "status": latest_turn.get("status")
        or _mapping(thread.get("status")).get("type"),
        "prompt": prompt,
        "turns": turns,
    }


def _turn_text(turn: Mapping[str, Any]) -> str:
    for item in reversed(tuple(turn.get("items") or ())):
        if isinstance(item, Mapping) and item.get("type") == "agentMessage":
            text = str(item.get("text") or "")
            if text:
                return text
    return ""


def _thread_id(response: Mapping[str, Any]) -> str:
    thread = _mapping(response.get("thread"))
    thread_id = str(thread.get("id") or "").strip()
    if not thread_id:
        raise AppServerProtocolError("Codex app-server returned no thread id")
    return thread_id


def _turn_id(response: Mapping[str, Any]) -> str:
    turn = _mapping(response.get("turn"))
    turn_id = str(turn.get("id") or "").strip()
    if not turn_id:
        raise AppServerProtocolError("Codex app-server returned no turn id")
    return turn_id


def _validate_link_snapshot(
    link: Mapping[str, Any], snapshot: Mapping[str, Any]
) -> None:
    expected = str(link.get("snapshot_hash") or "")
    current = str(snapshot.get("snapshot_hash") or "")
    if expected != current:
        raise ValueError(
            "Codex app-server continuation changed route, model, workspace, "
            "permission mode, managed home, or tool snapshot; fork explicitly."
        )


def _public_link(link: Mapping[str, Any] | None) -> dict[str, Any]:
    if link is None:
        return {}
    return {
        key: value
        for key, value in link.items()
        if key
        not in {
            "last_prompt_id",
        }
    }


def _scope_id(command: tuple[str, ...], snapshot: Mapping[str, Any]) -> str:
    value = {
        "command": list(command),
        "cli_version": snapshot.get("cli_version"),
        "api_mode": snapshot.get("api_mode"),
        "managed_home_id": snapshot.get("managed_home_id"),
        "tool_snapshot_hash": snapshot.get("tool_snapshot_hash"),
    }
    return _json_hash(value)[:24]


def _write_provider_config(
    home: Path,
    request: HarnessRequest,
    context: HarnessContext,
) -> None:
    model = request.model or context.default_model or "GigaChat"
    options = _mapping(request.extra.get("agent_adapter_options"))
    effort = str(options.get("reasoning_effort") or "none")
    if effort not in {"none", "low", "medium", "high"}:
        effort = "none"
    base_url = context.api_base_url(request.api_mode)
    config = (
        f'model = "{_toml_escape(model)}"\n'
        'model_provider = "gpt2giga_harness"\n'
        f'model_reasoning_effort = "{effort}"\n\n'
        "[model_providers.gpt2giga_harness]\n"
        'name = "gpt2giga_harness"\n'
        f'base_url = "{_toml_escape(base_url)}"\n'
        'env_key = "GPT2GIGA_API_KEY"\n'
        'wire_api = "responses"\n'
        "supports_websockets = false\n"
    )
    write_startup_config("codex-cli", home, config)


def _publish(
    request: HarnessRequest,
    collected: list[HarnessEvent],
    event: HarnessEvent,
) -> None:
    if not emit_event(request, event):
        collected.append(event)


def _cancel_requested(cancel_event: Any | None) -> bool:
    if cancel_event is None:
        return False
    is_set = getattr(cancel_event, "is_set", None)
    return bool(is_set()) if callable(is_set) else False


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _structured_link_id(session_id: str) -> str:
    return f"codex-link-{hashlib.sha256(session_id.encode('utf-8')).hexdigest()[:32]}"


def _adapter_version() -> str:
    try:
        value = metadata.version("gpt2giga-harness")
    except metadata.PackageNotFoundError:
        value = "unknown"
    return _driver_version(value)


def _driver_version(value: Any) -> str:
    return _identity_value(value or "unknown", prefix="version")


def _identity_value(value: Any, *, prefix: str) -> str:
    text = str(value or "").strip()
    allowed = frozenset(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:@+~-"
    )
    if (
        text
        and len(text) <= 256
        and text[0].isalnum()
        and all(character in allowed for character in text)
    ):
        return text
    return f"{prefix}-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:24]}"


def _safe_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _json_hash(value: Mapping[str, Any]) -> str:
    content = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(raw_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)
