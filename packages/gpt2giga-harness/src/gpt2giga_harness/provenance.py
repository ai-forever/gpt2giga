"""Run provenance and replay helpers for the Unified Harness."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from gpt2giga_harness.gigachat_compatibility import (
    gigachat_compatibility_evidence,
)
from gpt2giga_harness.project import project_to_dict, resolve_project
from gpt2giga_harness.reviewed_evidence import reviewed_evidence_manifest
from gpt2giga_harness.runtime.policy import PolicyAuditEvent
from gpt2giga_harness.sessions.models import (
    HarnessRawRecord,
    HarnessRun,
    HarnessSession,
    HarnessStoredEvent,
    event_to_dict,
    raw_record_to_dict,
)
from gpt2giga_harness.sessions.redaction import redact_for_storage
from gpt2giga_harness.types import HarnessSpec, spec_to_dict


@dataclass(frozen=True)
class RunProvenance:
    """Auditable, redacted snapshot for one stored harness run."""

    run_id: str
    session_id: str
    created_at: str
    updated_at: str
    project: Mapping[str, Any]
    git: Mapping[str, Any]
    harness: Mapping[str, Any]
    request: Mapping[str, Any]
    execution: Mapping[str, Any]
    records: Mapping[str, Any]
    gigachat_compatibility: Mapping[str, Any] | None
    reviewed_evidence: Mapping[str, Any] | None
    replay_request: Mapping[str, Any]


def build_run_provenance(
    run: HarnessRun,
    *,
    session: HarnessSession | None = None,
    spec: HarnessSpec | None = None,
    raw_requests: tuple[HarnessRawRecord, ...] = (),
    raw_responses: tuple[HarnessRawRecord, ...] = (),
    events: tuple[HarnessStoredEvent, ...] = (),
    policy_audit_events: tuple[PolicyAuditEvent, ...] = (),
    data_dir: str | Path | None = None,
) -> RunProvenance:
    """Build a redacted provenance snapshot for a run."""
    run_raw_requests = _records_for_run(raw_requests, run.id)
    run_raw_responses = _records_for_run(raw_responses, run.id)
    run_events = tuple(event for event in events if event.run_id == run.id)
    raw_request = run_raw_requests[-1] if run_raw_requests else None
    raw_response = run_raw_responses[-1] if run_raw_responses else None
    raw_request_payload = _mapping(raw_request.payload if raw_request else None)
    raw_response_payload = _mapping(raw_response.payload if raw_response else None)
    request = _request_provenance(run, raw_request_payload)
    execution = _execution_provenance(run, raw_response_payload)
    records = _record_provenance(
        raw_requests=run_raw_requests,
        raw_responses=run_raw_responses,
        events=run_events,
    )
    reviewed_evidence = reviewed_evidence_manifest(run.id, policy_audit_events)
    compatibility_evidence = gigachat_compatibility_evidence(run, run_events)
    return RunProvenance(
        run_id=run.id,
        session_id=run.session_id,
        created_at=run.created_at,
        updated_at=run.updated_at,
        project=_project_provenance(run, session=session, data_dir=data_dir),
        git=_git_provenance(run.workspace),
        harness=_harness_provenance(run, spec),
        request=request,
        execution=execution,
        records=records,
        gigachat_compatibility=compatibility_evidence,
        reviewed_evidence=reviewed_evidence,
        replay_request=build_replay_request(
            run,
            raw_request=raw_request,
            reviewed_evidence=reviewed_evidence,
        ),
    )


def run_provenance_to_dict(provenance: RunProvenance) -> dict[str, Any]:
    """Serialize run provenance for storage and API responses."""
    return {
        "run_id": provenance.run_id,
        "session_id": provenance.session_id,
        "created_at": provenance.created_at,
        "updated_at": provenance.updated_at,
        "project": dict(provenance.project),
        "git": dict(provenance.git),
        "harness": dict(provenance.harness),
        "request": dict(provenance.request),
        "execution": dict(provenance.execution),
        "records": dict(provenance.records),
        "gigachat_compatibility": (
            dict(provenance.gigachat_compatibility)
            if provenance.gigachat_compatibility is not None
            else None
        ),
        "reviewed_evidence": (
            dict(provenance.reviewed_evidence)
            if provenance.reviewed_evidence is not None
            else None
        ),
        "replay_request": dict(provenance.replay_request),
    }


def build_replay_request(
    run: HarnessRun,
    *,
    raw_request: HarnessRawRecord | None = None,
    reviewed_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reconstruct a safe request payload for replaying one run."""
    payload = _mapping(raw_request.payload if raw_request else None)
    original_prompt = _optional_text(payload.get("original_prompt"))
    prompt = original_prompt or _optional_text(payload.get("prompt")) or run.prompt
    extra = _safe_extra(_mapping(payload.get("extra")))
    extra["isolated_history"] = True
    extra["replay_of_run_id"] = run.id
    if reviewed_evidence is not None:
        extra["source_reviewed_evidence"] = dict(reviewed_evidence)
    replay = {
        "harness_id": run.harness_id,
        "prompt": prompt,
        "model": run.model,
        "api_mode": run.api_mode.value,
        "capability": run.capability.value,
        "mode": run.mode,
        "invocation_mode": run.invocation_mode.value,
        "stream": bool(payload.get("stream")),
        "workspace": run.workspace,
        "workspace_policy": _workspace_policy(run, payload),
        "extra": extra,
    }
    attachment_ids = _attachment_ids(run, payload)
    if attachment_ids:
        replay["attachment_ids"] = attachment_ids
    return _redacted_mapping(replay)


