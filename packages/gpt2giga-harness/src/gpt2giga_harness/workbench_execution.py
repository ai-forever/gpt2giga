"""Workbench transport defaults and redaction-safe capability projections."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from gpt2giga_harness.execution import ExecutionTransport
from gpt2giga_harness.product_capabilities import (
    AdmissionStatus,
    AuthorityLevel,
    ProductCapabilityError,
    TaskIntent,
    legacy_mode_compatibility_receipt,
    migrate_legacy_capability_request,
)
from gpt2giga_harness.runtime.structured import (
    DurableStructuredAdmissionError,
    admitted_durable_structured_capabilities,
    requested_execution_transport,
)
from gpt2giga_harness.structured_sessions import capability_snapshot_to_dict
from gpt2giga_harness.types import HarnessCapability


WORKBENCH_ADMISSION_SCHEMA_VERSION = 1


class WorkbenchKind(str, Enum):
    """Describe the ordinary product surface without naming a transport."""

    CODING_AGENT = "coding_agent"
    DIRECT_CHAT = "direct_chat"


@dataclass(frozen=True)
class WorkbenchAdmission:
    """Bind product intent to one truthful internal execution route."""

    kind: WorkbenchKind
    intent: TaskIntent
    authority: AuthorityLevel
    capability: HarnessCapability
    transport: ExecutionTransport
    invocation_mode: str
    status: AdmissionStatus
    why: tuple[str, ...]
    recovery: tuple[str, ...]
    diagnostics: Mapping[str, Any]
    input_source: str
    mode: str
    schema_version: int = WORKBENCH_ADMISSION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Serialize the redaction-safe execution receipt."""
        return {
            "schema_version": self.schema_version,
            "kind": self.kind.value,
            "intent": self.intent.value,
            "authority": self.authority.value,
            "capability": self.capability.value,
            "status": self.status.value,
            "why": list(self.why),
            "recovery": list(self.recovery),
            "input_source": self.input_source,
            "mode": self.mode,
            "diagnostics": dict(self.diagnostics),
        }


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


def admit_workbench_execution(
    harness: Any,
    payload: Mapping[str, Any],
    *,
    configured_default: str | ExecutionTransport | None = None,
) -> WorkbenchAdmission:
    """Select an internal route from product intent or a legacy machine request."""
    if _has_product_request(payload):
        return _admit_product_request(harness, payload)
    return _admit_legacy_request(
        harness,
        payload,
        configured_default=configured_default,
    )


def workbench_admission_projection(harness: Any) -> dict[str, Any]:
    """Project ordinary product modes while keeping transport diagnostic-only."""
    capabilities = {
        capability.value for capability in tuple(harness.spec().capabilities or ())
    }
    modes = []
    for kind, capability in (
        (WorkbenchKind.CODING_AGENT, HarnessCapability.AGENT_CLI),
        (WorkbenchKind.DIRECT_CHAT, HarnessCapability.CHAT_COMPLETIONS),
    ):
        if capability.value not in capabilities:
            modes.append(
                {
                    "id": kind.value,
                    "status": AdmissionStatus.BLOCKED.value,
                    "why": ["harness_capability_unavailable"],
                    "recovery": ["select_compatible_harness"],
                }
            )
            continue
        sample = admit_workbench_execution(
            harness,
            {
                "workbench_kind": kind.value,
                "task_intent": (
                    TaskIntent.CHANGE.value
                    if kind is WorkbenchKind.CODING_AGENT
                    else TaskIntent.ASK.value
                ),
                "authority": (
                    AuthorityLevel.WORKSPACE_WRITE.value
                    if kind is WorkbenchKind.CODING_AGENT
                    else AuthorityLevel.READ_ONLY.value
                ),
            },
        )
        modes.append(
            {
                "id": kind.value,
                "status": sample.status.value,
                "why": list(sample.why),
                "recovery": list(sample.recovery),
            }
        )
    return {
        "schema_version": WORKBENCH_ADMISSION_SCHEMA_VERSION,
        "modes": modes,
    }


