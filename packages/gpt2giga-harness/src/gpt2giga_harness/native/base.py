"""Common contracts for native harness history connectors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from gpt2giga_harness.native.models import (
    NativeSessionRef,
    NativeTranscriptMessage,
)
from gpt2giga_harness.types import HarnessContext, HarnessRequest, redact_secrets


@dataclass(frozen=True)
class NativeCommandPlan:
    """A native CLI command that can start or resume a session."""

    command: tuple[str, ...]
    env: Mapping[str, str] = field(default_factory=dict)
    cwd: str | None = None
    native_home: str | None = None
    display_command: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


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


def native_command_plan_to_dict(plan: NativeCommandPlan) -> dict[str, Any]:
    """Serialize a native command plan with secret-looking values redacted."""
    display_command = plan.display_command or plan.command
    return {
        "command": redact_secrets(list(plan.command)),
        "display_command": redact_secrets(list(display_command)),
        "env": redact_secrets(dict(plan.env)),
        "cwd": redact_secrets(plan.cwd),
        "native_home": redact_secrets(plan.native_home),
        "metadata": redact_secrets(dict(plan.metadata)),
    }


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
