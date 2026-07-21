"""Gemini CLI integration pack for the provider-neutral Workbench."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from gpt2giga_harness.cli_capabilities import CliCapabilitySnapshot
from gpt2giga_harness.harnesses.gemini_cli import GeminiStreamParser
from gpt2giga_harness.native_cli_contracts import (
    WORKBENCH_INTEGRATION_SPECS,
    CapabilityContext,
    CapabilityEvaluation,
    VersionEvidenceStatus,
    evaluate_contextual_capability,
)
from gpt2giga_harness.types import HarnessEvent
from gpt2giga_harness.workbench_protocol import WorkbenchEventDraft


@dataclass(frozen=True)
class GeminiWorkbenchAdmission:
    """Content-free admission result for reviewed Gemini structured lanes."""

    version: str | None
    native_handoff: bool
    structured_one_shot: bool
    structured_acp: bool
    reason: str


def admit_gemini_workbench(snapshot: CliCapabilitySnapshot) -> GeminiWorkbenchAdmission:
    """Admit only the reviewed 0.46 stream and ACP capability contract."""
    integration = WORKBENCH_INTEGRATION_SPECS["gemini"]
    version = snapshot.parsed_version or snapshot.version
    status = integration.version_window.status(version)
    in_window = status is VersionEvidenceStatus.IN_WINDOW and snapshot.compatible
    one_shot = (
        in_window
        and snapshot.event_schema == "gemini-stream-json-v1"
        and snapshot.capabilities.get("stream-json", False)
    )
    acp = (
        in_window
        and snapshot.capabilities.get("--acp", False)
        and snapshot.capabilities.get("--experimental-acp", False)
    )
    if acp:
        reason = "acp_admitted"
    elif status is not VersionEvidenceStatus.IN_WINDOW:
        reason = f"acp_{status.value}"
    elif not snapshot.compatible:
        reason = "acp_contract_unproven"
    else:
        reason = "acp_capability_unproven"
    return GeminiWorkbenchAdmission(
        version=version,
        native_handoff=bool(snapshot.command),
        structured_one_shot=one_shot,
        structured_acp=acp,
        reason=reason,
    )


def gemini_contextual_capabilities(
    snapshot: CliCapabilitySnapshot,
    *,
    transport: str,
    process_owner: str,
    session_generation: int,
    policy_allows: bool,
) -> tuple[CapabilityEvaluation, ...]:
    """Evaluate Gemini capabilities against their actual transport owner."""
    integration = WORKBENCH_INTEGRATION_SPECS["gemini"]
    context = CapabilityContext(
        version=snapshot.parsed_version or snapshot.version,
        transport=transport,
        process_owner=process_owner,
        session_generation=session_generation,
        policy_allows=policy_allows,
    )
    return tuple(
        evaluate_contextual_capability(integration, capability, context)
        for capability in integration.capabilities
    )


class GeminiAcpEventDecoder:
    """Decode reviewed normalized ACP events into common Workbench payloads."""

    def __init__(self, *, session_id: str, workspace_id: str) -> None:
        self.session_id = session_id
        self.workspace_id = workspace_id

    def decode(self, raw_event: Mapping[str, Any]) -> WorkbenchEventDraft:
        """Normalize one ACP driver event and discard its provider envelope."""
        event_type = str(raw_event.get("type") or "")
        payload = _mapping(raw_event.get("payload"))
        payload_type, normalized = _workbench_payload(event_type, payload)
        correlation_id = _identity(
            payload.get("tool_call_id"), fallback=self.session_id
        )
        generation = raw_event.get("generation")
        idempotency_key = (
            f"gemini:{event_type}:{correlation_id}:{generation}"
            if isinstance(generation, int)
            else None
        )
        return WorkbenchEventDraft(
            payload_type=payload_type,
            payload=normalized,
            provider="gemini",
            session_id=self.session_id,
            workspace_id=self.workspace_id,
            source="gemini_acp_decoder",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )


class GeminiOneShotEventDecoder:
    """Decode reviewed stream-JSON without changing native L0 output."""

    def __init__(self, *, session_id: str, workspace_id: str) -> None:
        self.session_id = session_id
        self.workspace_id = workspace_id
        self._parser = GeminiStreamParser()

    def decode(self, raw_event: Mapping[str, Any]) -> tuple[WorkbenchEventDraft, ...]:
        """Normalize one one-shot envelope and discard provider-only fields."""
        return tuple(self._draft(event) for event in self._parser(raw_event))

    def _draft(self, event: HarnessEvent) -> WorkbenchEventDraft:
        payload_type, payload = _one_shot_workbench_payload(event)
        return WorkbenchEventDraft(
            payload_type=payload_type,
            payload=payload,
            provider="gemini",
            session_id=self.session_id,
            workspace_id=self.workspace_id,
            source="gemini_stream_json_decoder",
            correlation_id=self.session_id,
        )


def _one_shot_workbench_payload(event: HarnessEvent) -> tuple[str, dict[str, Any]]:
    payload = dict(event.payload)
    if event.type == "message_delta":
        return "message.delta", {
            "role": "assistant",
            "delta": str(payload.get("delta") or ""),
        }
    if event.type == "usage":
        return "usage.updated", {
            key: value
            for key, value in payload.items()
            if key in {"input_tokens", "output_tokens", "total_tokens"}
            and isinstance(value, int)
        }
    if event.type.startswith("tool_call_"):
        status = {
            "tool_call_started": "running",
            "tool_call_delta": "running",
            "tool_call_finished": str(payload.get("status") or "completed"),
        }[event.type]
        return "tool.updated", {
            key: value
            for key, value in {
                "id": str(payload.get("tool_call_id") or "tool"),
                "kind": str(payload.get("name") or "tool"),
                "status": status,
                "arguments": payload.get("arguments"),
                "arguments_delta": payload.get("arguments_delta"),
                "result": payload.get("result"),
            }.items()
            if value is not None
        }
    if event.type == "stderr_delta":
        return "error", {"message": str(payload.get("delta") or event.message)}
    raise ValueError("unsupported Gemini one-shot event")


def _workbench_payload(
    event_type: str, payload: Mapping[str, Any]
) -> tuple[str, dict[str, Any]]:
    if event_type in {"output_delta", "reasoning_delta"}:
        content = _mapping(payload.get("content"))
        text = content.get("text")
        if not isinstance(text, str):
            raise ValueError("Gemini ACP text content is invalid")
        if event_type == "output_delta":
            return "message.delta", {"role": "assistant", "delta": text}
        return "reasoning.delta", {"delta": text, "visibility": "full"}
    if event_type.startswith("tool_"):
        return "tool.updated", {
            "id": str(payload.get("tool_call_id") or "tool"),
            "kind": str(payload.get("kind") or payload.get("title") or "tool"),
            "status": str(payload.get("status") or event_type.removeprefix("tool_")),
        }
    if event_type == "plan_update":
        entries = payload.get("entries")
        if not isinstance(entries, list):
            raise ValueError("Gemini ACP plan entries are invalid")
        return "plan.updated", {"entries": entries}
    if event_type == "usage_update":
        return "usage.updated", {
            key: value
            for key, value in {
                "used": payload.get("used"),
                "size": payload.get("size"),
            }.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
    if event_type == "session_state":
        return "task.updated", {
            "kind": "session",
            "id": "gemini-session",
            "status": str(payload.get("kind") or "updated"),
        }
    raise ValueError("unsupported Gemini ACP event")


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _identity(value: Any, *, fallback: str) -> str:
    text = str(value or fallback)
    return "".join(
        character if character.isalnum() or character in "._:@+~-" else "_"
        for character in text
    )[:256]
