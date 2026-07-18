"""Workbench transport defaults and redaction-safe capability projections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from gpt2giga_harness.execution import ExecutionTransport
from gpt2giga_harness.runtime.structured import (
    DurableStructuredAdmissionError,
    admitted_durable_structured_capabilities,
    requested_execution_transport,
)
from gpt2giga_harness.structured_sessions import capability_snapshot_to_dict


@dataclass(frozen=True)
class WorkbenchTransportOption:
    """One client-visible transport choice without provider content or secrets."""

    transport: ExecutionTransport
    status: str
    detail: str
    blocker: str | None
    remediation: str | None
    durable: bool
    provider_native_continuity: bool

    def to_dict(self) -> dict[str, Any]:
        """Serialize the bounded transport projection."""
        return {
            "id": self.transport.value,
            "status": self.status,
            "detail": self.detail,
            "blocker": self.blocker,
            "remediation": self.remediation,
            "durable": self.durable,
            "provider_native_continuity": self.provider_native_continuity,
        }


def default_workbench_transport(harness: Any) -> ExecutionTransport:
    """Choose the product default without claiming unsupported continuity."""
    if harness.spec().id in {"codex-cli", "gemini-cli", "claude-code"}:
        return ExecutionTransport.NATIVE_STRUCTURED
    try:
        admitted_durable_structured_capabilities(harness)
    except (DurableStructuredAdmissionError, TypeError, ValueError):
        pass
    else:
        return ExecutionTransport.NATIVE_STRUCTURED
    return ExecutionTransport.ONE_SHOT


def effective_workbench_transport(
    harness: Any,
    payload: Mapping[str, Any],
    *,
    configured_default: str | ExecutionTransport | None = None,
) -> ExecutionTransport:
    """Resolve explicit input or one harness-scoped backend default.

    An explicit canonical transport is never replaced. Legacy callers that
    explicitly request native invocation retain native-terminal semantics.
    """
    explicit = requested_execution_transport(payload)
    if explicit is not None:
        return explicit
    if str(payload.get("invocation_mode") or "").strip().lower() == "native":
        return ExecutionTransport.NATIVE_TERMINAL
    if isinstance(configured_default, ExecutionTransport):
        selected = configured_default
    elif configured_default is not None and str(configured_default).strip():
        try:
            selected = ExecutionTransport(str(configured_default).strip().lower())
        except ValueError as exc:
            raise DurableStructuredAdmissionError(
                "configured execution transport is invalid"
            ) from exc
    else:
        selected = default_workbench_transport(harness)
    if (
        selected is ExecutionTransport.NATIVE_STRUCTURED
        and default_workbench_transport(harness) is ExecutionTransport.ONE_SHOT
    ):
        return ExecutionTransport.ONE_SHOT
    return selected


def workbench_transport_options(harness: Any) -> tuple[WorkbenchTransportOption, ...]:
    """Project canonical transport choices for API, CLI, and Web clients."""
    spec = harness.spec()
    try:
        capabilities = admitted_durable_structured_capabilities(harness)
    except (DurableStructuredAdmissionError, TypeError, ValueError):
        structured = WorkbenchTransportOption(
            transport=ExecutionTransport.NATIVE_STRUCTURED,
            status="blocked",
            detail="No proven durable structured driver is available.",
            blocker="structured_driver_unavailable",
            remediation=f"giga harness inspect {spec.id} --json",
            durable=True,
            provider_native_continuity=False,
        )
    else:
        snapshot = capability_snapshot_to_dict(capabilities)
        structured = WorkbenchTransportOption(
            transport=ExecutionTransport.NATIVE_STRUCTURED,
            status="ready",
            detail=(
                f"Provider-native {snapshot['protocol']} session with durable "
                "Harness ownership."
            ),
            blocker=None,
            remediation=None,
            durable=True,
            provider_native_continuity=True,
        )
    terminal = WorkbenchTransportOption(
        transport=ExecutionTransport.NATIVE_TERMINAL,
        status="ready" if spec.supports_native_sessions else "blocked",
        detail=(
            "Managed provider CLI/TUI session; continuity remains terminal-owned."
            if spec.supports_native_sessions
            else "This adapter has no native terminal session surface."
        ),
        blocker=None
        if spec.supports_native_sessions
        else "native_terminal_unavailable",
        remediation=None
        if spec.supports_native_sessions
        else f"giga harness inspect {spec.id} --json",
        durable=False,
        provider_native_continuity=False,
    )
    one_shot = WorkbenchTransportOption(
        transport=ExecutionTransport.ONE_SHOT,
        status="ready",
        detail="Compatibility execution without provider-native session continuity.",
        blocker=None,
        remediation=None,
        durable=False,
        provider_native_continuity=False,
    )
    return structured, terminal, one_shot


def workbench_transport_projection(harness: Any) -> dict[str, Any]:
    """Return one complete bounded Workbench transport projection."""
    return {
        "default": default_workbench_transport(harness).value,
        "options": [
            option.to_dict() for option in workbench_transport_options(harness)
        ],
    }
