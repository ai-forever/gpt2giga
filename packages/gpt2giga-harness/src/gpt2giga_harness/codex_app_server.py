"""Supervised Codex app-server continuity for normalized Harness sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
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
from gpt2giga_harness.harnesses.agent_cli import build_safe_env
from gpt2giga_harness.managed_mcp import (
    clear_headless_mcp_materialization,
    materialize_headless_mcp_snapshot,
    write_startup_config,
)
from gpt2giga_harness.sessions.locking import exclusive_file_lock
from gpt2giga_harness.sessions.store import utc_now
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
        self.client_factory = client_factory or _StdioJsonRpcClient
        self._runtimes: dict[str, _Runtime] = {}
        self._runtime_lock = threading.Lock()

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
        scope_id = _scope_id(command, snapshot)
        runtime = self._runtime_for(
            scope_id,
            command=command,
            request=request,
            context=context,
            snapshot=snapshot,
        )
        command_display = (*command, "app-server", "--stdio", "--strict-config")
        with runtime.turn_lock:
            return self._run_locked(
                runtime,
                request,
                context,
                prompt=prompt,
                prompt_id=prompt_id,
                continuation=continuation,
                snapshot=snapshot,
                command_display=command_display,
            )

    def _run_locked(
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

        action = str(continuation.get("action") or "start")
        recovery_outcome = "not_required"
        try:
            if action == "fork":
                source_thread_id = str(
                    continuation.get("fork_thread_id")
                    or _mapping(continuation.get("fork")).get("thread_id")
                    or ""
                ).strip()
                if not source_thread_id:
                    raise ValueError(
                        "Codex app-server fork requires a source thread id"
                    )
                response = runtime.client.request(
                    "thread/fork",
                    {
                        **_thread_identity_params(request),
                        "threadId": source_thread_id,
                        "lastTurnId": continuation.get("fork_turn_id"),
                        "excludeTurns": True,
                    },
                    timeout=APP_SERVER_TIMEOUT_SECONDS,
                )
                thread_id = _thread_id(response)
                forked_from = source_thread_id
                recovery_outcome = "forked"
            elif link is None:
                response = runtime.client.request(
                    "thread/start",
                    {
                        **_thread_identity_params(request),
                        "ephemeral": False,
                    },
                    timeout=APP_SERVER_TIMEOUT_SECONDS,
                )
                thread_id = _thread_id(response)
                forked_from = None
            else:
                thread_id = str(link.get("thread_id") or "").strip()
                if not thread_id:
                    raise AppServerProtocolError(
                        "Codex app-server link has no thread identity"
                    )
                forked_from = _optional_text(link.get("forked_from_thread_id"))
                if (
                    str(link.get("runtime_id") or "") != runtime.client.runtime_id
                    or thread_id not in runtime.loaded_threads
                ):
                    runtime.client.request(
                        "thread/read",
                        {"threadId": thread_id, "includeTurns": False},
                        timeout=APP_SERVER_TIMEOUT_SECONDS,
                    )
                    runtime.client.request(
                        "thread/resume",
                        {
                            **_thread_identity_params(request),
                            "threadId": thread_id,
                            "excludeTurns": True,
                        },
                        timeout=APP_SERVER_TIMEOUT_SECONDS,
                    )
                    recovery_outcome = "resumed_after_owner_change"
            runtime.loaded_threads.add(thread_id)
            now = utc_now()
            link = self.link_store.save(
                request.session_id,
                {
                    "schema_version": APP_SERVER_LINK_SCHEMA_VERSION,
                    "protocol": APP_SERVER_PROTOCOL,
                    "runtime_id": runtime.client.runtime_id,
                    "thread_id": thread_id,
                    "latest_turn_id": link.get("latest_turn_id") if link else None,
                    "forked_from_thread_id": forked_from,
                    "snapshot": dict(snapshot),
                    "snapshot_hash": snapshot["snapshot_hash"],
                    "runtime_status": "loaded",
                    "recovery_outcome": recovery_outcome,
                    "created_at": link.get("created_at") if link else now,
                    "resumed_at": now
                    if recovery_outcome.startswith("resumed")
                    else None,
                    "updated_at": now,
                    "last_prompt_id": link.get("last_prompt_id") if link else None,
                    "last_prompt_status": link.get("last_prompt_status")
                    if link
                    else None,
                },
            )
            turn_response = runtime.client.request(
                "turn/start",
                {
                    "threadId": thread_id,
                    "input": [{"type": "text", "text": prompt}],
                    "clientUserMessageId": prompt_id,
                    "model": request.model,
                    "cwd": request.workspace,
                    "approvalPolicy": "never",
                },
                timeout=APP_SERVER_TIMEOUT_SECONDS,
            )
            turn_id = _turn_id(turn_response)
            link = self.link_store.save(
                request.session_id,
                {
                    **link,
                    "latest_turn_id": turn_id,
                    "runtime_status": "turn_running",
                    "updated_at": utc_now(),
                    "last_prompt_id": prompt_id,
                    "last_prompt_status": "submitted",
                },
            )
            return self._wait_for_turn(
                runtime,
                request,
                context,
                thread_id=thread_id,
                turn_id=turn_id,
                link=link,
                command_display=command_display,
            )
        except Exception as exc:
            if link is not None:
                link = self.link_store.save(
                    request.session_id,
                    {
                        **link,
                        "runtime_status": "interrupted",
                        "recovery_outcome": "owner_error",
                        "updated_at": utc_now(),
                        "last_prompt_status": (
                            "interrupted"
                            if link.get("last_prompt_id") == prompt_id
                            else link.get("last_prompt_status")
                        ),
                    },
                )
            return HarnessResult(
                ok=False,
                text="",
                raw={"app_server_thread": _public_link(link)} if link else {},
                command=command_display,
                error=str(redact_secrets(str(exc))),
            )

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
    ) -> HarnessResult:
        collected: list[HarnessEvent] = []
        final_text = ""
        deadline = time.monotonic() + max(context.timeout_seconds, 0.1)
        interrupt_sent = False
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
                _decline_server_request(runtime.client, message, collected, request)
                continue
            if params.get("threadId") not in {None, thread_id}:
                continue
            if params.get("turnId") not in {None, turn_id}:
                continue
            event, item_text = _normalize_notification(method, params)
            if item_text is not None:
                final_text = item_text
            if event is not None:
                _publish(request, collected, event)
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


def _thread_identity_params(request: HarnessRequest) -> dict[str, Any]:
    return {
        "cwd": request.workspace,
        "model": request.model,
        "modelProvider": "gpt2giga_harness",
        "sandbox": "workspace-write" if request.mode == "edit" else "read-only",
        "approvalPolicy": "never",
    }


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
    return None


def _tool_arguments(item: Mapping[str, Any]) -> Any:
    item_type = str(item.get("type") or "")
    if item_type == "commandExecution":
        return {"command": item.get("command"), "cwd": item.get("cwd")}
    if item_type == "webSearch":
        return {"query": item.get("query")}
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
    return None


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
