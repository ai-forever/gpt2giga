"""Review-gated promotion of completed runs into reusable project YAML."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping

import yaml

from gpt2giga.harness.agents import AGENT_DIRECTORY, parse_agent_profile
from gpt2giga.harness.authoring import ProjectAuthoringService, ProjectFileDraft
from gpt2giga.harness.evals import EVALS_RELATIVE_DIR, eval_spec_from_mapping
from gpt2giga.harness.sessions.models import HarnessRun
from gpt2giga.harness.sessions.redaction import redact_for_storage
from gpt2giga.harness.sessions.store import HarnessSessionStore
from gpt2giga.harness.workflows import WORKFLOW_DIRECTORY, parse_workflow_definition

PROMOTION_KINDS = frozenset({"agent", "workflow", "eval"})
SAFE_ID = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
ONE_OFF_ID = re.compile(r"\b(?:run|sess|job|attempt|trace|span)_[A-Za-z0-9_-]+\b")
MAX_PROMPT_CHARS = 8_000


@dataclass(frozen=True)
class RunPromotionDraft:
    """One validated candidate that must be reviewed before apply."""

    kind: str
    target_id: str
    project_root: str
    content: str
    source_hash: str
    redacted_diff: str
    relative_path: str
    review_token: str
    parameters: Mapping[str, Any]
    provenance: Mapping[str, Any]
    warnings: tuple[str, ...]


def preview_run_promotion(
    store: HarnessSessionStore, run_id: str, *, kind: str, target_id: str
) -> RunPromotionDraft:
    """Build a secret-free candidate and validated project-file diff."""
    _validate_target(kind, target_id)
    run = store.get_run(run_id)
    if not run.workspace:
        raise ValueError("Run has no project workspace")
    root = Path(run.workspace).expanduser().resolve()
    prompt = _portable_text(run.prompt, root, run)
    if not prompt:
        raise ValueError("Run prompt is empty after redaction")
    parameters = {
        "prompt": prompt,
        "selected_files": list(_selected_files(run.metadata)),
        "tool_ids": list(_tool_ids(run.metadata)),
        "permission_profile": _permission_profile(run.metadata),
        "artifact_types": list(_artifact_types(run.metadata)),
    }
    provenance = {
        "source_run_id": run.id,
        "source_session_id": run.session_id,
        "source_trace_id": _optional_text(run.metadata.get("trace_id")),
        "source_harness_id": run.harness_id,
        "generated_by": "gpt2giga.run_promotion.v1",
    }
    content, relative = _candidate(run, kind, target_id, parameters, provenance)
    draft = _project_draft(root, kind, target_id, content)
    return RunPromotionDraft(
        kind=kind,
        target_id=target_id,
        project_root=str(root),
        content=content,
        source_hash=draft.source_hash,
        redacted_diff=draft.redacted_diff,
        relative_path=relative.as_posix(),
        review_token=_review_token(kind, target_id, content),
        parameters=parameters,
        provenance=dict(redact_for_storage(provenance)),
        warnings=(
            "Review the YAML before applying it to the project.",
            "Absolute paths, one-off ids, secret-looking values, and raw tool results were omitted from reusable parameters.",
            "Skill or plugin export remains a separate explicit future action.",
        ),
    )


def apply_run_promotion(
    store: HarnessSessionStore,
    run_id: str,
    *,
    kind: str,
    target_id: str,
    content: str,
    source_hash: str,
    review_token: str,
) -> tuple[str, ProjectFileDraft[Any]]:
    """Apply only content carrying a matching review token and source ETag."""
    _validate_target(kind, target_id)
    if not review_token or review_token != _review_token(kind, target_id, content):
        raise ValueError("Promotion content must be reviewed again before apply")
    run = store.get_run(run_id)
    if not run.workspace:
        raise ValueError("Run has no project workspace")
    root = Path(run.workspace).expanduser().resolve()
    draft = _project_draft(root, kind, target_id, content, source_hash=source_hash)
    return ProjectAuthoringService(root).apply(draft), draft


def promotion_to_dict(draft: RunPromotionDraft) -> dict[str, Any]:
    """Serialize a promotion review."""
    return {
        "kind": draft.kind,
        "target_id": draft.target_id,
        "project_root": draft.project_root,
        "content": draft.content,
        "source_hash": draft.source_hash,
        "redacted_diff": draft.redacted_diff,
        "relative_path": draft.relative_path,
        "review_token": draft.review_token,
        "parameters": dict(draft.parameters),
        "provenance": dict(draft.provenance),
        "warnings": list(draft.warnings),
    }


def _candidate(
    run: HarnessRun,
    kind: str,
    target_id: str,
    parameters: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> tuple[str, Path]:
    source = {key: value for key, value in provenance.items() if value}
    prompt = str(parameters["prompt"])
    if kind == "agent":
        payload = {
            "id": target_id,
            "title": _title(target_id),
            "description": "Reusable agent promoted from a reviewed run.",
            "schema_version": 1,
            "harness_id": run.harness_id,
            "instructions": prompt,
            "model": run.model,
            "api_mode": run.api_mode.value,
            "invocation_mode": run.invocation_mode.value,
            "mode": run.mode,
            "workspace_policy": "worktree" if run.mode == "edit" else "auto",
            "permission_profile": parameters["permission_profile"],
            "context_selectors": parameters["selected_files"],
            "tool_ids": parameters["tool_ids"],
            "budgets": {"max_attempts": 1, "max_concurrency": 1},
            "expected_artifact": next(iter(parameters["artifact_types"]), None),
            "provenance": source,
        }
        relative = AGENT_DIRECTORY / f"{target_id}.yaml"
    elif kind == "workflow":
        payload = {
            "id": target_id,
            "title": _title(target_id),
            "description": "Workflow promoted from a reviewed run.",
            "schema_version": 1,
            "version": "1.0.0",
            "inputs": {
                "prompt": prompt,
                "selected_files": parameters["selected_files"],
            },
            "budgets": {"max_concurrency": 1, "max_steps": 1},
            "steps": [
                {
                    "id": "execute",
                    "kind": "agent",
                    "agent_id": _agent_id(run.metadata),
                    "prompt": "${prompt}",
                    "artifact_types": parameters["artifact_types"],
                }
            ],
            "provenance": source,
        }
        relative = WORKFLOW_DIRECTORY / f"{target_id}.yaml"
    else:
        payload = {
            "name": target_id,
            "description": "Eval trace promoted from a reviewed run.",
            "harnesses": [run.harness_id],
            "model": run.model,
            "api_mode": run.api_mode.value,
            "mode": run.mode,
            "workspace_policy": "current",
            "cases": [{"id": "source-trace", "prompt": prompt, "checks": []}],
            "metadata": {
                "provenance": source,
                "selected_files": parameters["selected_files"],
            },
        }
        relative = EVALS_RELATIVE_DIR / f"{target_id}.yaml"
    return (
        yaml.safe_dump(_drop_none(payload), sort_keys=False, allow_unicode=True),
        relative,
    )


def _project_draft(
    root: Path,
    kind: str,
    target_id: str,
    content: str,
    *,
    source_hash: str | None = None,
) -> ProjectFileDraft[Any]:
    relative = {
        "agent": AGENT_DIRECTORY,
        "workflow": WORKFLOW_DIRECTORY,
        "eval": EVALS_RELATIVE_DIR,
    }[kind] / f"{target_id}.yaml"

    def validate(value: str) -> Any:
        if kind == "agent":
            parsed = parse_agent_profile(value, source_path=relative.as_posix())
            if parsed.id != target_id:
                raise ValueError("Agent filename must match its id")
            return parsed
        if kind == "workflow":
            parsed = parse_workflow_definition(
                value, source_path=relative.as_posix(), allow_unknown=True
            )
            if parsed.id != target_id:
                raise ValueError("Workflow filename must match its id")
            return parsed
        data = yaml.safe_load(value)
        if not isinstance(data, Mapping):
            raise ValueError("Eval YAML must be a mapping")
        parsed = eval_spec_from_mapping(data, path=relative)
        if parsed.name != target_id:
            raise ValueError("Eval filename must match its name")
        return parsed

    return ProjectAuthoringService(root).draft(
        relative, content, validate=validate, expected_hash=source_hash
    )


def _portable_text(value: str, root: Path, run: HarnessRun) -> str:
    text = str(redact_for_storage(value)).strip()[:MAX_PROMPT_CHARS]
    text = text.replace(str(root), "${workspace}")
    for item in (run.id, run.session_id):
        text = text.replace(item, "<source-id>")
    return ONE_OFF_ID.sub("<source-id>", text).strip()


def _selected_files(metadata: Mapping[str, Any]) -> tuple[str, ...]:
    candidates: list[Any] = []
    execution = metadata.get("workspace_execution")
    if isinstance(execution, Mapping):
        candidates.extend(execution.get("changed_files") or ())
    candidates.extend(metadata.get("selected_files") or ())
    for item in metadata.get("attachments") or ():
        if isinstance(item, Mapping):
            candidates.append(item.get("workspace_path"))
    selected: list[str] = []
    for value in candidates:
        text = str(value or "").strip()
        path = PurePosixPath(text)
        if (
            text
            and not path.is_absolute()
            and ".." not in path.parts
            and text not in selected
        ):
            selected.append(text)
    return tuple(selected[:32])


def _tool_ids(metadata: Mapping[str, Any]) -> tuple[str, ...]:
    snapshot = metadata.get("agent_profile_snapshot")
    source = snapshot if isinstance(snapshot, Mapping) else metadata
    values = source.get("tool_ids") if isinstance(source, Mapping) else ()
    return tuple(
        dict.fromkeys(str(item).strip() for item in values or () if str(item).strip())
    )[:32]


def _artifact_types(metadata: Mapping[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    if metadata.get("workspace_execution"):
        values.append("patch")
    if metadata.get("pr_artifact"):
        values.append("pr_draft")
    if metadata.get("test_report"):
        values.append("test_report")
    return tuple(values)


def _permission_profile(metadata: Mapping[str, Any]) -> str:
    snapshot = metadata.get("agent_profile_snapshot")
    if isinstance(snapshot, Mapping) and snapshot.get("permission_profile"):
        return str(snapshot["permission_profile"])
    return str(metadata.get("permission_profile") or "interactive")


def _agent_id(metadata: Mapping[str, Any]) -> str:
    value = str(metadata.get("agent_id") or "implementer")
    return value if SAFE_ID.fullmatch(value) else "implementer"


def _validate_target(kind: str, target_id: str) -> None:
    if kind not in PROMOTION_KINDS:
        raise ValueError("Promotion kind must be agent, workflow, or eval")
    if not SAFE_ID.fullmatch(target_id):
        raise ValueError("Promotion id must match ^[a-z][a-z0-9_-]{1,63}$")


def _review_token(kind: str, target_id: str, content: str) -> str:
    return hashlib.sha256(f"{kind}\0{target_id}\0{content}".encode()).hexdigest()


def _title(value: str) -> str:
    return " ".join(part.capitalize() for part in value.replace("_", "-").split("-"))


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _drop_none(item) for key, item in value.items() if item is not None
        }
    if isinstance(value, list):
        return [_drop_none(item) for item in value]
    return value


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
