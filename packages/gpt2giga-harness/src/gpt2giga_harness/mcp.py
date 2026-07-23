"""Safe MCP descriptors, inventory, discovery, and probe history."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
import os
from pathlib import Path
from queue import Empty, Queue
import signal
import subprocess
import tempfile
import threading
import time
from typing import Any, Mapping
from urllib.parse import urlsplit
from urllib import request as urllib_request

from gpt2giga_harness.project import ProjectToolProfile
from gpt2giga_harness.harnesses.agent_cli import build_safe_env
from gpt2giga_harness.sessions.locking import exclusive_file_lock
from gpt2giga_harness.sessions.redaction import redact_for_storage
from gpt2giga_harness.sessions.store import new_id, utc_now
from gpt2giga_harness.secrets import (
    SecretReference,
    SecretResolver,
    secret_reference_from_dict,
    secret_reference_to_dict,
)
from gpt2giga_harness.tools import (
    SecretResolutionError,
    ToolDescriptor,
    ToolExecutionPolicy,
    ToolRisk,
)
from gpt2giga_harness.types import HarnessContext


class MCPTransport(str, Enum):
    """Supported MCP connection transports."""

    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"
    SSE = "sse"


class MCPProbeStatus(str, Enum):
    """Stable health result for one connection probe."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ToolServerDescriptor:
    """MCP specialization of the shared tool provider contract."""

    id: str
    title: str
    transport: MCPTransport
    description: str = ""
    command: str | None = None
    args: tuple[str, ...] = ()
    cwd: str | None = None
    url: str | None = None
    environment: Mapping[str, str | SecretReference] = field(default_factory=dict)
    headers: Mapping[str, str | SecretReference] = field(default_factory=dict)
    instructions: str = ""
    source: str = "project"
    trusted: bool = False
    enabled: bool = False
    timeout_seconds: float = 10.0
    harnesses: tuple[str, ...] = ()
    execution_policy: ToolExecutionPolicy = field(
        default_factory=lambda: ToolExecutionPolicy(id="default")
    )
    tools: tuple[ToolDescriptor, ...] = ()

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.title.strip():
            raise ValueError("MCP server id and title must not be empty")
        if self.transport is MCPTransport.STDIO and not self.command:
            raise ValueError("stdio MCP servers require command")
        if (
            self.transport in {MCPTransport.STREAMABLE_HTTP, MCPTransport.SSE}
            and not self.url
        ):
            raise ValueError("remote MCP servers require url")
        if self.url:
            parsed_url = urlsplit(self.url)
            if (
                parsed_url.scheme not in {"http", "https"}
                or not parsed_url.hostname
                or parsed_url.username
                or parsed_url.password
                or parsed_url.fragment
            ):
                raise ValueError(
                    "MCP url must be an http(s) endpoint without userinfo or fragment"
                )
        if any(_is_sensitive_arg(item) for item in self.args):
            raise ValueError("sensitive MCP args must use an env/header secret_ref")
        if self.timeout_seconds <= 0:
            raise ValueError("MCP timeout_seconds must be positive")

    def list_tools(self) -> tuple[ToolDescriptor, ...]:
        """Return the most recently discovered tools."""
        return self.tools


@dataclass(frozen=True)
class MCPProbeResult:
    """One bounded, redaction-safe discovery result."""

    id: str
    server_id: str
    status: MCPProbeStatus
    started_at: str
    duration_ms: int
    error: str | None = None
    protocol_version: str | None = None
    server_name: str | None = None
    server_version: str | None = None
    instructions: str | None = None
    capabilities: Mapping[str, Any] = field(default_factory=dict)
    tools: tuple[ToolDescriptor, ...] = ()
    resources: tuple[Mapping[str, Any], ...] = ()
    prompts: tuple[Mapping[str, Any], ...] = ()


