"""Hermetic Claude Agent SDK surface and authentication boundary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version as distribution_version
import inspect
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Awaitable, Callable, Mapping, Sequence

from gpt2giga_harness.structured_processes import NormalizedStructuredEvent
from gpt2giga_harness.structured_sessions import AdapterCapabilitySnapshot


CLAUDE_AGENT_SDK_DISTRIBUTION = "claude-agent-sdk"
CLAUDE_AGENT_SDK_PROTOCOL = "claude-agent-sdk"
MINIMUM_CLAUDE_AGENT_SDK_VERSION = "0.2.122"
MAXIMUM_CLAUDE_AGENT_SDK_VERSION_EXCLUSIVE = "0.3.0"
_VERSION_RE = re.compile(r"(?<!\d)(\d+\.\d+(?:\.\d+)?)")
_IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@+~-]{0,255}\Z")

_REQUIRED_CLIENT_MEMBERS = frozenset(
    {
        "connect",
        "disconnect",
        "get_mcp_status",
        "interrupt",
        "query",
        "receive_response",
        "reconnect_mcp_server",
        "set_model",
        "toggle_mcp_server",
    }
)
_REQUIRED_OPTION_FIELDS = frozenset(
    {
        "can_use_tool",
        "cli_path",
        "env",
        "fork_session",
        "hooks",
        "mcp_servers",
        "resume",
        "setting_sources",
        "strict_mcp_config",
    }
)


class ClaudeAgentSdkPocError(RuntimeError):
    """Raised when the reviewed Claude Agent SDK contract is not proven."""


class ClaudeSdkAuthMode(str, Enum):
    """Documented authentication modes admitted by the embedded PoC."""

    API_KEY = "api_key"
    BEDROCK = "bedrock"
    ANTHROPIC_AWS = "anthropic_aws"
    VERTEX = "vertex"
    FOUNDRY = "foundry"
    CLAUDE_AI_SUBSCRIPTION = "claude_ai_subscription"


_PROVIDER_AUTH_FLAGS = {
    ClaudeSdkAuthMode.BEDROCK: "CLAUDE_CODE_USE_BEDROCK",
    ClaudeSdkAuthMode.ANTHROPIC_AWS: "CLAUDE_CODE_USE_ANTHROPIC_AWS",
    ClaudeSdkAuthMode.VERTEX: "CLAUDE_CODE_USE_VERTEX",
    ClaudeSdkAuthMode.FOUNDRY: "CLAUDE_CODE_USE_FOUNDRY",
}


@dataclass(frozen=True)
class ClaudeSdkExitDecision:
    """Fail-closed N2-04 decision without provider traffic or credential use."""

    embedded_driver_ready: bool
    subscription_embedding_allowed: bool
    provider_ui_handoff_ready: bool
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class ClaudeSdkProbe:
    """Content-free evidence from one installed SDK and dual CLI probe."""

    sdk_version: str
    system_cli_path: str
    system_cli_version: str
    bundled_cli_path: str
    bundled_cli_version: str
    selected_cli_source: str
    python_defer_shape: bool
    python_durable_defer_documented: bool
    capability_snapshot: AdapterCapabilitySnapshot
    exit_decision: ClaudeSdkExitDecision


@dataclass(frozen=True)
class ClaudePermissionBinding:
    """Content-free identity for one live SDK permission callback."""

    tool_name: str
    tool_use_id: str
    input_hash: str


def probe_installed_claude_agent_sdk(
    *,
    system_cli_path: str | Path,
    adapter_version: str,
    python_durable_defer_documented: bool,
) -> ClaudeSdkProbe:
    """Probe the optional installed SDK without model or provider operations."""
    try:
        sdk_version = distribution_version(CLAUDE_AGENT_SDK_DISTRIBUTION)
        sdk = import_module("claude_agent_sdk")
    except (PackageNotFoundError, ModuleNotFoundError) as exc:
        raise ClaudeAgentSdkPocError("Claude Agent SDK extra is not installed") from exc

    client_type = getattr(sdk, "ClaudeSDKClient", None)
    options_type = getattr(sdk, "ClaudeAgentOptions", None)
    if client_type is None or options_type is None:
        raise ClaudeAgentSdkPocError(
            "Claude Agent SDK public client surface is missing"
        )
    client_members = {
        name
        for name in _REQUIRED_CLIENT_MEMBERS
        if callable(getattr(client_type, name, None))
    }
    option_fields = set(inspect.signature(options_type).parameters)
    package_file = Path(inspect.getfile(sdk)).resolve()
    bundled_name = "claude.exe" if os.name == "nt" else "claude"
    bundled_cli_path = package_file.parent / "_bundled" / bundled_name
    if not bundled_cli_path.is_file():
        raise ClaudeAgentSdkPocError("Claude Agent SDK bundled CLI is missing")

    return review_claude_agent_sdk_surface(
        sdk_version=sdk_version,
        adapter_version=adapter_version,
        system_cli_path=str(Path(system_cli_path).resolve()),
        system_cli_version=_run_version_probe(Path(system_cli_path)),
        bundled_cli_path=str(bundled_cli_path),
        bundled_cli_version=_run_version_probe(bundled_cli_path),
        client_members=client_members,
        option_fields=option_fields,
        python_defer_shape=hasattr(sdk, "DeferredToolUse"),
        python_durable_defer_documented=python_durable_defer_documented,
    )


def review_claude_agent_sdk_surface(
    *,
    sdk_version: str,
    adapter_version: str,
    system_cli_path: str,
    system_cli_version: str,
    bundled_cli_path: str,
    bundled_cli_version: str,
    client_members: Sequence[str] | set[str] | frozenset[str],
    option_fields: Sequence[str] | set[str] | frozenset[str],
    python_defer_shape: bool,
    python_durable_defer_documented: bool,
) -> ClaudeSdkProbe:
    """Review injected SDK evidence and freeze only conservative claims."""
    _validate_sdk_version(sdk_version)
    _validate_identity(adapter_version, field_name="adapter version")
    for value, field_name in (
        (system_cli_path, "system CLI path"),
        (bundled_cli_path, "bundled CLI path"),
    ):
        if not isinstance(value, str) or not value:
            raise ClaudeAgentSdkPocError(f"{field_name} is missing")
    system_version = _parse_version(system_cli_version, field_name="system CLI version")
    _parse_version(bundled_cli_version, field_name="bundled CLI version")

    missing_members = sorted(_REQUIRED_CLIENT_MEMBERS.difference(client_members))
    missing_options = sorted(_REQUIRED_OPTION_FIELDS.difference(option_fields))
    if missing_members or missing_options:
        missing = (*missing_members, *missing_options)
        raise ClaudeAgentSdkPocError(
            f"Claude Agent SDK reviewed surface is missing: {', '.join(missing)}"
        )
    if not isinstance(python_defer_shape, bool) or not isinstance(
        python_durable_defer_documented, bool
    ):
        raise ClaudeAgentSdkPocError("Claude Python defer evidence is invalid")

    protocol_version = ".".join(str(part) for part in _version_tuple(sdk_version)[:2])
    capabilities = AdapterCapabilitySnapshot(
        adapter_id="claude-code",
        adapter_version=adapter_version,
        protocol=CLAUDE_AGENT_SDK_PROTOCOL,
        protocol_version=protocol_version,
        structured_events=True,
        partial_output=True,
        interactive_input=True,
        live_approvals=True,
        durable_approval=(python_defer_shape and python_durable_defer_documented),
        interrupt=True,
        steer=False,
        resume=True,
        fork=True,
        session_list=True,
        session_close=False,
        native_auth=False,
        provider_ui_handoff=False,
        dynamic_model=True,
        dynamic_mcp=True,
        recovery_after_process_loss=True,
        attachment_kinds=("image", "text", "workspace_file", "document"),
        attachment_transports=("sdk-content-block", "sdk-path-reference"),
    )
    blockers: list[str] = []
    if not python_defer_shape:
        blockers.append("python_deferred_tool_shape_missing")
    if not python_durable_defer_documented:
        blockers.append("python_durable_approval_not_documented")
    decision = ClaudeSdkExitDecision(
        embedded_driver_ready=not blockers,
        subscription_embedding_allowed=False,
        provider_ui_handoff_ready=False,
        blockers=tuple(blockers),
    )
    return ClaudeSdkProbe(
        sdk_version=sdk_version,
        system_cli_path=system_cli_path,
        system_cli_version=system_version,
        bundled_cli_path=bundled_cli_path,
        bundled_cli_version=bundled_cli_version,
        selected_cli_source="explicit_system_cli_path",
        python_defer_shape=python_defer_shape,
        python_durable_defer_documented=python_durable_defer_documented,
        capability_snapshot=capabilities,
        exit_decision=decision,
    )


def build_claude_agent_sdk_options(
    *,
    system_cli_path: str | Path,
    cwd: str | Path,
    managed_config_dir: str | Path,
    auth_mode: ClaudeSdkAuthMode,
    api_key: str | None = None,
    provider_env: Mapping[str, str] | None = None,
    resume: str | None = None,
    fork_session: bool = False,
    can_use_tool: Callable[..., Awaitable[Any]] | None = None,
    hooks: Mapping[str, Sequence[Any]] | None = None,
    mcp_servers: Mapping[str, Any] | None = None,
) -> Any:
    """Build isolated ephemeral SDK options for a hermetic or authorized run."""
    if not isinstance(auth_mode, ClaudeSdkAuthMode):
        raise ClaudeAgentSdkPocError("Claude SDK auth mode is invalid")
    if auth_mode is ClaudeSdkAuthMode.CLAUDE_AI_SUBSCRIPTION:
        raise ClaudeAgentSdkPocError(
            "Claude.ai subscription embedding requires prior provider approval"
        )
    try:
        options_type = import_module("claude_agent_sdk").ClaudeAgentOptions
    except (AttributeError, ModuleNotFoundError) as exc:
        raise ClaudeAgentSdkPocError("Claude Agent SDK extra is not installed") from exc

    env = dict(provider_env or {})
    oauth_token = env.get("CLAUDE_CODE_OAUTH_TOKEN")
    if oauth_token:
        raise ClaudeAgentSdkPocError("Claude.ai OAuth tokens are not admitted")
    if auth_mode is ClaudeSdkAuthMode.API_KEY:
        if not isinstance(api_key, str) or not api_key:
            raise ClaudeAgentSdkPocError("Anthropic API key is required")
        env["ANTHROPIC_API_KEY"] = api_key
    else:
        flag = _PROVIDER_AUTH_FLAGS[auth_mode]
        if env.get(flag) != "1":
            raise ClaudeAgentSdkPocError(f"documented provider auth requires {flag}=1")
        if api_key is not None:
            raise ClaudeAgentSdkPocError(
                "Anthropic API key cannot be mixed with provider auth"
            )
    env["CLAUDE_CODE_OAUTH_TOKEN"] = ""
    env["CLAUDE_CONFIG_DIR"] = str(Path(managed_config_dir))
    env["CLAUDE_AGENT_SDK_CLIENT_APP"] = "gpt2giga-harness/n2-04-poc"

    return options_type(
        cli_path=Path(system_cli_path),
        cwd=Path(cwd),
        env=env,
        extra_args={"bare": None},
        setting_sources=[],
        strict_mcp_config=True,
        permission_mode="default",
        resume=resume,
        fork_session=fork_session,
        can_use_tool=can_use_tool,
        hooks=dict(hooks) if hooks is not None else None,
        mcp_servers=dict(mcp_servers or {}),
        include_partial_messages=True,
        include_hook_events=True,
    )


def permission_binding(
    *,
    tool_name: str,
    tool_input: Mapping[str, Any],
    tool_use_id: str | None,
) -> ClaudePermissionBinding:
    """Hash raw tool input into a content-free live approval identity."""
    _validate_identity(tool_name, field_name="tool name")
    _validate_identity(tool_use_id, field_name="tool use id")
    if not isinstance(tool_input, Mapping):
        raise ClaudeAgentSdkPocError("tool input must be a mapping")
    try:
        encoded = json.dumps(
            dict(tool_input),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ClaudeAgentSdkPocError("tool input is not canonical JSON") from exc
    return ClaudePermissionBinding(
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        input_hash=hashlib.sha256(encoded).hexdigest(),
    )


def normalize_claude_sdk_message(message: Any) -> tuple[NormalizedStructuredEvent, ...]:
    """Normalize reviewed SDK dataclasses without retaining raw tool input."""
    message_type = type(message).__name__
    if message_type == "AssistantMessage":
        events: list[NormalizedStructuredEvent] = []
        for block in getattr(message, "content", ()):
            block_type = type(block).__name__
            if block_type == "TextBlock":
                events.append(
                    NormalizedStructuredEvent(
                        type="output_delta",
                        payload={"content": {"type": "text", "text": block.text}},
                    )
                )
            elif block_type in {"ToolUseBlock", "ServerToolUseBlock"}:
                binding = permission_binding(
                    tool_name=block.name,
                    tool_input=block.input,
                    tool_use_id=block.id,
                )
                events.append(
                    NormalizedStructuredEvent(
                        type="tool_approval_pending",
                        id=binding.tool_use_id,
                        payload={
                            "tool_call_id": binding.tool_use_id,
                            "tool_name": binding.tool_name,
                            "input_hash": binding.input_hash,
                        },
                    )
                )
        return tuple(events)
    if message_type == "ResultMessage":
        deferred = getattr(message, "deferred_tool_use", None)
        payload: dict[str, Any] = {
            "session_id": message.session_id,
            "stop_reason": message.stop_reason,
            "num_turns": message.num_turns,
        }
        if deferred is not None:
            binding = permission_binding(
                tool_name=deferred.name,
                tool_input=deferred.input,
                tool_use_id=deferred.id,
            )
            payload["deferred_tool"] = {
                "tool_call_id": binding.tool_use_id,
                "tool_name": binding.tool_name,
                "input_hash": binding.input_hash,
            }
        return (
            NormalizedStructuredEvent(
                type="turn_failed" if message.is_error else "turn_completed",
                id=getattr(message, "uuid", None),
                payload=payload,
            ),
        )
    if message_type == "SystemMessage":
        return (
            NormalizedStructuredEvent(
                type="system_event",
                payload={"subtype": message.subtype},
            ),
        )
    return ()


def _run_version_probe(executable: Path) -> str:
    if not executable.is_file():
        raise ClaudeAgentSdkPocError(f"CLI executable does not exist: {executable}")
    with tempfile.TemporaryDirectory(prefix="gpt2giga-claude-sdk-probe-") as home:
        env = {
            "CLAUDE_CONFIG_DIR": home,
            "HOME": home,
            "PATH": os.environ.get("PATH", ""),
        }
        try:
            completed = subprocess.run(
                (str(executable), "--version"),
                cwd=home,
                env=env,
                capture_output=True,
                check=False,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ClaudeAgentSdkPocError("Claude CLI version probe failed") from exc
    if completed.returncode != 0:
        raise ClaudeAgentSdkPocError("Claude CLI version probe returned an error")
    return (completed.stdout or completed.stderr).strip()[:512]


def _validate_sdk_version(value: str) -> None:
    parsed = _version_tuple(value)
    if parsed < _version_tuple(MINIMUM_CLAUDE_AGENT_SDK_VERSION):
        raise ClaudeAgentSdkPocError("Claude Agent SDK is below the reviewed window")
    if parsed >= _version_tuple(MAXIMUM_CLAUDE_AGENT_SDK_VERSION_EXCLUSIVE):
        raise ClaudeAgentSdkPocError("Claude Agent SDK is above the reviewed window")


def _parse_version(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ClaudeAgentSdkPocError(f"{field_name} is invalid")
    match = _VERSION_RE.search(value)
    if match is None:
        raise ClaudeAgentSdkPocError(f"{field_name} could not be parsed")
    return match.group(1)


def _version_tuple(value: str) -> tuple[int, int, int]:
    parsed = _parse_version(value, field_name="version")
    parts = tuple(int(part) for part in parsed.split("."))
    return (parts + (0, 0, 0))[:3]


def _validate_identity(value: Any, *, field_name: str) -> None:
    if not isinstance(value, str) or _IDENTITY_RE.fullmatch(value) is None:
        raise ClaudeAgentSdkPocError(f"{field_name} is invalid")
