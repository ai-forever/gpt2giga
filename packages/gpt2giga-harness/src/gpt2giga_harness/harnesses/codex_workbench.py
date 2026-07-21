"""Codex app-server integration pack for the provider-neutral Workbench."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from gpt2giga_harness.cli_capabilities import CliCapabilitySnapshot
from gpt2giga_harness.native_cli_contracts import (
    WORKBENCH_INTEGRATION_SPECS,
    CapabilityContext,
    CapabilityEvaluation,
    VersionEvidenceStatus,
    evaluate_contextual_capability,
)
from gpt2giga_harness.workbench_protocol import WorkbenchEventDraft


@dataclass(frozen=True)
class CodexWorkbenchAdmission:
    """Content-free admission result for the reviewed Codex L2 transport."""

    version: str | None
    admitted: bool
    reason: str


def admit_codex_workbench(snapshot: CliCapabilitySnapshot) -> CodexWorkbenchAdmission:
    """Admit only the exact reviewed version and app-server capability window."""
    integration = WORKBENCH_INTEGRATION_SPECS["codex"]
    version = snapshot.parsed_version or snapshot.version
    status = integration.version_window.status(version)
    if status is not VersionEvidenceStatus.IN_WINDOW:
        return CodexWorkbenchAdmission(version, False, f"version_{status.value}")
    if not snapshot.compatible or not snapshot.capabilities.get("app-server", False):
        return CodexWorkbenchAdmission(version, False, "app_server_unavailable")
    return CodexWorkbenchAdmission(version, True, "structured_admitted")


def codex_contextual_capabilities(
    snapshot: CliCapabilitySnapshot,
    *,
    session_generation: int,
    policy_allows: bool,
) -> tuple[CapabilityEvaluation, ...]:
    """Evaluate the Codex pack against the current Workbench execution context."""
    integration = WORKBENCH_INTEGRATION_SPECS["codex"]
    context = CapabilityContext(
        version=snapshot.parsed_version or snapshot.version,
        transport="app-server",
        process_owner="harness",
        session_generation=session_generation,
        policy_allows=policy_allows,
    )
    return tuple(
        evaluate_contextual_capability(integration, capability, context)
        for capability in integration.capabilities
    )


class CodexAppServerEventDecoder:
    """Decode reviewed app-server notifications into common Workbench payloads."""

    def __init__(self, *, session_id: str, workspace_id: str) -> None:
        self.session_id = session_id
        self.workspace_id = workspace_id

    def decode(self, raw_event: Mapping[str, Any]) -> WorkbenchEventDraft:
        """Normalize one notification and discard its provider envelope."""
        method = str(raw_event.get("method") or "")
        params = _mapping(raw_event.get("params"))
        payload_type, payload = _normalized_payload(method, params)
        correlation = _identity(
            params.get("turnId") or params.get("threadId") or params.get("itemId"),
            fallback="codex-event",
        )
        item = _mapping(params.get("item"))
        event_identity = _identity(
            item.get("id") or params.get("itemId"), fallback=method.replace("/", ".")
        )
        provider_event_id = params.get("eventId") or raw_event.get("id")
        idempotency_key = (
            f"codex:{_identity(provider_event_id, fallback='event')}"
            if provider_event_id is not None
            else (
                f"codex:{_identity(method, fallback='event')}:{event_identity}"
                if method
                in {"item/started", "item/completed", "turn/started", "turn/completed"}
                else None
            )
        )
        return WorkbenchEventDraft(
            payload_type=payload_type,
            payload=payload,
            provider="codex",
            session_id=self.session_id,
            workspace_id=self.workspace_id,
            source="codex_app_server_decoder",
            correlation_id=correlation,
            idempotency_key=idempotency_key,
        )


def _normalized_payload(
    method: str, params: Mapping[str, Any]
) -> tuple[str, dict[str, Any]]:
    if method == "item/agentMessage/delta":
        return "message.delta", {
            "role": "assistant",
            "delta": str(params.get("delta") or ""),
        }
    if method in {"item/reasoning/summaryTextDelta", "item/reasoning/textDelta"}:
        return "reasoning.delta", {
            "delta": str(params.get("delta") or ""),
            "visibility": "summary" if "summary" in method else "full",
        }
    if method == "thread/tokenUsage/updated":
        usage = _mapping(_mapping(params.get("tokenUsage")).get("last"))
        return "usage.updated", {
            key: value
            for key, value in {
                "input_tokens": usage.get("inputTokens"),
                "output_tokens": usage.get("outputTokens"),
                "total_tokens": usage.get("totalTokens"),
            }.items()
            if isinstance(value, int)
        }
    if method in {"turn/started", "turn/completed"}:
        turn = _mapping(params.get("turn"))
        return "task.updated", {
            "kind": "turn",
            "id": _identity(turn.get("id"), fallback="turn"),
            "status": str(turn.get("status") or method.rsplit("/", 1)[-1]),
        }
    if method in {"item/started", "item/completed"}:
        item = _mapping(params.get("item"))
        return "tool.updated", {
            "id": _identity(item.get("id"), fallback="tool"),
            "kind": str(item.get("type") or "unknown"),
            "status": str(item.get("status") or method.rsplit("/", 1)[-1]),
        }
    if method == "error":
        return "error", {
            "message": str(params.get("message") or "Codex app-server error")
        }
    raise ValueError("unsupported Codex app-server notification")


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _identity(value: Any, *, fallback: str) -> str:
    text = str(value or fallback)
    return "".join(
        character if character.isalnum() or character in "._:@+~-" else "_"
        for character in text
    )[:256]