class MCPProbeHistoryStore:
    """Append-only JSONL history for bounded MCP health results."""

    def __init__(self, data_dir: str | Path) -> None:
        self.path = Path(data_dir).expanduser() / "tools" / "probe_history.jsonl"

    def append(self, result: MCPProbeResult) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_file_lock(self.path):
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(mcp_probe_to_dict(result), sort_keys=True))
                handle.write("\n")

    def list(
        self, server_id: str | None = None, *, limit: int = 20
    ) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with exclusive_file_lock(self.path):
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    item = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if server_id is None or item.get("server_id") == server_id:
                    rows.append(item)
        return rows[-max(1, min(limit, 100)) :][::-1]


def descriptor_from_profile(
    name: str, profile: ProjectToolProfile
) -> ToolServerDescriptor:
    """Parse one non-secret project profile into a strict MCP descriptor."""
    if profile.kind.lower() != "mcp":
        raise ValueError("tool profile kind must be mcp")
    config = profile.config
    transport = MCPTransport(str(config.get("transport") or "stdio"))
    policy_id = str(config.get("policy_id") or "default")
    risk_rules = _risk_rules(config.get("risk_policy"))
    tool_rules = _tool_rules(config.get("tool_policy"))
    return ToolServerDescriptor(
        id=name,
        title=profile.title or name,
        description=profile.description or "",
        transport=transport,
        command=_optional_text(config.get("command")),
        args=_string_tuple(config.get("args")),
        cwd=_optional_text(config.get("cwd")),
        url=_optional_text(config.get("url")),
        environment=_reference_mapping(config.get("env"), reject_secret_literals=True),
        headers=_reference_mapping(config.get("headers"), reject_secret_literals=True),
        instructions=_optional_text(config.get("instructions")) or "",
        trusted=bool(config.get("trusted", False)),
        enabled=profile.enabled,
        timeout_seconds=float(config.get("timeout_seconds") or 10.0),
        harnesses=profile.harnesses,
        execution_policy=ToolExecutionPolicy(
            id=policy_id,
            tool_rules=tool_rules,
            risk_rules=risk_rules,
        ),
    )


def build_mcp_inventory(
    profiles: Mapping[str, ProjectToolProfile],
) -> tuple[tuple[ToolServerDescriptor, ...], tuple[dict[str, str], ...]]:
    """Build valid descriptors while returning safe per-profile errors."""
    descriptors: list[ToolServerDescriptor] = []
    errors: list[dict[str, str]] = []
    for name, profile in profiles.items():
        if profile.kind.lower() != "mcp":
            continue
        try:
            descriptors.append(descriptor_from_profile(name, profile))
        except (TypeError, ValueError) as exc:
            errors.append({"server_id": name, "error": str(exc)})
    return tuple(descriptors), tuple(errors)


