"""Versioned project workflow catalog and YAML-preserving builder helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any, Mapping

import yaml

from gpt2giga_harness.sessions.locking import exclusive_file_lock
from gpt2giga_harness.workflows import (
    WORKFLOW_DIRECTORY,
    WorkflowDefinition,
    load_workflow,
    parse_workflow_definition,
    workflow_definition_to_dict,
    workflow_plan,
)

WORKFLOW_HISTORY_DIRECTORY = WORKFLOW_DIRECTORY / ".history"
WORKFLOW_TEMPLATE_IDS = (
    "plan-implement-test-review",
    "diagnose-fix-regression",
    "issue-patch-pr-draft",
)


@dataclass(frozen=True)
class WorkflowRevision:
    """One immutable source revision from the transparent history directory."""

    source_hash: str
    created_at: str
    path: str
    content: str


def workflow_source(project_root: str | Path, workflow_id: str) -> str:
    """Read the exact YAML source for one validated workflow."""
    definition = load_workflow(project_root, workflow_id)
    return _workflow_path(project_root, definition.id).read_text(encoding="utf-8")


def workflow_history(
    project_root: str | Path, workflow_id: str
) -> tuple[WorkflowRevision, ...]:
    """List archived source revisions newest first."""
    definition = load_workflow(project_root, workflow_id)
    root = Path(project_root).resolve()
    directory = root / WORKFLOW_HISTORY_DIRECTORY / definition.id
    revisions: list[WorkflowRevision] = []
    for path in sorted(directory.glob("*.yaml"), reverse=True):
        content = path.read_text(encoding="utf-8")
        parts = path.stem.rsplit("-", 1)
        created = parts[0].replace("T", " ").replace("Z", "+00:00")
        revisions.append(
            WorkflowRevision(
                source_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                created_at=created,
                path=path.relative_to(root).as_posix(),
                content=content,
            )
        )
    return tuple(revisions)


def save_workflow(
    project_root: str | Path,
    content: str,
    *,
    expected_hash: str | None = None,
    expected_id: str | None = None,
    form: Mapping[str, Any] | None = None,
) -> WorkflowDefinition:
    """Validate and atomically save YAML, archiving the previous revision.

    When a typed form is supplied, known fields are merged into the original
    YAML mapping. Unknown top-level and per-step fields are retained verbatim in
    the saved document for forward-compatible editing.
    """
    root = Path(project_root).resolve()
    if form is not None:
        content = merge_workflow_form(content, form)
    definition = parse_workflow_definition(content, allow_unknown=True)
    if expected_id is not None and definition.id != expected_id:
        raise ValueError("Workflow id cannot be renamed in place")
    path = _workflow_path(root, definition.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = root / WORKFLOW_DIRECTORY / ".catalog"
    with exclusive_file_lock(lock):
        previous = path.read_text(encoding="utf-8") if path.exists() else None
        if previous is not None and expected_hash is not None:
            actual = hashlib.sha256(previous.encode("utf-8")).hexdigest()
            if actual != expected_hash:
                raise ValueError("Workflow changed since it was loaded")
        if previous is not None and previous != content:
            _archive_revision(root, definition.id, previous)
        _atomic_write(path, content)
    return load_workflow(root, definition.id)


def duplicate_workflow(
    project_root: str | Path, workflow_id: str, new_id: str
) -> WorkflowDefinition:
    """Create a validated copy with a new identity and independent history."""
    source = workflow_source(project_root, workflow_id)
    data = _yaml_mapping(source)
    data["id"] = new_id
    data["title"] = f"{data.get('title') or workflow_id} Copy"
    data["version"] = "1.0.0"
    content = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    path = _workflow_path(project_root, new_id)
    if path.exists():
        raise ValueError("Workflow already exists")
    return save_workflow(project_root, content)


def delete_workflow(project_root: str | Path, workflow_id: str) -> None:
    """Delete the current editable definition while retaining history."""
    content = workflow_source(project_root, workflow_id)
    root = Path(project_root).resolve()
    path = _workflow_path(root, workflow_id)
    lock = root / WORKFLOW_DIRECTORY / ".catalog"
    with exclusive_file_lock(lock):
        _archive_revision(root, workflow_id, content)
        path.unlink()


def merge_workflow_form(content: str, form: Mapping[str, Any]) -> str:
    """Merge typed builder fields while preserving unknown YAML fields."""
    current = _yaml_mapping(content)
    known_top = {
        "id",
        "title",
        "description",
        "schema_version",
        "version",
        "inputs",
        "budgets",
        "steps",
    }
    for key in known_top - {"steps"}:
        if key in form:
            current[key] = form[key]
    if "steps" in form:
        incoming = form["steps"]
        if not isinstance(incoming, list):
            raise ValueError("Workflow steps must be a list")
        existing = {
            str(item.get("id")): dict(item)
            for item in current.get("steps", [])
            if isinstance(item, Mapping) and item.get("id")
        }
        merged: list[dict[str, Any]] = []
        for item in incoming:
            if not isinstance(item, Mapping):
                raise ValueError("Workflow steps must be mappings")
            step = existing.get(str(item.get("id")), {})
            step.update(dict(item))
            merged.append(step)
        current["steps"] = merged
    rendered = yaml.safe_dump(current, sort_keys=False, allow_unicode=True)
    # Validate only the execution fields. Unknown future fields remain in YAML.
    parse_workflow_definition(
        yaml.safe_dump(_execution_mapping(current), sort_keys=False)
    )
    return rendered


def workflow_catalog_detail(
    project_root: str | Path, workflow_id: str
) -> dict[str, Any]:
    """Return source, typed definition, DAG, and immutable revision metadata."""
    definition = load_workflow(project_root, workflow_id)
    source = workflow_source(project_root, workflow_id)
    runsafe = workflow_definition_to_dict(definition)
    return {
        "workflow": runsafe,
        "source": source,
        "plan": workflow_plan(definition),
        "history": [
            {
                "source_hash": item.source_hash,
                "created_at": item.created_at,
                "path": item.path,
            }
            for item in workflow_history(project_root, workflow_id)
        ],
    }


def workflow_templates() -> tuple[dict[str, Any], ...]:
    """Return the built-in authoring templates as validated catalog entries."""
    return tuple(
        {
            "id": template_id,
            "title": parse_workflow_definition(content).title,
            "description": parse_workflow_definition(content).description,
            "content": content,
            "plan": workflow_plan(parse_workflow_definition(content)),
        }
        for template_id, content in _template_sources().items()
    )


def template_source(template_id: str) -> str:
    """Return one built-in template source."""
    try:
        return _template_sources()[template_id]
    except KeyError as exc:
        raise KeyError(template_id) from exc


def _template_sources() -> dict[str, str]:
    def render(
        workflow_id: str, title: str, description: str, steps: list[dict[str, Any]]
    ) -> str:
        return yaml.safe_dump(
            {
                "id": workflow_id,
                "title": title,
                "description": description,
                "schema_version": 1,
                "version": "1.0.0",
                "inputs": {"prompt": "Describe the project task."},
                "budgets": {"max_concurrency": 1, "max_steps": len(steps)},
                "steps": steps,
            },
            sort_keys=False,
            allow_unicode=True,
        )

    return {
        "plan-implement-test-review": render(
            "plan-implement-test-review",
            "Plan, Implement, Test, Review",
            "A safe edit workflow with explicit verification and review handoffs.",
            [
                {
                    "id": "plan",
                    "kind": "agent",
                    "agent_id": "planner",
                    "prompt": "Plan: ${prompt}",
                },
                {
                    "id": "implement",
                    "kind": "agent",
                    "agent_id": "implementer",
                    "depends_on": ["plan"],
                    "prompt": "Implement: ${prompt}",
                },
                {
                    "id": "test",
                    "kind": "agent",
                    "agent_id": "test-runner",
                    "depends_on": ["implement"],
                    "prompt": "Test: ${prompt}",
                },
                {
                    "id": "review",
                    "kind": "agent",
                    "agent_id": "reviewer",
                    "depends_on": ["test"],
                    "prompt": "Review: ${prompt}",
                },
            ],
        ),
        "diagnose-fix-regression": render(
            "diagnose-fix-regression",
            "Diagnose, Fix, Regression",
            "Diagnose a failure, make an isolated fix, then verify regression coverage.",
            [
                {
                    "id": "diagnose",
                    "kind": "agent",
                    "agent_id": "reviewer",
                    "prompt": "Diagnose: ${prompt}",
                },
                {
                    "id": "fix",
                    "kind": "agent",
                    "agent_id": "implementer",
                    "depends_on": ["diagnose"],
                    "prompt": "Fix: ${prompt}",
                },
                {
                    "id": "regression",
                    "kind": "agent",
                    "agent_id": "test-runner",
                    "depends_on": ["fix"],
                    "prompt": "Verify regression: ${prompt}",
                },
            ],
        ),
        "issue-patch-pr-draft": render(
            "issue-patch-pr-draft",
            "Issue, Patch, PR Draft",
            "Turn issue context into an isolated patch and reviewed PR draft.",
            [
                {
                    "id": "issue",
                    "kind": "agent",
                    "agent_id": "planner",
                    "prompt": "Analyze issue: ${prompt}",
                },
                {
                    "id": "patch",
                    "kind": "agent",
                    "agent_id": "implementer",
                    "depends_on": ["issue"],
                    "prompt": "Create patch: ${prompt}",
                },
                {
                    "id": "pr",
                    "kind": "agent",
                    "agent_id": "reviewer",
                    "depends_on": ["patch"],
                    "artifact_types": ["patch", "diff"],
                    "prompt": "Draft PR: ${prompt}",
                },
            ],
        ),
    }


def _execution_mapping(data: Mapping[str, Any]) -> dict[str, Any]:
    top = {
        "id",
        "title",
        "description",
        "schema_version",
        "version",
        "inputs",
        "budgets",
        "steps",
    }
    step_keys = {
        "id",
        "kind",
        "title",
        "depends_on",
        "condition",
        "agent_id",
        "prompt",
        "eval_id",
        "harness_ids",
        "action",
        "transform",
        "select",
        "artifact_types",
        "retries",
        "timeout_seconds",
        "max_fan_out",
        "inputs",
        "output",
    }
    result = {key: value for key, value in data.items() if key in top}
    if isinstance(result.get("steps"), list):
        result["steps"] = [
            {key: value for key, value in item.items() if key in step_keys}
            if isinstance(item, Mapping)
            else item
            for item in result["steps"]
        ]
    return result


def _yaml_mapping(content: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ValueError("Invalid workflow YAML") from exc
    if not isinstance(value, Mapping):
        raise ValueError("Workflow must be a YAML mapping")
    return dict(value)


def _workflow_path(project_root: str | Path, workflow_id: str) -> Path:
    root = Path(project_root).resolve()
    # Reuse the canonical validator before deriving a filesystem path.
    definition = parse_workflow_definition(
        f"id: {workflow_id}\ntitle: Temporary\nversion: '1'\nsteps:\n  - id: value\n    kind: transform\n    transform: identity\n"
    )
    return root / WORKFLOW_DIRECTORY / f"{definition.id}.yaml"


def _archive_revision(root: Path, workflow_id: str, content: str) -> None:
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    path = (
        root / WORKFLOW_HISTORY_DIRECTORY / workflow_id / f"{stamp}-{digest[:12]}.yaml"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if not any(path.parent.glob(f"*-{digest[:12]}.yaml")):
        _atomic_write(path, content)


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
