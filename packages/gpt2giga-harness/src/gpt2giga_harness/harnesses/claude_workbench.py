"""Truthful Claude Code integration pack for the provider-neutral Workbench."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from gpt2giga_harness.cli_capabilities import CliCapabilitySnapshot
from gpt2giga_harness.harnesses.claude_code import ClaudeStreamParser
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
class ClaudeWorkbenchAdmission:
    """Content-free truth for Claude's native, one-shot, and durable lanes."""

    version: str | None
    native_handoff: bool
    structured_one_shot: bool
    durable_embedded: bool
    reason: str


def admit_claude_workbench(snapshot: CliCapabilitySnapshot) -> ClaudeWorkbenchAdmission:
    """Admit reviewed one-shot decoding without claiming durable embedding."""
    integration = WORKBENCH_INTEGRATION_SPECS["claude"]
    version = snapshot.parsed_version or snapshot.version
    status = integration.version_window.status(version)
    native_handoff = bool(snapshot.command)
    one_shot = (
        status is VersionEvidenceStatus.IN_WINDOW
        and snapshot.compatible
        and snapshot.event_schema == "claude-stream-json-v1"
        and snapshot.capabilities.get("stream-json", False)
    )
    if one_shot:
        reason = "one_shot_admitted"
    elif status is not VersionEvidenceStatus.IN_WINDOW:
        reason = f"one_shot_{status.value}"
    elif not snapshot.compatible:
        reason = "one_shot_contract_unproven"
    elif snapshot.event_schema != "claude-stream-json-v1":
        reason = "one_shot_schema_unproven"
    else:
        reason = "one_shot_stream_json_unavailable"
    return ClaudeWorkbenchAdmission(
        version=version,
        native_handoff=native_handoff,
        structured_one_shot=one_shot,
        durable_embedded=False,
        reason=reason,
    )


def claude_contextual_capabilities(
    snapshot: CliCapabilitySnapshot,
    *,
    transport: str,
    process_owner: str,
    session_generation: int,
    policy_allows: bool,
) -> tuple[CapabilityEvaluation, ...]:
    """Evaluate Claude capabilities against their actual transport owner."""
    integration = WORKBENCH_INTEGRATION_SPECS["claude"]
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


class ClaudeOneShotEventDecoder:
    """Decode reviewed stream-JSON without creating a durable-session claim."""

    def __init__(self, *, session_id: str, workspace_id: str) -> None:
        self.session_id = session_id
        self.workspace_id = workspace_id
        self._parser = ClaudeStreamParser()

    def decode(self, raw_event: Mapping[str, Any]) -> tuple[WorkbenchEventDraft, ...]:
        """Normalize one one-shot envelope and discard provider-only fields."""
        return tuple(self._draft(event) for event in self._parser(raw_event))

    def _draft(self, event: HarnessEvent) -> WorkbenchEventDraft:
        payload_type, payload = _workbench_payload(event)
        return WorkbenchEventDraft(
            payload_type=payload_type,
            payload=payload,
            provider="claude",
            session_id=self.session_id,
            workspace_id=self.workspace_id,
            source="claude_stream_json_decoder",
            correlation_id=self.session_id,
        )


def _workbench_payload(event: HarnessEvent) -> tuple[str, dict[str, Any]]:
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
    raise ValueError("unsupported Claude one-shot event")