def _request_provenance(
    run: HarnessRun,
    raw_request_payload: Mapping[str, Any],
) -> dict[str, Any]:
    metadata = _mapping(run.metadata)
    original_prompt = _optional_text(raw_request_payload.get("original_prompt"))
    effective_prompt = _optional_text(raw_request_payload.get("prompt"))
    prompt = original_prompt or effective_prompt or run.prompt
    project_memory = _mapping(metadata.get("project_memory"))
    payload = {
        "prompt": prompt,
        "effective_prompt": effective_prompt if effective_prompt != prompt else None,
        "prompt_was_augmented": bool(
            effective_prompt is not None and effective_prompt != prompt
        ),
        "model": run.model,
        "api_mode": run.api_mode.value,
        "capability": run.capability.value,
        "mode": run.mode,
        "invocation_mode": run.invocation_mode.value,
        "stream": bool(raw_request_payload.get("stream")),
        "workspace": run.workspace,
        "effective_workspace": _optional_text(
            raw_request_payload.get("effective_workspace")
        ),
        "workspace_policy": _workspace_policy(run, raw_request_payload),
        "requested_workspace_policy": _optional_text(
            raw_request_payload.get("requested_workspace_policy")
        ),
        "attachment_ids": _attachment_ids(run, raw_request_payload),
        "attachments": _attachment_summaries(run, raw_request_payload),
        "project_memory": project_memory or None,
        "extra": _safe_extra(_mapping(raw_request_payload.get("extra"))),
    }
    return _redacted_mapping(payload)


def _execution_provenance(
    run: HarnessRun,
    raw_response_payload: Mapping[str, Any],
) -> dict[str, Any]:
    raw = _mapping(raw_response_payload.get("raw"))
    workspace_execution = _mapping(run.metadata.get("workspace_execution"))
    managed_mcp_snapshot = _mapping(raw.get("managed_mcp_snapshot")) or _mapping(
        run.metadata.get("managed_mcp_snapshot")
    )
    payload = {
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "error": run.error,
        "command": list(run.command),
        "env": _mapping(raw.get("env")),
        "workspace_execution": workspace_execution or None,
        "managed_mcp_snapshot": managed_mcp_snapshot or None,
        "native_session_id": run.native_session_id,
        "native": _native_execution(run),
        "raw_response_ok": raw_response_payload.get("ok"),
    }
    return _redacted_mapping(payload)


def _record_provenance(
    *,
    raw_requests: tuple[HarnessRawRecord, ...],
    raw_responses: tuple[HarnessRawRecord, ...],
    events: tuple[HarnessStoredEvent, ...],
) -> dict[str, Any]:
    return {
        "raw_request_ids": [record.id for record in raw_requests],
        "raw_response_ids": [record.id for record in raw_responses],
        "event_ids": [event.id for event in events],
        "event_count": len(events),
        "raw_requests": [raw_record_to_dict(record) for record in raw_requests],
        "raw_responses": [raw_record_to_dict(record) for record in raw_responses],
        "events": [event_to_dict(event) for event in events],
    }


