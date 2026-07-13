"""Common contracts for native harness history connectors."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol

from gpt2giga_harness.native.models import (
    NativeExecutionSnapshot,
    NativeSessionRef,
    NativeTranscriptMessage,
    execution_snapshot_to_dict,
)
from gpt2giga_harness.runtime.policy import EnforcementLevel
from gpt2giga_harness.types import HarnessContext, HarnessRequest, redact_secrets


NATIVE_PERMISSION_MODES = frozenset({"plan", "read", "edit"})


class NativePromptDeliveryStatus(str, Enum):
    """Describe the durable delivery outcome for one native initial prompt."""

    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"


@dataclass(frozen=True)
class NativePromptDelivery:
    """Redaction-safe contract for delivering one native initial prompt."""

    idempotency_key: str
    mechanism: str
    prompt_sha256: str
    byte_count: int
    status: NativePromptDeliveryStatus = NativePromptDeliveryStatus.PENDING
    error: str | None = None


@dataclass(frozen=True)
class NativeCommandPlan:
    """A native CLI command that can start or resume a session."""

    command: tuple[str, ...]
    env: Mapping[str, str] = field(default_factory=dict)
    cwd: str | None = None
    native_home: str | None = None
    display_command: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    execution_snapshot: NativeExecutionSnapshot | None = None
    snapshot_known_sources: tuple[str, ...] = ()
    prompt_delivery: NativePromptDelivery | None = None


@dataclass(frozen=True)
class NativeDiscoveryError:
    """Structured discovery failure returned to API/UI callers."""

    harness_id: str
    code: str
    message: str
    detail: str | None = None


@dataclass(frozen=True)
class NativeDiscoveryResult:
    """Native session discovery result with partial failure support."""

    sessions: tuple[NativeSessionRef, ...]
    errors: tuple[NativeDiscoveryError, ...] = ()


class NativeHistoryConnector(Protocol):
    """Connector interface for harness-specific native session behavior."""

    harness_id: str
    requires_proxy_preflight: bool

    def discover(
        self,
        *,
        workspace: str | None,
        include_external: bool,
    ) -> tuple[NativeSessionRef, ...]:
        """Discover native sessions for one harness."""

    def preview(
        self,
        ref: NativeSessionRef,
        *,
        max_messages: int = 20,
    ) -> tuple[NativeTranscriptMessage, ...]:
        """Return a small transcript preview when safe."""

    def import_ref(
        self,
        ref: NativeSessionRef,
    ) -> tuple[NativeTranscriptMessage, ...]:
        """Return transcript messages for normalized import."""

    def build_start_command(
        self,
        request: HarnessRequest,
        context: HarnessContext,
    ) -> NativeCommandPlan:
        """Build a command plan for starting a new native session."""

    def build_resume_command(
        self,
        ref: NativeSessionRef,
        context: HarnessContext,
    ) -> NativeCommandPlan:
        """Build a command plan for resuming a known native session."""

    def record_start_snapshot(self, plan: NativeCommandPlan) -> None:
        """Persist a successfully spawned native start snapshot for discovery."""


def native_permission_metadata(
    *,
    requested_mode: str,
    cli_control: str,
    cli_value: str,
    read_only: bool,
) -> dict[str, Any]:
    """Describe the proven CLI permission boundary without claiming ownership."""
    if requested_mode not in NATIVE_PERMISSION_MODES:
        raise ValueError(f"unsupported native permission mode: {requested_mode}")
    return {
        "requested_mode": requested_mode,
        "cli_control": cli_control,
        "cli_value": cli_value,
        "read_only": read_only,
        "cli_permission_enforcement": EnforcementLevel.DELEGATED_TO_CLI_SANDBOX.value,
        "interactive_approvals": EnforcementLevel.DELEGATED_TO_CLI_SANDBOX.value,
        "harness_process_spawn": EnforcementLevel.ENFORCED_BY_HARNESS.value,
    }


def native_source_workspace(request: HarnessRequest) -> str | None:
    """Return the source checkout identity when execution uses a worktree."""
    value = request.extra.get("native_source_workspace")
    if value is None or not str(value).strip():
        return request.workspace
    return str(value).strip()


def native_workspace_policy(request: HarnessRequest) -> str:
    """Return the effective persisted workspace policy for a native plan."""
    execution = request.extra.get("workspace_execution")
    if isinstance(execution, Mapping):
        value = execution.get("policy")
        if value is not None and str(value).strip():
            return str(value).strip()
    return "current"


def native_command_plan_to_dict(plan: NativeCommandPlan) -> dict[str, Any]:
    """Serialize a native command plan with secret-looking values redacted."""
    display_command = plan.display_command or plan.command
    public_command = (
        display_command if plan.prompt_delivery is not None else plan.command
    )
    return {
        "command": redact_secrets(list(public_command)),
        "display_command": redact_secrets(list(display_command)),
        "env": redact_secrets(dict(plan.env)),
        "cwd": redact_secrets(plan.cwd),
        "native_home": redact_secrets(plan.native_home),
        "metadata": redact_secrets(dict(plan.metadata)),
        "execution_snapshot": (
            redact_secrets(execution_snapshot_to_dict(plan.execution_snapshot))
            if plan.execution_snapshot is not None
            else None
        ),
        "prompt_delivery": (
            native_prompt_delivery_to_dict(plan.prompt_delivery)
            if plan.prompt_delivery is not None
            else None
        ),
    }


def native_prompt_delivery_to_dict(
    delivery: NativePromptDelivery,
    *,
    status: NativePromptDeliveryStatus | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Serialize prompt delivery without exposing the submitted prompt."""
    effective_status = status or delivery.status
    payload = {
        "idempotency_key": delivery.idempotency_key,
        "mechanism": delivery.mechanism,
        "prompt_sha256": delivery.prompt_sha256,
        "byte_count": delivery.byte_count,
        "status": effective_status.value,
    }
    effective_error = error if error is not None else delivery.error
    if effective_error is not None:
        payload["error"] = redact_secrets(effective_error)
    return payload


def discovery_error_to_dict(error: NativeDiscoveryError) -> dict[str, Any]:
    """Serialize a native discovery error for API responses."""
    return {
        "harness_id": error.harness_id,
        "code": error.code,
        "message": redact_secrets(error.message),
        "detail": redact_secrets(error.detail),
    }


def discovery_result_to_dict(result: NativeDiscoveryResult) -> dict[str, Any]:
    """Serialize a native discovery result for API responses."""
    from gpt2giga_harness.native.store import native_session_ref_to_dict

    return {
        "sessions": [native_session_ref_to_dict(ref) for ref in result.sessions],
        "errors": [discovery_error_to_dict(error) for error in result.errors],
    }