def _admit_product_request(
    harness: Any,
    payload: Mapping[str, Any],
) -> WorkbenchAdmission:
    kind = _parse_enum(
        payload.get("workbench_kind"),
        WorkbenchKind,
        "workbench kind",
    )
    intent = _parse_enum(payload.get("task_intent"), TaskIntent, "task intent")
    authority = _parse_enum(
        payload.get("authority"),
        AuthorityLevel,
        "authority",
    )
    capability = (
        HarnessCapability.AGENT_CLI
        if kind is WorkbenchKind.CODING_AGENT
        else HarnessCapability.CHAT_COMPLETIONS
    )
    if capability not in tuple(harness.spec().capabilities or ()):
        raise ProductCapabilityError(f"{harness.spec().id} does not admit {kind.value}")

    options = {
        option.transport: option for option in workbench_transport_options(harness)
    }
    reasons: list[str] = []
    recovery: list[str] = []
    status = AdmissionStatus.AVAILABLE
    fallback: str | None = None
    if kind is WorkbenchKind.DIRECT_CHAT:
        transport = ExecutionTransport.ONE_SHOT
        provider_path = "direct_chat"
    else:
        structured = options[ExecutionTransport.NATIVE_STRUCTURED]
        if structured.status == "ready":
            transport = ExecutionTransport.NATIVE_STRUCTURED
            provider_path = _structured_provider_path(harness)
        else:
            transport = ExecutionTransport.ONE_SHOT
            provider_path = _one_shot_provider_path(harness)
            status = AdmissionStatus.DEGRADED
            fallback = "native_structured_to_one_shot"
            reasons.append("provider_native_continuity_unavailable")
            recovery.append(structured.remediation or "inspect_harness_capabilities")

    explicit_transport = requested_execution_transport(payload)
    if explicit_transport is not None:
        if kind is WorkbenchKind.DIRECT_CHAT and explicit_transport is not transport:
            raise ProductCapabilityError(
                "direct chat does not admit a provider-session transport override"
            )
        option = options[explicit_transport]
        if option.status != "ready":
            raise ProductCapabilityError(
                f"requested transport is unavailable: {explicit_transport.value}"
            )
        transport = explicit_transport
        provider_path = _provider_path(harness, transport)
        status = AdmissionStatus.AVAILABLE
        fallback = None
        reasons = [
            reason
            for reason in reasons
            if reason != "provider_native_continuity_unavailable"
        ]
        recovery = [
            item
            for item in recovery
            if item != "inspect_harness_capabilities"
            and not item.startswith("giga harness inspect ")
        ]
        reasons.append("machine_transport_override_admitted")

    mode, mode_reason = _mode_for_product_request(intent, authority)
    if mode_reason is not None:
        status = AdmissionStatus.DEGRADED
        reasons.append(mode_reason)
        recovery.append("choose_workspace_write_for_change")
    reasons.append(f"admitted_provider_path:{provider_path}")
    invocation_mode = (
        "native" if transport is ExecutionTransport.NATIVE_TERMINAL else "headless"
    )
    return WorkbenchAdmission(
        kind=kind,
        intent=intent,
        authority=authority,
        capability=capability,
        transport=transport,
        invocation_mode=invocation_mode,
        status=status,
        why=tuple(dict.fromkeys(reasons)),
        recovery=tuple(dict.fromkeys(recovery)),
        diagnostics={
            "content_free": True,
            "harness_id": harness.spec().id,
            "provider_path": provider_path,
            "execution_transport": transport.value,
            "provider_native_continuity": (
                transport is ExecutionTransport.NATIVE_STRUCTURED
            ),
            "fallback": fallback,
        },
        input_source=(
            "product_with_machine_override"
            if explicit_transport is not None
            else "product"
        ),
        mode=mode,
    )