def _project_provenance(
    run: HarnessRun,
    *,
    session: HarnessSession | None,
    data_dir: str | Path | None,
) -> dict[str, Any]:
    if run.workspace is not None:
        try:
            project = resolve_project(
                run.workspace,
                data_dir=data_dir or "~/.gpt2giga/harness",
                load_config_name=False,
            )
            return project_to_dict(project)
        except ValueError:
            pass
    session_metadata = _mapping(session.metadata if session is not None else None)
    return {
        "id": session_metadata.get("project_id"),
        "root": session_metadata.get("project_root") or run.workspace,
        "name": session_metadata.get("project_name"),
        "git_root": None,
        "git_branch": None,
        "is_git_repo": False,
        "dirty_summary": {},
        "config_path": None,
        "state_dir": None,
    }


def _git_provenance(workspace: str | None) -> dict[str, Any]:
    path = Path(workspace).expanduser().resolve() if workspace else None
    if path is None or not path.exists():
        return {"commit": None, "is_dirty": None}
    commit = _git_output(("rev-parse", "HEAD"), cwd=path)
    status = _git_output(("status", "--porcelain=v1"), cwd=path)
    return {
        "commit": commit,
        "is_dirty": bool(status) if status is not None else None,
    }


def _harness_provenance(
    run: HarnessRun,
    spec: HarnessSpec | None,
) -> dict[str, Any]:
    if spec is None:
        return {
            "id": run.harness_id,
            "title": run.harness_id,
            "kind": None,
            "capabilities": [run.capability.value],
            "version": None,
        }
    payload = spec_to_dict(spec)
    payload["version"] = None
    return payload


def _native_execution(run: HarnessRun) -> dict[str, Any] | None:
    metadata = _mapping(run.metadata)
    native_process = _mapping(metadata.get("native_process"))
    native_action = _optional_text(metadata.get("native_action"))
    native_home = _optional_text(metadata.get("native_home"))
    if not native_process and native_action is None and native_home is None:
        return None
    return {
        "action": native_action,
        "session_id": _optional_text(metadata.get("native_session_id"))
        or run.native_session_id,
        "process": native_process or None,
        "home": native_home,
    }


def _attachment_ids(
    run: HarnessRun,
    raw_request_payload: Mapping[str, Any],
) -> list[str]:
    metadata = _mapping(run.metadata)
    ids = raw_request_payload.get("attachment_ids") or metadata.get("attachment_ids")
    if not isinstance(ids, list):
        return []
    return [str(item) for item in ids if _optional_text(item)]


def _attachment_summaries(
    run: HarnessRun,
    raw_request_payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    metadata = _mapping(run.metadata)
    raw_attachments = raw_request_payload.get("attachments") or metadata.get(
        "attachments"
    )
    if not isinstance(raw_attachments, list):
        return []
    summaries: list[dict[str, Any]] = []
    for item in raw_attachments:
        attachment = _mapping(item)
        if not attachment:
            continue
        summaries.append(
            {
                "id": attachment.get("id"),
                "kind": attachment.get("kind"),
                "filename": attachment.get("filename"),
                "mime_type": attachment.get("mime_type"),
                "size_bytes": attachment.get("size_bytes"),
                "sha256": attachment.get("sha256"),
                "workspace_path": attachment.get("workspace_path"),
                "source": attachment.get("source"),
            }
        )
    return summaries


def _workspace_policy(
    run: HarnessRun,
    raw_request_payload: Mapping[str, Any],
) -> str | None:
    value = _optional_text(raw_request_payload.get("workspace_policy"))
    if value is not None:
        return value
    execution = _mapping(run.metadata.get("workspace_execution"))
    return _optional_text(execution.get("policy"))


def _safe_extra(extra: Mapping[str, Any]) -> dict[str, Any]:
    blocked = {
        "attachments",
        "attachment_render_plan",
        "project_memory",
        "workspace_execution",
    }
    return _redacted_mapping(
        {str(key): value for key, value in extra.items() if str(key) not in blocked}
    )


def _records_for_run(
    records: tuple[HarnessRawRecord, ...],
    run_id: str,
) -> tuple[HarnessRawRecord, ...]:
    return tuple(record for record in records if record.run_id == run_id)


def _redacted_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    redacted = redact_for_storage(dict(value))
    return dict(redacted) if isinstance(redacted, Mapping) else {}


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _git_output(args: tuple[str, ...], *, cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            ("git", *args),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None
