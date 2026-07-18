"""Provider-owned Claude Code handoff contracts and action planning."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping

from gpt2giga_harness.cli_capabilities import CliCapabilitySnapshot


CLAUDE_HANDOFF_SCHEMA_VERSION = 1
CLAUDE_HANDOFF_EVIDENCE_PATH = "evidence/claude/2.1.212/provider_handoff_surface.json"
CLAUDE_HANDOFF_OWNERSHIP = "provider_owned"
CLAUDE_HANDOFF_AUTH_PREREQUISITE = "claude_ai_full_scope_login"
_SUPPORTED_PLATFORMS = frozenset({"darwin", "linux", "win32"})
_DESKTOP_PLATFORMS = frozenset({"darwin", "win32"})
_REQUIRED_REMOTE_CONTROL_CLAIMS = frozenset(
    {
        "api_keys_unsupported",
        "attach_slash_command",
        "claude_ai_auth_required",
        "disconnect_toggle",
        "interactive_flag",
        "provider_owned_local_process",
        "provider_session_list_fallback",
        "provider_url_not_machine_readable",
        "server_command",
    }
)
_REQUIRED_COMMAND_CLAIMS = frozenset({"desktop_slash_command", "exit_slash_command"})
_OBSERVABILITY_LIMITS = (
    "provider_session_identity_unavailable",
    "provider_url_unavailable",
    "structured_events_unavailable",
    "live_approvals_unavailable",
    "recovery_unavailable",
)


class ClaudeHandoffError(ValueError):
    """Raised when retained handoff evidence or requested input is invalid."""


class ClaudeHandoffAction(str, Enum):
    """Documented provider-owned actions exposed by the handoff planner."""

    LAUNCH_NEW = "launch_new"
    ATTACH_CURRENT = "attach_current"
    OPEN_PROVIDER_UI = "open_provider_ui"
    DISCONNECT = "disconnect"
    STOP = "stop"


class ClaudeHandoffLaunchMode(str, Enum):
    """Documented CLI launch surfaces for a new Remote Control session."""

    INTERACTIVE = "interactive"
    SERVER = "server"


@dataclass(frozen=True)
class ClaudeHandoffEvidence:
    """Strict retained public-document evidence with a semantic hash."""

    reviewed_at: str
    minimum_cli_version: str
    remote_control_url: str
    command_reference_url: str
    remote_control_claims: frozenset[str]
    command_claims: frozenset[str]
    evidence_hash: str


@dataclass(frozen=True)
class ClaudeHandoffCapability:
    """Content-free, fail-closed truth for one installed Claude CLI."""

    status: str
    cli_version: str | None
    platform: str
    provider_ui_handoff: bool
    one_shot: bool
    native_terminal: bool
    auth_prerequisite: str
    ownership: str
    documented_surfaces: tuple[str, ...]
    available_actions: tuple[ClaudeHandoffAction, ...]
    degraded_actions: tuple[ClaudeHandoffAction, ...]
    blocker: str | None
    evidence_hash: str
    structured_events: bool = False
    live_approvals: bool = False
    durable_approval: bool = False
    recovery: bool = False
    durable: bool = False
    queueable: bool = False


@dataclass(frozen=True)
class ClaudeHandoffPlan:
    """Exact content-free action preview with no provider identity or URL."""

    action: ClaudeHandoffAction
    status: str
    surface: str
    command: tuple[str, ...]
    workspace: str
    ownership: str
    auth_prerequisite: str
    observability_limits: tuple[str, ...]
    external_process_may_open: bool
    external_ui_may_open: bool
    machine_executable: bool
    instruction: str
    blocker: str | None
    evidence_hash: str
    transport: str = "provider_handoff"
    interaction_mode: str = "interactive"
    runtime_ownership: str = "request_bound"
    durable: bool = False
    queueable: bool = False
    resumable_by_harness: bool = False
    automatic_retry: bool = False


def load_claude_handoff_evidence() -> ClaudeHandoffEvidence:
    """Load the packaged reviewed-document fixture with strict parsing."""
    resource = files("gpt2giga_harness").joinpath(CLAUDE_HANDOFF_EVIDENCE_PATH)
    try:
        payload = json.loads(resource.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise ClaudeHandoffError("Claude handoff evidence is unavailable") from exc
    return parse_claude_handoff_evidence(payload)


def parse_claude_handoff_evidence(
    payload: Mapping[str, Any],
) -> ClaudeHandoffEvidence:
    """Parse one exact evidence fixture and reject forward schema drift."""
    if not isinstance(payload, Mapping):
        raise ClaudeHandoffError("Claude handoff evidence must be an object")
    expected_keys = {
        "schema_version",
        "reviewed_at",
        "minimum_cli_version",
        "sources",
    }
    if set(payload) != expected_keys:
        raise ClaudeHandoffError("Claude handoff evidence fields are invalid")
    if payload.get("schema_version") != CLAUDE_HANDOFF_SCHEMA_VERSION:
        raise ClaudeHandoffError("Claude handoff evidence schema is unsupported")
    sources = payload.get("sources")
    if not isinstance(sources, Mapping) or set(sources) != {
        "commands",
        "remote_control",
    }:
        raise ClaudeHandoffError("Claude handoff evidence sources are invalid")
    remote_url, remote_claims = _parse_source(
        sources["remote_control"],
        source_name="remote_control",
        required_claims=_REQUIRED_REMOTE_CONTROL_CLAIMS,
    )
    commands_url, command_claims = _parse_source(
        sources["commands"],
        source_name="commands",
        required_claims=_REQUIRED_COMMAND_CLAIMS,
    )
    reviewed_at = _required_text(payload.get("reviewed_at"), "reviewed_at")
    minimum_version = _required_text(
        payload.get("minimum_cli_version"), "minimum_cli_version"
    )
    canonical = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return ClaudeHandoffEvidence(
        reviewed_at=reviewed_at,
        minimum_cli_version=minimum_version,
        remote_control_url=remote_url,
        command_reference_url=commands_url,
        remote_control_claims=remote_claims,
        command_claims=command_claims,
        evidence_hash=hashlib.sha256(canonical).hexdigest(),
    )


def probe_claude_handoff(
    cli: CliCapabilitySnapshot,
    *,
    evidence: ClaudeHandoffEvidence | None = None,
    platform: str | None = None,
) -> ClaudeHandoffCapability:
    """Project retained docs plus installed CLI evidence into capability truth."""
    evidence = evidence or load_claude_handoff_evidence()
    platform = platform or sys.platform
    blocker = _handoff_blocker(cli, evidence=evidence, platform=platform)
    available: list[ClaudeHandoffAction] = []
    degraded: list[ClaudeHandoffAction] = []
    if blocker is None:
        for action in ClaudeHandoffAction.__members__.values():
            if (
                action is ClaudeHandoffAction.OPEN_PROVIDER_UI
                and platform not in _DESKTOP_PLATFORMS
            ):
                degraded.append(action)
            else:
                available.append(action)
    return ClaudeHandoffCapability(
        status=(
            "blocked"
            if blocker is not None
            else "degraded"
            if degraded
            else "supported"
        ),
        cli_version=cli.parsed_version or cli.version,
        platform=platform,
        provider_ui_handoff=blocker is None,
        one_shot=cli.compatible,
        native_terminal=cli.compatible,
        auth_prerequisite=CLAUDE_HANDOFF_AUTH_PREREQUISITE,
        ownership=CLAUDE_HANDOFF_OWNERSHIP,
        documented_surfaces=(
            "claude remote-control",
            "claude --remote-control",
            "/remote-control",
            "/desktop",
            "/exit",
        ),
        available_actions=tuple(available),
        degraded_actions=tuple(degraded),
        blocker=blocker,
        evidence_hash=evidence.evidence_hash,
    )


def plan_claude_handoff(
    cli: CliCapabilitySnapshot,
    *,
    action: ClaudeHandoffAction,
    workspace: str | Path,
    launch_mode: ClaudeHandoffLaunchMode = ClaudeHandoffLaunchMode.INTERACTIVE,
    evidence: ClaudeHandoffEvidence | None = None,
    platform: str | None = None,
) -> ClaudeHandoffPlan:
    """Build one exact action preview without opening a process or provider UI."""
    if not isinstance(action, ClaudeHandoffAction):
        raise ClaudeHandoffError("Claude handoff action is invalid")
    if not isinstance(launch_mode, ClaudeHandoffLaunchMode):
        raise ClaudeHandoffError("Claude handoff launch mode is invalid")
    evidence = evidence or load_claude_handoff_evidence()
    capability = probe_claude_handoff(
        cli,
        evidence=evidence,
        platform=platform,
    )
    workspace_path = Path(workspace)
    if not workspace_path.is_absolute() or not workspace_path.is_dir():
        raise ClaudeHandoffError(
            "Claude handoff workspace must be an existing directory"
        )
    surface, command, instruction, external_process, external_ui = _action_surface(
        cli,
        action=action,
        launch_mode=launch_mode,
    )
    blocker = capability.blocker
    if action is ClaudeHandoffAction.OPEN_PROVIDER_UI and (
        capability.platform not in _DESKTOP_PLATFORMS
    ):
        blocker = "claude_desktop_platform_unsupported"
        command = ()
        instruction = (
            "Use the documented Remote Control session list in Claude Web or mobile; "
            "this platform cannot continue the current session with /desktop."
        )
    status = "ready" if blocker is None else "manual_or_blocked"
    return ClaudeHandoffPlan(
        action=action,
        status=status,
        surface=surface,
        command=command,
        workspace=str(workspace_path),
        ownership=CLAUDE_HANDOFF_OWNERSHIP,
        auth_prerequisite=CLAUDE_HANDOFF_AUTH_PREREQUISITE,
        observability_limits=_OBSERVABILITY_LIMITS,
        external_process_may_open=external_process,
        external_ui_may_open=external_ui,
        machine_executable=False,
        instruction=instruction,
        blocker=blocker,
        evidence_hash=evidence.evidence_hash,
    )


def claude_handoff_capability_to_dict(
    capability: ClaudeHandoffCapability,
) -> dict[str, Any]:
    """Serialize handoff capability truth without raw help or provider state."""
    return {
        "status": capability.status,
        "cli_version": capability.cli_version,
        "platform": capability.platform,
        "provider_ui_handoff": capability.provider_ui_handoff,
        "one_shot": capability.one_shot,
        "native_terminal": capability.native_terminal,
        "auth_prerequisite": capability.auth_prerequisite,
        "ownership": capability.ownership,
        "documented_surfaces": list(capability.documented_surfaces),
        "available_actions": [item.value for item in capability.available_actions],
        "degraded_actions": [item.value for item in capability.degraded_actions],
        "blocker": capability.blocker,
        "evidence_hash": capability.evidence_hash,
        "structured_events": capability.structured_events,
        "live_approvals": capability.live_approvals,
        "durable_approval": capability.durable_approval,
        "recovery": capability.recovery,
        "durable": capability.durable,
        "queueable": capability.queueable,
        "content_free": True,
    }


def claude_handoff_plan_to_dict(plan: ClaudeHandoffPlan) -> dict[str, Any]:
    """Serialize one preview without a credential, provider URL, or session id."""
    return {
        "action": plan.action.value,
        "status": plan.status,
        "surface": plan.surface,
        "command": list(plan.command),
        "workspace": plan.workspace,
        "ownership": plan.ownership,
        "auth_prerequisite": plan.auth_prerequisite,
        "observability_limits": list(plan.observability_limits),
        "external_process_may_open": plan.external_process_may_open,
        "external_ui_may_open": plan.external_ui_may_open,
        "machine_executable": plan.machine_executable,
        "instruction": plan.instruction,
        "blocker": plan.blocker,
        "evidence_hash": plan.evidence_hash,
        "transport": plan.transport,
        "interaction_mode": plan.interaction_mode,
        "runtime_ownership": plan.runtime_ownership,
        "durable": plan.durable,
        "queueable": plan.queueable,
        "resumable_by_harness": plan.resumable_by_harness,
        "automatic_retry": plan.automatic_retry,
        "content_free": True,
    }


def claude_execution_surfaces_to_dict(
    capability: ClaudeHandoffCapability,
) -> list[dict[str, Any]]:
    """Distinguish Claude one-shot, terminal, handoff, and blocked embedding."""
    handoff_status = capability.status
    cli_status = "supported" if capability.one_shot else "blocked"
    cli_blocker = None if capability.one_shot else "cli_contract_unproven"
    return [
        {
            "id": "one_shot",
            "status": cli_status,
            "ownership": "request_bound",
            "queueable": False,
            "detail": "One bounded Claude Code print-mode process.",
            "blocker": cli_blocker,
        },
        {
            "id": "native_terminal",
            "status": "supported" if capability.native_terminal else "blocked",
            "ownership": "request_bound",
            "queueable": False,
            "detail": "Managed native Claude terminal with provider-owned interaction.",
            "blocker": None if capability.native_terminal else "cli_contract_unproven",
        },
        {
            "id": "provider_handoff",
            "status": handoff_status,
            "ownership": CLAUDE_HANDOFF_OWNERSHIP,
            "queueable": False,
            "detail": (
                "Documented Remote Control or Desktop action; Claude owns auth, "
                "session execution, and external UI."
            ),
            "blocker": capability.blocker,
        },
        {
            "id": "native_structured_embedded",
            "status": "blocked",
            "ownership": "unavailable",
            "queueable": False,
            "detail": "Embedded Claude Agent SDK productization is not admitted.",
            "blocker": "subscription_embedding_and_durable_approval_not_accepted",
        },
    ]


def _handoff_blocker(
    cli: CliCapabilitySnapshot,
    *,
    evidence: ClaudeHandoffEvidence,
    platform: str,
) -> str | None:
    if cli.harness_id != "claude-code":
        return "not_claude_code"
    if platform not in _SUPPORTED_PLATFORMS:
        return "platform_unsupported"
    if not cli.compatible:
        return "cli_contract_unproven"
    if cli.version_window_status != "in_window" or cli.parsed_version is None:
        return "cli_version_unreviewed"
    if _release_tuple(cli.parsed_version) < _release_tuple(
        evidence.minimum_cli_version
    ):
        return "remote_control_version_too_old"
    if not cli.capabilities.get("--remote-control"):
        return "interactive_remote_control_flag_missing"
    if not cli.capabilities.get("remote-control"):
        return "remote_control_command_unproven"
    return None


def _action_surface(
    cli: CliCapabilitySnapshot,
    *,
    action: ClaudeHandoffAction,
    launch_mode: ClaudeHandoffLaunchMode,
) -> tuple[str, tuple[str, ...], str, bool, bool]:
    if action is ClaudeHandoffAction.LAUNCH_NEW:
        executable = cli.command[:1] or ("claude",)
        suffix = (
            ("--remote-control",)
            if launch_mode is ClaudeHandoffLaunchMode.INTERACTIVE
            else ("remote-control",)
        )
        label = (
            "interactive"
            if launch_mode is ClaudeHandoffLaunchMode.INTERACTIVE
            else "server"
        )
        return (
            "argv",
            (*executable, *suffix),
            f"Run the reviewed Claude Remote Control {label} command in this workspace.",
            True,
            False,
        )
    if action is ClaudeHandoffAction.ATTACH_CURRENT:
        return (
            "slash_command",
            ("/remote-control",),
            "Enter /remote-control in the current Claude Code session.",
            False,
            False,
        )
    if action is ClaudeHandoffAction.OPEN_PROVIDER_UI:
        return (
            "slash_command",
            ("/desktop",),
            "Enter /desktop in the current Claude Code session; Claude opens Desktop.",
            False,
            True,
        )
    if action is ClaudeHandoffAction.DISCONNECT:
        return (
            "slash_command",
            ("/remote-control",),
            "Enter /remote-control again in the active session to disconnect it.",
            False,
            False,
        )
    return (
        "slash_command",
        ("/exit",),
        "Enter /exit in the provider-owned Claude session to stop that process.",
        False,
        False,
    )


def _parse_source(
    value: Any,
    *,
    source_name: str,
    required_claims: frozenset[str],
) -> tuple[str, frozenset[str]]:
    if not isinstance(value, Mapping) or set(value) != {"claims", "url"}:
        raise ClaudeHandoffError(f"Claude handoff {source_name} source is invalid")
    url = _required_text(value.get("url"), f"{source_name}.url")
    if not url.startswith("https://code.claude.com/docs/"):
        raise ClaudeHandoffError(f"Claude handoff {source_name} URL is not official")
    raw_claims = value.get("claims")
    if not isinstance(raw_claims, list) or any(
        not isinstance(item, str) or not item for item in raw_claims
    ):
        raise ClaudeHandoffError(f"Claude handoff {source_name} claims are invalid")
    claims = frozenset(raw_claims)
    if len(claims) != len(raw_claims) or not required_claims.issubset(claims):
        raise ClaudeHandoffError(f"Claude handoff {source_name} claims are incomplete")
    return url, claims


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ClaudeHandoffError(f"Claude handoff {field_name} is required")
    return value.strip()


def _release_tuple(value: str) -> tuple[int, int, int]:
    match = re.search(r"(?<!\d)(\d+)\.(\d+)(?:\.(\d+))?", value)
    if match is None:
        raise ClaudeHandoffError("Claude handoff version evidence is invalid")
    return int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)
