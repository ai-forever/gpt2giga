"""PR-ready artifact helpers for harness runs."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from gpt2giga_harness.sessions.models import HarnessRun
from gpt2giga_harness.types import redact_secrets
from gpt2giga_harness.worktrees import apply_run_diff, run_diff_response

MAX_SUMMARY_CHARS = 1200
MAX_TEST_OUTPUT_CHARS = 4000


@dataclass(frozen=True)
class RunPrArtifact:
    """Local PR artifact generated from one stored harness run."""

    run_id: str
    session_id: str
    title: str
    body: str
    patch: str
    changed_files: tuple[str, ...]
    untracked_files: tuple[str, ...]
    test_output: str | None
    branch_name_suggestion: str
    applied_branch: str | None = None


def build_pr_artifact(
    run: HarnessRun,
    *,
    result_text: str | None = None,
    result_raw: Mapping[str, Any] | None = None,
) -> RunPrArtifact:
    """Build a deterministic PR artifact from run metadata."""
    previous = _mapping(run.metadata.get("pr_artifact"))
    diff = run_diff_response(run.metadata)
    workspace_execution = _mapping(run.metadata.get("workspace_execution"))
    patch = _text(diff.get("patch")) or ""
    changed_files = tuple(str(item) for item in diff.get("changed_files", ()))
    untracked_files = tuple(str(item) for item in diff.get("untracked_files", ()))
    title = (
        _text(previous.get("title"))
        or _text(run.metadata.get("pr_title_suggestion"))
        or _suggest_title(run, changed_files, untracked_files)
    )
    branch_name = _text(previous.get("branch_name_suggestion")) or _suggest_branch_name(
        title, run.id
    )
    test_output = _bounded_optional(
        _text(previous.get("test_output")), MAX_TEST_OUTPUT_CHARS
    ) or _extract_test_output(run.metadata, result_raw)
    body = _text(previous.get("body"))
    if result_text is not None or result_raw is not None or not body:
        body = _build_body(
            run=run,
            result_text=result_text,
            changed_files=changed_files,
            untracked_files=untracked_files,
            test_output=test_output,
        )
    return RunPrArtifact(
        run_id=run.id,
        session_id=run.session_id,
        title=title,
        body=body,
        patch=patch,
        changed_files=changed_files,
        untracked_files=untracked_files,
        test_output=test_output,
        branch_name_suggestion=branch_name,
        applied_branch=_text(workspace_execution.get("applied_branch")),
    )


def pr_artifact_to_dict(artifact: RunPrArtifact) -> dict[str, Any]:
    """Serialize a PR artifact for metadata, API, and CLI output."""
    return {
        "run_id": artifact.run_id,
        "session_id": artifact.session_id,
        "title": artifact.title,
        "body": artifact.body,
        "patch": artifact.patch,
        "changed_files": list(artifact.changed_files),
        "untracked_files": list(artifact.untracked_files),
        "test_output": artifact.test_output,
        "branch_name_suggestion": artifact.branch_name_suggestion,
        "applied_branch": artifact.applied_branch,
    }


def create_pr_branch(
    run: HarnessRun,
    *,
    branch_name: str | None = None,
) -> dict[str, Any]:
    """Create a local branch from a worktree-backed run and apply its patch."""
    artifact = build_pr_artifact(run)
    clean_branch_name = _text(branch_name) or artifact.branch_name_suggestion
    workspace_execution = apply_run_diff(
        run.metadata,
        branch_name=clean_branch_name,
    )
    return {
        "branch_name": clean_branch_name,
        "workspace_execution": workspace_execution,
    }


def _build_body(
    *,
    run: HarnessRun,
    result_text: str | None,
    changed_files: tuple[str, ...],
    untracked_files: tuple[str, ...],
    test_output: str | None,
) -> str:
    summary = _result_summary(result_text)
    changes = _change_lines(changed_files, untracked_files)
    tests = test_output.strip() if test_output else "Not recorded."
    return "\n".join(
        (
            "## Summary",
            f"- {summary}",
            "",
            "## Changes",
            changes,
            "",
            "## Tests",
            f"```text\n{tests}\n```",
            "",
            "## Run",
            f"- Harness: `{run.harness_id}`",
            f"- Model: `{run.model or 'default'}`",
            f"- API mode: `{run.api_mode.value}`",
            f"- Run id: `{run.id}`",
        )
    )


def _result_summary(result_text: str | None) -> str:
    text = _bounded_optional(result_text, MAX_SUMMARY_CHARS)
    if text:
        first = " ".join(text.strip().split())
        return str(redact_secrets(first))
    return "Generated from the stored harness run."


def _change_lines(
    changed_files: tuple[str, ...],
    untracked_files: tuple[str, ...],
) -> str:
    rows: list[str] = []
    for path in changed_files:
        rows.append(f"- Updated `{path}`")
    for path in untracked_files:
        rows.append(f"- Added `{path}`")
    return "\n".join(rows) if rows else "- No patch was captured."


def _suggest_title(
    run: HarnessRun,
    changed_files: tuple[str, ...],
    untracked_files: tuple[str, ...],
) -> str:
    files = (*changed_files, *untracked_files)
    if len(files) == 1:
        return f"Update {files[0]}"
    if len(files) > 1:
        first = files[0]
        return f"Update {first} and related files"
    prompt = " ".join(run.prompt.strip().split())
    if prompt:
        prompt = str(redact_secrets(prompt))
        return _sentence_title(prompt)
    return f"Update from harness run {run.id}"


def _sentence_title(text: str) -> str:
    first = re.split(r"[.!?\n]", text, maxsplit=1)[0].strip()
    first = first[:72].strip()
    if not first:
        return "Update from harness run"
    return first[:1].upper() + first[1:]


def _suggest_branch_name(title: str, run_id: str) -> str:
    slug = re.sub(r"[^a-z0-9._/-]+", "-", title.lower()).strip("-./")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        slug = run_id.lower().replace("_", "-")
    return f"giga/{slug[:48].strip('-./') or run_id}"


def _extract_test_output(
    metadata: Mapping[str, Any],
    result_raw: Mapping[str, Any] | None,
) -> str | None:
    candidates: list[Any] = []
    workspace_execution = _mapping(metadata.get("workspace_execution"))
    candidates.extend(
        (
            metadata.get("test_output"),
            metadata.get("test_command_output"),
            workspace_execution.get("test_output"),
            workspace_execution.get("test_command_output"),
        )
    )
    if result_raw:
        candidates.extend(
            (
                result_raw.get("test_output"),
                result_raw.get("test_command_output"),
                _stdout_if_test_like(result_raw.get("stdout")),
                _stdout_if_test_like(result_raw.get("stderr")),
            )
        )
    for candidate in candidates:
        text = _bounded_optional(_text(candidate), MAX_TEST_OUTPUT_CHARS)
        if text:
            return text
    return None


def _stdout_if_test_like(value: Any) -> str | None:
    text = _text(value)
    if text is None:
        return None
    lowered = text.lower()
    markers = ("pytest", "passed", "failed", "error", "coverage")
    if any(marker in lowered for marker in markers):
        return text
    return None


def _bounded_optional(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    text = str(redact_secrets(value)).strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[-limit:]


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