def probe_mcp_server(
    descriptor: ToolServerDescriptor,
    resolver: SecretResolver,
) -> MCPProbeResult:
    """Initialize and discover one MCP server without invoking any tool."""
    started_at = utc_now()
    started = time.monotonic()
    try:
        if not descriptor.enabled:
            raise ValueError("MCP server is disabled")
        owner = f"mcp-probe:{descriptor.id}"
        env = _resolve_values(descriptor.environment, resolver, owner=owner)
        headers = _resolve_values(descriptor.headers, resolver, owner=owner)
        if descriptor.transport is MCPTransport.STDIO:
            responses = _probe_stdio(descriptor, env)
        elif descriptor.transport is MCPTransport.SSE:
            raise ValueError("legacy SSE MCP probing requires a provider-native target")
        else:
            responses = _probe_http(descriptor, headers)
        initialize, raw_tools, raw_resources, raw_prompts = responses
        initialize = _required_response({1: initialize}, 1)
        tools = _optional_list_response(raw_tools, request_id=2, key="tools")
        resources = _optional_list_response(
            raw_resources, request_id=3, key="resources"
        )
        prompts = _optional_list_response(raw_prompts, request_id=4, key="prompts")
        result = initialize.get("result") or {}
        server_info = result.get("serverInfo") or {}
        discovered = tuple(
            _tool_descriptor(descriptor, item)
            for item in (tools.get("result") or {}).get("tools", [])[:200]
            if isinstance(item, Mapping) and item.get("name")
        )
        return MCPProbeResult(
            id=new_id("mcp_probe"),
            server_id=descriptor.id,
            status=MCPProbeStatus.HEALTHY,
            started_at=started_at,
            duration_ms=int((time.monotonic() - started) * 1000),
            protocol_version=_optional_text(result.get("protocolVersion")),
            server_name=_optional_text(server_info.get("name")),
            server_version=_optional_text(server_info.get("version")),
            instructions=(_optional_text(result.get("instructions")) or "")[:4000]
            or None,
            capabilities=redact_for_storage(result.get("capabilities") or {}),
            tools=discovered,
            resources=_safe_named_items(resources, "resources"),
            prompts=_safe_named_items(prompts, "prompts"),
        )
    except SecretResolutionError as exc:
        return _failed_probe(descriptor.id, started_at, started, str(exc), blocked=True)
    except (OSError, TimeoutError, ValueError, RuntimeError) as exc:
        return _failed_probe(descriptor.id, started_at, started, str(exc))


def mcp_descriptor_to_dict(descriptor: ToolServerDescriptor) -> dict[str, Any]:
    """Serialize a descriptor without resolving or exposing secrets."""
    return {
        "id": descriptor.id,
        "title": descriptor.title,
        "description": descriptor.description,
        "transport": descriptor.transport.value,
        "command": descriptor.command,
        "args": redact_for_storage(list(descriptor.args)),
        "cwd": descriptor.cwd,
        "url": descriptor.url,
        "environment": _safe_reference_mapping(descriptor.environment),
        "headers": _safe_reference_mapping(descriptor.headers),
        "instructions": redact_for_storage(descriptor.instructions),
        "source": descriptor.source,
        "trusted": descriptor.trusted,
        "enabled": descriptor.enabled,
        "timeout_seconds": descriptor.timeout_seconds,
        "harnesses": list(descriptor.harnesses),
        "policy_id": descriptor.execution_policy.id,
    }


def mcp_probe_to_dict(result: MCPProbeResult) -> dict[str, Any]:
    """Serialize discovered metadata with redaction and bounded schemas."""
    return redact_for_storage(
        {
            "id": result.id,
            "server_id": result.server_id,
            "status": result.status.value,
            "started_at": result.started_at,
            "duration_ms": result.duration_ms,
            "error": result.error,
            "protocol_version": result.protocol_version,
            "server_name": result.server_name,
            "server_version": result.server_version,
            "instructions": result.instructions,
            "capabilities": result.capabilities,
            "tools": [_tool_to_dict(tool) for tool in result.tools],
            "resources": list(result.resources),
            "prompts": list(result.prompts),
        }
    )


