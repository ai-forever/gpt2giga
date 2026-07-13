"""Dry-run tool profile planning for the project cockpit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from gpt2giga_harness.project import (
    ProjectToolProfile,
    project_tool_profile_to_dict,
)
from gpt2giga_harness.registry import HarnessRegistry, UnknownHarnessError
from gpt2giga_harness.types import redact_secrets

SUPPORTED_TOOL_PROFILE_HARNESSES = ("codex-cli", "claude-code", "gemini-cli")
_CONFIG_PATHS = {
    "codex-cli": "managed CODEX_HOME config.toml mcp_servers",
    "claude-code": "managed Claude HOME mcpServers",
    "gemini-cli": "managed Gemini settings.json mcpServers",
}


@dataclass(frozen=True)
class ToolHarnessStatus:
    """Profile status for one harness."""

    harness_id: str
    status: str
    reason: str
    target_path: str | None = None
    preview: Mapping[str, Any] | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolProfileStatus:
    """Dry-run sync status for one project tool profile."""

    name: str
    profile: ProjectToolProfile
    harnesses: tuple[ToolHarnessStatus, ...]
    warnings: tuple[str, ...] = ()


def build_tool_profile_statuses(
    profiles: Mapping[str, ProjectToolProfile],
    registry: HarnessRegistry,
    *,
    include_previews: bool = False,
) -> tuple[ToolProfileStatus, ...]:
    """Build redacted, side-effect-free tool profile status rows."""
    statuses: list[ToolProfileStatus] = []
    for name, profile in profiles.items():
        harness_statuses = tuple(
            _harness_status(
                name,
                profile,
                harness_id,
                registry,
                include_preview=include_previews,
            )
            for harness_id in _target_harnesses(profile)
        )
        statuses.append(
            ToolProfileStatus(
                name=name,
                profile=profile,
                harnesses=harness_statuses,
                warnings=_profile_warnings(profile, harness_statuses),
            )
        )
    return tuple(statuses)


def tool_profile_status_to_dict(status: ToolProfileStatus) -> dict[str, Any]:
    """Serialize one tool profile status for API/UI output."""
    return {
        "name": status.name,
        "profile": project_tool_profile_to_dict(status.name, status.profile),
        "harnesses": [
            {
                "harness_id": item.harness_id,
                "status": item.status,
                "reason": item.reason,
                "target_path": item.target_path,
                "preview": redact_secrets(dict(item.preview or {})),
                "warnings": list(item.warnings),
            }
            for item in status.harnesses
        ],
        "warnings": list(status.warnings),
    }


def _target_harnesses(profile: ProjectToolProfile) -> tuple[str, ...]:
    if profile.harnesses:
        return profile.harnesses
    return SUPPORTED_TOOL_PROFILE_HARNESSES


def _harness_status(
    name: str,
    profile: ProjectToolProfile,
    harness_id: str,
    registry: HarnessRegistry,
    *,
    include_preview: bool,
) -> ToolHarnessStatus:
    try:
        harness = registry.get(harness_id)
    except UnknownHarnessError:
        return ToolHarnessStatus(
            harness_id=harness_id,
            status="missing",
            reason="Harness is not registered.",
        )
    if not profile.enabled:
        return ToolHarnessStatus(
            harness_id=harness_id,
            status="disabled",
            reason="Tool profile is disabled in project config.",
            target_path=_CONFIG_PATHS.get(harness_id),
        )
    if harness_id not in SUPPORTED_TOOL_PROFILE_HARNESSES:
        return ToolHarnessStatus(
            harness_id=harness_id,
            status="unsupported",
            reason="Dry-run config generation is not available for this harness.",
        )
    availability = harness.availability()
    warnings: list[str] = []
    if availability.status.value != "available":
        warnings.append(f"Harness availability: {availability.reason}")
    return ToolHarnessStatus(
        harness_id=harness_id,
        status="ready",
        reason="Dry-run config can be generated.",
        target_path=_CONFIG_PATHS[harness_id],
        preview=_profile_preview(name, profile, harness_id) if include_preview else {},
        warnings=tuple(warnings),
    )


def _profile_preview(
    name: str,
    profile: ProjectToolProfile,
    harness_id: str,
) -> Mapping[str, Any]:
    entry = {
        "kind": profile.kind,
        "enabled": True,
        "title": profile.title or name,
        "description": profile.description,
        "config": redact_secrets(dict(profile.config)),
    }
    if harness_id == "codex-cli":
        return {"mcp_servers": {name: entry}}
    return {"mcpServers": {name: entry}}


def _profile_warnings(
    profile: ProjectToolProfile,
    harnesses: tuple[ToolHarnessStatus, ...],
) -> tuple[str, ...]:
    warnings: list[str] = []
    if profile.enabled and not any(item.status == "ready" for item in harnesses):
        warnings.append("Enabled tool profile has no supported registered harness.")
    if profile.kind.lower() != "mcp":
        warnings.append("Only generic MCP-style dry-run previews are generated.")
    return tuple(warnings)
