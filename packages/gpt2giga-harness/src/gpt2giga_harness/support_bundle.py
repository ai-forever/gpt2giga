"""Redaction-safe support bundle projection for one durable Harness run."""

from __future__ import annotations

from collections import Counter
import re
from typing import Any, Mapping

from gpt2giga_harness.registry import HarnessRegistry
from gpt2giga_harness.runtime.models import JobAttempt, RuntimeJob
from gpt2giga_harness.sessions.models import HarnessRun, HarnessStoredEvent
from gpt2giga_harness.sessions.redaction import redact_for_storage
from gpt2giga_harness.types import spec_to_dict


SUPPORT_BUNDLE_SCHEMA_VERSION = 1
_INTERNAL_PATH_RE = re.compile(
    r"(?:/(?:Users|home|root|tmp|private|var|opt|srv|mnt|workspace|workspaces)"
    r"(?:/[^\s\"'`,;:)]+)+)|(?:[A-Za-z]:\\[^\s\"'`,;:)]+)"
)


def build_run_support_bundle(
    *,
    run: HarnessRun,
    job: RuntimeJob,
    attempts: tuple[JobAttempt, ...],
    events: tuple[HarnessStoredEvent, ...],
    registry: HarnessRegistry,
    artifact_inventory: list[dict[str, Any]],
    explanations: list[dict[str, Any]],
    approval_states: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a content-free result bundle safe to attach to a support issue."""
    bundle = {
        "schema_version": SUPPORT_BUNDLE_SCHEMA_VERSION,
        "kind": "gpt2giga_harness_support_bundle",
        "run": _run_summary(run, job, attempts),
        "capability_snapshot": _capability_snapshot(registry, run.harness_id),
        "execution_plan": _execution_plan(run),
        "state_transitions": _state_transitions(attempts, events),
        "diagnostics": _public_diagnostics(run, explanations, approval_states),
        "artifacts": [dict(item) for item in artifact_inventory],
        "reproduction": _reproduction_instructions(run),
        "safety": {
            "content_capture_included": False,
            "prompt_included": False,
            "messages_included": False,
            "event_payloads_included": False,
            "commands_included": False,
            "errors_included": False,
            "approval_context_included": False,
            "artifact_content_included": False,
            "workspace_paths_included": False,
        },
    }
    redacted = redact_for_storage(bundle)
    path_safe = _redact_internal_paths(redacted)
    return dict(path_safe) if isinstance(path_safe, Mapping) else {}


def _run_summary(
    run: HarnessRun,
    job: RuntimeJob,
    attempts: tuple[JobAttempt, ...],
) -> dict[str, Any]:
    return {
        "id": run.id,
        "session_id": run.session_id,
        "job_id": job.id,
        "origin": job.origin,
        "status": run.status.value,
        "job_status": job.status.value,
        "harness_id": run.harness_id,
        "model": run.model,
        "api_mode": run.api_mode.value,
        "capability": run.capability.value,
        "mode": run.mode,
        "invocation_mode": run.invocation_mode.value,
        "attempt_count": len(attempts),
        "max_attempts": job.max_attempts,
        "workflow_id": job.workflow_id,
        "workflow_version": job.workflow_version,
        "schedule_id": job.schedule_id,
        "agent_id": job.agent_id,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "updated_at": run.updated_at,
    }


def _capability_snapshot(
    registry: HarnessRegistry,
    harness_id: str,
) -> dict[str, Any]:
    try:
        spec = spec_to_dict(registry.get(harness_id).spec())
    except KeyError:
        return {"source": "HarnessSpec", "harness_id": harness_id, "available": False}
    return {
        "source": "HarnessSpec.adapter_capabilities",
        "harness_id": harness_id,
        "kind": spec["kind"],
        "capabilities": list(spec["capabilities"]),
        "default_invocation_mode": spec["default_invocation_mode"],
        "default_api_mode": spec["default_api_mode"],
        "protocol_capability_scope": spec["protocol_capability_scope"],
        "headless_continuation": spec["headless_continuation"],
        "adapter_capabilities": dict(spec["adapter_capabilities"]),
    }


def _execution_plan(run: HarnessRun) -> dict[str, Any]:
    preflight = _mapping(run.metadata.get("preflight"))
    readiness = _mapping(preflight.get("readiness"))
    retained = _mapping(readiness.get("plan"))
    workspace_execution = _mapping(run.metadata.get("workspace_execution"))
    return {
        "harness_id": str(retained.get("harness_id") or run.harness_id),
        "invocation_mode": str(
            retained.get("invocation_mode") or run.invocation_mode.value
        ),
        "api_mode": str(retained.get("api_mode") or run.api_mode.value),
        "model": retained.get("model") if "model" in retained else run.model,
        "mode": str(retained.get("mode") or run.mode),
        "workspace_configured": bool(
            retained.get("workspace_configured", run.workspace is not None)
        ),
        "workspace_policy": str(
            retained.get("workspace_policy")
            or workspace_execution.get("policy")
            or "current"
        ),
        "delivery": str(retained.get("delivery") or "durable"),
        "dry_run": bool(retained.get("dry_run")),
    }


def _state_transitions(
    attempts: tuple[JobAttempt, ...],
    events: tuple[HarnessStoredEvent, ...],
) -> list[dict[str, Any]]:
    transitions: list[dict[str, Any]] = []
    for attempt in attempts:
        transitions.append(
            {
                "kind": "attempt",
                "id": attempt.id,
                "run_id": attempt.run_id,
                "attempt_number": attempt.attempt_number,
                "status": attempt.status.value,
                "idempotency_class": attempt.idempotency_class,
                "created_at": attempt.created_at,
                "started_at": attempt.started_at,
                "finished_at": attempt.finished_at,
                "retry_recorded": bool(attempt.retry_reason),
            }
        )
    for event in reversed(events):
        transitions.append(
            {
                "kind": "event",
                "id": event.id,
                "run_id": event.run_id,
                "attempt_id": event.attempt_id,
                "event_type": event.type,
                "span_kind": event.span_kind,
                "status": event.span_status,
                "sequence": event.sequence,
                "created_at": event.created_at,
            }
        )
    transitions.sort(key=lambda item: (str(item.get("created_at") or ""), item["id"]))
    return transitions


def _public_diagnostics(
    run: HarnessRun,
    explanations: list[dict[str, Any]],
    approval_states: list[dict[str, Any]],
) -> dict[str, Any]:
    preflight = _mapping(run.metadata.get("preflight"))
    findings = tuple(
        item for item in preflight.get("findings", ()) if isinstance(item, Mapping)
    )
    readiness = _mapping(preflight.get("readiness"))
    readiness_findings = tuple(
        item for item in readiness.get("findings", ()) if isinstance(item, Mapping)
    )
    finding_severities = Counter(
        str(item.get("severity") or "unknown") for item in findings
    )
    finding_codes = sorted(
        {str(item.get("code")) for item in findings if item.get("code")}
    )
    return {
        "preflight": {
            "available": bool(preflight),
            "ok": preflight.get("ok"),
            "hard_block": preflight.get("hard_block"),
            "max_severity": preflight.get("max_severity"),
            "finding_counts": dict(sorted(finding_severities.items())),
            "finding_codes": finding_codes,
        },
        "readiness": {
            "available": bool(readiness),
            "schema_version": readiness.get("schema_version"),
            "ok": readiness.get("ok"),
            "blocked": readiness.get("blocked"),
            "summary": dict(_mapping(readiness.get("summary"))),
            "findings": [_readiness_finding(item) for item in readiness_findings],
        },
        "operational_explanations": [dict(item) for item in explanations],
        "approval_states": [dict(item) for item in approval_states],
    }


def _readiness_finding(value: Mapping[str, Any]) -> dict[str, Any]:
    remediation = tuple(
        item for item in value.get("remediation", ()) if isinstance(item, Mapping)
    )
    return {
        "id": value.get("id"),
        "category": value.get("category"),
        "status": value.get("status"),
        "required": bool(value.get("required")),
        "summary": value.get("summary"),
        "remediation": [
            {
                "message": item.get("message"),
                "command": item.get("command"),
            }
            for item in remediation
        ],
    }


def _reproduction_instructions(run: HarnessRun) -> dict[str, Any]:
    return {
        "content_required_from_operator": True,
        "steps": [
            {
                "order": 1,
                "instruction": "Verify the current installation and selected environment.",
                "command": "giga doctor --json",
            },
            {
                "order": 2,
                "instruction": "Inspect the selected adapter contract and availability.",
                "command": f"giga harness inspect {run.harness_id} --json",
            },
            {
                "order": 3,
                "instruction": "Compare retained state without replaying the run.",
                "api_path": f"/api/runs/{run.id}/summary",
            },
            {
                "order": 4,
                "instruction": (
                    "Supply the original task content separately, review it for secrets, "
                    "and start a new run only when reproduction is authorized."
                ),
            },
        ],
        "omitted": [
            "original task content",
            "captured model or tool content",
            "artifact bodies",
            "approval context",
            "workspace paths",
        ],
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _redact_internal_paths(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _redact_internal_paths(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_redact_internal_paths(item) for item in value)
    if isinstance(value, list):
        return [_redact_internal_paths(item) for item in value]
    if isinstance(value, str):
        return _INTERNAL_PATH_RE.sub("<internal-path>", value)
    return value