def _probe_stdio(
    descriptor: ToolServerDescriptor, resolved_env: Mapping[str, str]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stderr_file:
        process = subprocess.Popen(
            [str(descriptor.command), *descriptor.args],
            cwd=descriptor.cwd,
            env=build_safe_env(HarnessContext(proxy_url=""), extra=resolved_env),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            text=True,
            encoding="utf-8",
            start_new_session=True,
        )
        assert process.stdin is not None
        assert process.stdout is not None
        output_queue: Queue[str | BaseException | None] = Queue(maxsize=256)
        output_thread = threading.Thread(
            target=_read_stdio_output,
            args=(process.stdout, output_queue),
            daemon=True,
        )
        output_thread.start()
        responses: dict[int, dict[str, Any]] = {}
        deadline = time.monotonic() + descriptor.timeout_seconds
        try:
            for payload in _discovery_requests():
                process.stdin.write(json.dumps(payload) + "\n")
                process.stdin.flush()
                request_id = payload.get("id")
                if isinstance(request_id, int):
                    responses[request_id] = _wait_stdio_response(
                        output_queue,
                        responses,
                        request_id,
                        deadline=deadline,
                    )
            process.stdin.close()
            try:
                process.wait(timeout=min(1.0, max(0.01, deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                _kill_process_group(process)
                process.wait(timeout=1)
        except (OSError, TimeoutError, ValueError):
            _kill_process_group(process)
            process.wait(timeout=1)
            raise
        stderr_file.seek(0)
        stderr = stderr_file.read(4097)
    if process.returncode not in (0, None):
        detail = " ".join(stderr.split())[:300]
        raise RuntimeError(
            f"MCP stdio server exited with {process.returncode}: {detail}"
        )
    return tuple(_present_response(responses, request_id) for request_id in range(1, 5))  # type: ignore[return-value]


def _probe_http(
    descriptor: ToolServerDescriptor, resolved_headers: Mapping[str, str]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    responses: list[dict[str, Any]] = []
    session_id: str | None = None
    protocol_version: str | None = None
    for payload in _discovery_requests():
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **resolved_headers,
        }
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        if protocol_version:
            headers["MCP-Protocol-Version"] = protocol_version
        req = urllib_request.Request(
            str(descriptor.url),
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with _open_http(req, timeout=descriptor.timeout_seconds) as response:
            session_id = response.headers.get("Mcp-Session-Id") or session_id
            body = response.read(1_000_001)
            if len(body) > 1_000_000:
                raise ValueError("MCP HTTP response exceeds 1 MB")
            if "id" not in payload:
                continue
            decoded = _decode_http_response(
                body,
                response.headers.get_content_type(),
                expected_id=payload["id"],
            )
            responses.append(decoded)
            if payload["id"] == 1:
                protocol_version = _optional_text(
                    (decoded.get("result") or {}).get("protocolVersion")
                )
    if session_id:
        _close_http_session(
            descriptor,
            resolved_headers,
            session_id=session_id,
            protocol_version=protocol_version,
        )
    return tuple(responses)  # type: ignore[return-value]


def _discovery_requests() -> tuple[dict[str, Any], ...]:
    return (
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "gpt2giga", "version": "2"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "resources/list", "params": {}},
        {"jsonrpc": "2.0", "id": 4, "method": "prompts/list", "params": {}},
    )


def _read_stdio_output(stream, output_queue: Queue[str | BaseException | None]) -> None:
    total = 0
    try:
        while line := stream.readline(1_000_001):
            total += len(line)
            if total > 1_000_000:
                output_queue.put(ValueError("MCP stdio response exceeds 1 MB"))
                return
            if line.strip():
                output_queue.put(line)
    except (OSError, UnicodeError) as exc:
        output_queue.put(exc)
    finally:
        output_queue.put(None)


def _wait_stdio_response(
    output_queue: Queue[str | BaseException | None],
    responses: dict[int, dict[str, Any]],
    request_id: int,
    *,
    deadline: float,
) -> dict[str, Any]:
    while request_id not in responses:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("MCP stdio probe timed out")
        try:
            queued = output_queue.get(timeout=remaining)
        except Empty as exc:
            raise TimeoutError("MCP stdio probe timed out") from exc
        if queued is None:
            raise ValueError(f"MCP response {request_id} is missing")
        if isinstance(queued, BaseException):
            raise queued
        try:
            item = json.loads(queued)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and isinstance(item.get("id"), int):
            responses[item["id"]] = item
    return responses[request_id]


def _required_response(
    responses: Mapping[int, dict[str, Any]], request_id: int
) -> dict[str, Any]:
    response = responses.get(request_id)
    if response is None:
        raise ValueError(f"MCP response {request_id} is missing")
    if response.get("error"):
        error = response["error"]
        message = (
            error.get("message") if isinstance(error, Mapping) else "unknown error"
        )
        raise ValueError(f"MCP request {request_id} failed: {message}")
    return response


def _present_response(
    responses: Mapping[int, dict[str, Any]], request_id: int
) -> dict[str, Any]:
    response = responses.get(request_id)
    if response is None:
        raise ValueError(f"MCP response {request_id} is missing")
    return response


def _optional_list_response(
    response: dict[str, Any], *, request_id: int, key: str
) -> dict[str, Any]:
    if not response.get("error"):
        return response
    error = response["error"]
    code = error.get("code") if isinstance(error, Mapping) else None
    if code == -32601:
        return {"jsonrpc": "2.0", "id": request_id, "result": {key: []}}
    message = error.get("message") if isinstance(error, Mapping) else "unknown error"
    raise ValueError(f"MCP request {request_id} failed: {message}")


def _decode_http_response(
    body: bytes, content_type: str, *, expected_id: int
) -> dict[str, Any]:
    text = body.decode("utf-8")
    if content_type == "text/event-stream":
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            try:
                item = json.loads(line[5:].lstrip())
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and item.get("id") == expected_id:
                return item
        raise ValueError("MCP SSE response did not contain the requested JSON-RPC id")
    try:
        item = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("MCP HTTP response is not valid JSON-RPC") from exc
    if not isinstance(item, dict):
        raise ValueError("MCP HTTP response must be an object")
    return item


class _NoRedirectHandler(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_http(req: urllib_request.Request, *, timeout: float):
    opener = urllib_request.build_opener(_NoRedirectHandler())
    return opener.open(req, timeout=timeout)


def _close_http_session(
    descriptor: ToolServerDescriptor,
    resolved_headers: Mapping[str, str],
    *,
    session_id: str,
    protocol_version: str | None,
) -> None:
    headers = {**resolved_headers, "Mcp-Session-Id": session_id}
    if protocol_version:
        headers["MCP-Protocol-Version"] = protocol_version
    req = urllib_request.Request(
        str(descriptor.url),
        headers=headers,
        method="DELETE",
    )
    try:
        with _open_http(req, timeout=descriptor.timeout_seconds) as response:
            response.read(1024)
    except OSError:
        return


def _resolve_values(
    values: Mapping[str, str | SecretReference], resolver: SecretResolver, *, owner: str
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for key, value in values.items():
        if isinstance(value, SecretReference):
            resolved[key] = resolver.resolve(value, owner=owner).reveal_for(owner)
        else:
            resolved[key] = value
    return resolved


def _reference_mapping(
    value: Any, *, reject_secret_literals: bool = False
) -> dict[str, str | SecretReference]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("MCP env/headers must be a mapping")
    result: dict[str, str | SecretReference] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip()
        if not key:
            raise ValueError("MCP env/header names must not be empty")
        if isinstance(raw_value, Mapping):
            reference_data = raw_value.get("secret_ref", raw_value)
            if not isinstance(reference_data, Mapping):
                raise ValueError(f"invalid secret reference for {key}")
            result[key] = secret_reference_from_dict(reference_data)
        elif isinstance(raw_value, str):
            if reject_secret_literals and _is_sensitive_name(key):
                raise ValueError(f"sensitive value {key} must use secret_ref")
            result[key] = raw_value
        else:
            raise ValueError(
                f"MCP env/header value for {key} must be text or secret_ref"
            )
    return result


def _safe_reference_mapping(
    values: Mapping[str, str | SecretReference],
) -> dict[str, Any]:
    return {
        key: (
            {"secret_ref": secret_reference_to_dict(value)}
            if isinstance(value, SecretReference)
            else "<configured>"
        )
        for key, value in values.items()
    }


def _risk_rules(value: Any) -> dict[ToolRisk, Any]:
    from gpt2giga_harness.tools import PolicyDecision

    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("risk_policy must be a mapping")
    return {
        ToolRisk(str(key)): PolicyDecision(str(item)) for key, item in value.items()
    }


def _tool_rules(value: Any) -> dict[str, Any]:
    from gpt2giga_harness.tools import PolicyDecision

    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("tool_policy must be a mapping")
    return {str(key): PolicyDecision(str(item)) for key, item in value.items()}


def _tool_descriptor(
    server: ToolServerDescriptor, item: Mapping[str, Any]
) -> ToolDescriptor:
    name = str(item["name"])
    annotations = (
        item.get("annotations") if isinstance(item.get("annotations"), Mapping) else {}
    )
    if annotations.get("destructiveHint"):
        risk = ToolRisk.HIGH
    elif annotations.get("readOnlyHint"):
        risk = ToolRisk.LOW
    else:
        risk = ToolRisk.MEDIUM
    descriptor = ToolDescriptor(
        id=f"{server.id}:{name}",
        provider_id=server.id,
        title=name,
        description=_optional_text(item.get("description")) or "",
        input_schema=redact_for_storage(item.get("inputSchema") or {}),
        output_schema=redact_for_storage(item.get("outputSchema") or {}),
        risk=risk,
        policy_id=server.execution_policy.id,
        metadata={"annotations": redact_for_storage(annotations)},
    )
    resolution = server.execution_policy.resolve(descriptor)
    return ToolDescriptor(
        **{
            **descriptor.__dict__,
            "metadata": {
                **descriptor.metadata,
                "policy_decision": resolution.decision.value,
                "policy_source": resolution.source,
            },
        }
    )


def _tool_to_dict(tool: ToolDescriptor) -> dict[str, Any]:
    return {
        "id": tool.id,
        "name": tool.title,
        "description": tool.description,
        "input_schema": tool.input_schema,
        "output_schema": tool.output_schema,
        "risk": tool.risk.value,
        "policy_id": tool.policy_id,
        "policy_decision": tool.metadata.get("policy_decision", "ask"),
        "policy_source": tool.metadata.get("policy_source", "default"),
        "metadata": tool.metadata,
    }


def _safe_named_items(
    response: Mapping[str, Any], key: str
) -> tuple[Mapping[str, Any], ...]:
    values = (response.get("result") or {}).get(key, [])
    return tuple(
        redact_for_storage(
            {
                field: item.get(field)
                for field in ("name", "uri", "description", "mimeType", "title")
                if item.get(field) is not None
            }
        )
        for item in values[:200]
        if isinstance(item, Mapping)
    )


def _failed_probe(
    server_id: str,
    started_at: str,
    started: float,
    error: str,
    *,
    blocked: bool = False,
) -> MCPProbeResult:
    return MCPProbeResult(
        id=new_id("mcp_probe"),
        server_id=server_id,
        status=MCPProbeStatus.BLOCKED if blocked else MCPProbeStatus.UNHEALTHY,
        started_at=started_at,
        duration_ms=int((time.monotonic() - started) * 1000),
        error=str(redact_for_storage(" ".join(error.split())[:500])),
    )


def _kill_process_group(process: subprocess.Popen[str]) -> None:
    try:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, (list, tuple)):
        raise ValueError("MCP args must be a list")
    return tuple(str(item) for item in value)


def _is_sensitive_name(value: str) -> bool:
    normalized = value.lower().replace("-", "_")
    markers = (
        "authorization",
        "credential",
        "credentials",
        "password",
        "secret",
        "token",
        "api_key",
        "cookie",
    )
    return any(
        normalized == marker
        or normalized.startswith(f"{marker}_")
        or normalized.endswith(f"_{marker}")
        for marker in markers
    )


def _is_sensitive_arg(value: str) -> bool:
    option = value.split("=", 1)[0].lstrip("-")
    return bool(option) and _is_sensitive_name(option)