def _admit_legacy_request(
    harness: Any,
    payload: Mapping[str, Any],
    *,
    configured_default: str | ExecutionTransport | None,
) -> WorkbenchAdmission:
    transport = effective_workbench_transport(
        harness,
        payload,
        configured_default=configured_default,
    )
    capabilities = tuple(harness.spec().capabilities or ())
    raw_capability = str(
        payload.get("capability") or (capabilities[0].value if capabilities else "")
    ).strip()
    try:
        capability = HarnessCapability(raw_capability)
    except ValueError:
        capability = (
            capabilities[0] if capabilities else HarnessCapability.CHAT_COMPLETIONS
        )
        capability_reason = "legacy_capability_unmapped"
    else:
        capability_reason = None
    kind = (
        WorkbenchKind.CODING_AGENT
        if capability is HarnessCapability.AGENT_CLI
        else WorkbenchKind.DIRECT_CHAT
    )
    mode = str(payload.get("mode") or "plan").strip().lower()
    compatibility = legacy_mode_compatibility_receipt(mode)
    try:
        migrated = migrate_legacy_capability_request({"mode": mode})
    except ProductCapabilityError:
        intent = TaskIntent.ASK
        authority = AuthorityLevel.READ_ONLY
        status = AdmissionStatus.DEGRADED
        reasons = ("legacy_mode_unmapped",)
        recovery = ("send_product_capability_fields",)
    else:
        intent = migrated.intent
        authority = migrated.authority
        status = AdmissionStatus.AVAILABLE
        reasons = ("legacy_profile_migrated", "legacy_mode_alias")
        recovery = ()
    if capability_reason is not None:
        status = AdmissionStatus.DEGRADED
        reasons = (*reasons, capability_reason)
        recovery = (*recovery, "send_product_capability_fields")
    provider_path = _provider_path(harness, transport)
    return WorkbenchAdmission(
        kind=kind,
        intent=intent,
        authority=authority,
        capability=capability,
        transport=transport,
        invocation_mode=(
            "native" if transport is ExecutionTransport.NATIVE_TERMINAL else "headless"
        ),
        status=status,
        why=(*reasons, f"admitted_provider_path:{provider_path}"),
        recovery=recovery,
        diagnostics={
            "content_free": True,
            "harness_id": harness.spec().id,
            "provider_path": provider_path,
            "execution_transport": transport.value,
            "provider_native_continuity": (
                transport is ExecutionTransport.NATIVE_STRUCTURED
            ),
            "fallback": None,
            "compatibility": compatibility,
        },
        input_source="legacy_machine",
        mode=mode,
    )


def _has_product_request(payload: Mapping[str, Any]) -> bool:
    fields = {"workbench_kind", "task_intent", "authority"}
    present = fields & set(payload)
    if present and present != fields:
        missing = ", ".join(sorted(fields - present))
        raise ProductCapabilityError(f"incomplete product request; missing {missing}")
    return present == fields


def _mode_for_product_request(
    intent: TaskIntent,
    authority: AuthorityLevel,
) -> tuple[str, str | None]:
    if intent is TaskIntent.ASK:
        return "plan", None
    if intent is TaskIntent.REVIEW:
        return "read", None
    if authority is AuthorityLevel.WORKSPACE_WRITE:
        return "edit", None
    return "read", "change_intent_limited_by_read_only_authority"


def _provider_path(harness: Any, transport: ExecutionTransport) -> str:
    if transport is ExecutionTransport.NATIVE_STRUCTURED:
        return _structured_provider_path(harness)
    if transport is ExecutionTransport.NATIVE_TERMINAL:
        return "provider_owned_terminal"
    return _one_shot_provider_path(harness)


def _structured_provider_path(harness: Any) -> str:
    try:
        snapshot = capability_snapshot_to_dict(
            admitted_durable_structured_capabilities(harness)
        )
    except (DurableStructuredAdmissionError, TypeError, ValueError):
        return "durable_structured"
    protocol = str(snapshot.get("protocol") or "")
    if protocol.startswith("codex-app-server"):
        return "codex_app_server"
    if "gemini-acp" in protocol:
        return "gemini_acp"
    return "durable_structured"


def _one_shot_provider_path(harness: Any) -> str:
    if harness.spec().id == "claude-code":
        return "claude_provider_owned_one_shot"
    if harness.spec().id == "direct-chat":
        return "direct_chat"
    return "provider_one_shot"


def _parse_enum(value: Any, enum_type: type[Enum], label: str) -> Any:
    normalized = str(value or "").strip().lower()
    try:
        return enum_type(normalized)
    except ValueError as exc:
        raise ProductCapabilityError(f"{label} is invalid") from exc
