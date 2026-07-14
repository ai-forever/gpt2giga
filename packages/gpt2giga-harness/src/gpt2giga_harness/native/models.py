"""Core models for native harness session discovery and linking."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Mapping
import uuid


class HarnessInvocationMode(str, Enum):
    """Describe how a harness should be invoked."""

    HEADLESS = "headless"
    NATIVE = "native"


def parse_invocation_mode(
    value: str | HarnessInvocationMode | None,
) -> HarnessInvocationMode:
    """Parse a CLI/UI invocation mode value."""
    if isinstance(value, HarnessInvocationMode):
        return value
    if value is None or not str(value).strip():
        return HarnessInvocationMode.HEADLESS
    return HarnessInvocationMode(str(value).strip().lower())


class NativeSessionStatus(str, Enum):
    """Describe how a native session relates to gpt2giga history."""

    MANAGED_NATIVE = "managed_native"
    EXTERNAL_NATIVE = "external_native"
    IMPORTED = "imported"
    LINKED = "linked"
    READONLY = "readonly"


@dataclass(frozen=True)
class NativeExecutionSnapshot:
    """Immutable, redaction-safe configuration for one managed native start."""

    id: str
    harness_id: str
    api_mode: str
    model: str | None
    native_home: str | None
    workspace: str | None
    project_id: str
    permission_mode: str
    tool_config_hash: str | None
    created_at: str
    route_known: bool = True
    warnings: tuple[str, ...] = ()
    source_workspace: str | None = None
    effective_workspace: str | None = None
    workspace_policy: str | None = None


@dataclass(frozen=True)
class NativeSessionRef:
    """Cross-harness reference to a discovered or managed native session."""

    id: str
    harness_id: str
    native_session_id: str | None
    title: str
    workspace: str | None
    source: str
    status: NativeSessionStatus
    created_at: str | None
    updated_at: str | None
    message_count: int | None
    can_preview: bool
    can_import: bool
    can_resume: bool
    resume_reason: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    execution_snapshot: NativeExecutionSnapshot | None = None


@dataclass(frozen=True)
class NativeTranscriptMessage:
    """Normalized message preview imported from a native CLI transcript."""

    role: str
    content: str
    created_at: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


def create_execution_snapshot(
    *,
    harness_id: str,
    api_mode: str,
    model: str | None,
    native_home: str | None,
    workspace: str | None,
    project_id: str,
    permission_mode: str,
    tool_config_hash: str | None,
    source_workspace: str | None = None,
    effective_workspace: str | None = None,
    workspace_policy: str | None = None,
    route_known: bool = True,
    warnings: tuple[str, ...] = (),
) -> NativeExecutionSnapshot:
    """Create one immutable native execution snapshot with a stable public id."""
    created_at = datetime.now(timezone.utc).isoformat()
    identity = json.dumps(
        {
            "harness_id": harness_id,
            "api_mode": api_mode,
            "model": model,
            "native_home": native_home,
            "workspace": workspace,
            "project_id": project_id,
            "permission_mode": permission_mode,
            "tool_config_hash": tool_config_hash,
            "source_workspace": source_workspace,
            "effective_workspace": effective_workspace,
            "workspace_policy": workspace_policy,
            "created_at": created_at,
            "nonce": uuid.uuid4().hex,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    snapshot_id = "nexec_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return NativeExecutionSnapshot(
        id=snapshot_id,
        harness_id=harness_id,
        api_mode=api_mode,
        model=model,
        native_home=native_home,
        workspace=workspace,
        project_id=project_id,
        permission_mode=permission_mode,
        tool_config_hash=tool_config_hash,
        created_at=created_at,
        route_known=route_known,
        warnings=warnings,
        source_workspace=source_workspace,
        effective_workspace=effective_workspace,
        workspace_policy=workspace_policy,
    )


def execution_snapshot_to_dict(
    snapshot: NativeExecutionSnapshot,
) -> dict[str, Any]:
    """Serialize a native execution snapshot for storage and API responses."""
    return {
        "id": snapshot.id,
        "harness_id": snapshot.harness_id,
        "api_mode": snapshot.api_mode,
        "model": snapshot.model,
        "native_home": snapshot.native_home,
        "workspace": snapshot.workspace,
        "project_id": snapshot.project_id,
        "permission_mode": snapshot.permission_mode,
        "tool_config_hash": snapshot.tool_config_hash,
        "created_at": snapshot.created_at,
        "route_known": snapshot.route_known,
        "warnings": list(snapshot.warnings),
        "source_workspace": snapshot.source_workspace,
        "effective_workspace": snapshot.effective_workspace,
        "workspace_policy": snapshot.workspace_policy,
    }


def execution_snapshot_from_dict(
    data: Mapping[str, Any] | None,
) -> NativeExecutionSnapshot | None:
    """Parse a persisted snapshot while keeping legacy missing values readable."""
    if not isinstance(data, Mapping):
        return None
    required = ("id", "harness_id", "api_mode", "project_id", "permission_mode")
    if any(not str(data.get(key) or "").strip() for key in required):
        return None
    return NativeExecutionSnapshot(
        id=str(data["id"]),
        harness_id=str(data["harness_id"]),
        api_mode=str(data["api_mode"]),
        model=_optional_text(data.get("model")),
        native_home=_optional_text(data.get("native_home")),
        workspace=_optional_text(data.get("workspace")),
        project_id=str(data["project_id"]),
        permission_mode=str(data["permission_mode"]),
        tool_config_hash=_optional_text(data.get("tool_config_hash")),
        created_at=str(data.get("created_at") or ""),
        route_known=bool(data.get("route_known", True)),
        warnings=tuple(str(item) for item in data.get("warnings", ())),
        source_workspace=_optional_text(data.get("source_workspace")),
        effective_workspace=_optional_text(data.get("effective_workspace")),
        workspace_policy=_optional_text(data.get("workspace_policy")),
    )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
