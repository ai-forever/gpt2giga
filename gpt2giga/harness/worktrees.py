"""Git worktree helpers for isolated edit-mode harness runs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Mapping

from gpt2giga.harness.sessions.store import utc_now

MAX_PATCH_CHARS = 200_000


class WorkspacePolicy(str, Enum):
    """Workspace execution policies understood by the harness runner."""

    AUTO = "auto"
    CURRENT = "current"
    WORKTREE = "worktree"
    TEMP_COPY = "temp_copy"


class WorktreeError(ValueError):
    """Raised when worktree metadata cannot be used."""


class WorktreeConflictError(WorktreeError):
    """Raised when applying a patch would be unsafe."""


@dataclass(frozen=True)
class WorkspaceExecution:
    """Prepared workspace execution context for one run."""

    requested_policy: WorkspacePolicy
    policy: WorkspacePolicy
    source_workspace: str | None
    source_git_root: str | None = None
    effective_workspace: str | None = None
    worktree_path: str | None = None
    base_branch: str | None = None
    base_commit: str | None = None
    fallback_reason: str | None = None

    @property
    def request_workspace(self) -> str | None:
        """Return the workspace path that should be passed to the harness."""
        return self.effective_workspace or self.source_workspace

    def to_metadata(self) -> dict[str, Any]:
        """Serialize the execution context for run metadata."""
        return {
            "requested_policy": self.requested_policy.value,
            "policy": self.policy.value,
            "source_workspace": self.source_workspace,
            "source_git_root": self.source_git_root,
            "effective_workspace": self.effective_workspace,
            "worktree_path": self.worktree_path,
            "base_branch": self.base_branch,
            "base_commit": self.base_commit,
            "fallback_reason": self.fallback_reason,
        }


@dataclass(frozen=True)
class WorkspaceDiff:
    """Captured diff metadata for one workspace."""

    patch: str
    changed_files: tuple[str, ...] = ()
    untracked_files: tuple[str, ...] = ()
    captured: bool = False
    truncated: bool = False
    error: str | None = None

    def to_metadata(self) -> dict[str, Any]:
        """Serialize diff metadata for a run."""
        return {
            "patch": self.patch,
            "changed_files": list(self.changed_files),
            "untracked_files": list(self.untracked_files),
            "captured": self.captured,
            "truncated": self.truncated,
            "error": self.error,
        }


def parse_workspace_policy(value: Any) -> WorkspacePolicy:
    """Parse a workspace policy from CLI/API payloads."""
    if isinstance(value, WorkspacePolicy):
        return value
    if value is None or not str(value).strip():
        return WorkspacePolicy.AUTO
    normalized = str(value).strip().lower().replace("-", "_")
    return WorkspacePolicy(normalized)


def prepare_workspace_execution(
    *,
    requested_policy: WorkspacePolicy | str | None,
    harness_kind: str,
    mode: str,
    workspace: str | None,
    data_dir: str | Path,
    session_id: str,
    run_id: str,
    dry_run: bool = False,
) -> WorkspaceExecution:
    """Prepare the effective workspace for one harness run."""
    parsed_policy = parse_workspace_policy(requested_policy)
    source_workspace = str(Path(workspace).expanduser()) if workspace else None
    if source_workspace is None or mode != "edit" or dry_run:
        return WorkspaceExecution(
            requested_policy=parsed_policy,
            policy=WorkspacePolicy.CURRENT,
            source_workspace=source_workspace,
        )

    should_use_worktree = parsed_policy == WorkspacePolicy.WORKTREE or (
        parsed_policy == WorkspacePolicy.AUTO and harness_kind == "agent-cli"
    )
    if parsed_policy == WorkspacePolicy.TEMP_COPY:
        raise WorktreeError(
            "temp_copy workspace isolation is not implemented; refusing to run "
            "in the current workspace."
        )
    if not should_use_worktree:
        return WorkspaceExecution(
            requested_policy=parsed_policy,
            policy=WorkspacePolicy.CURRENT,
            source_workspace=source_workspace,
        )

    git_root = _git_output(source_workspace, "rev-parse", "--show-toplevel")
    if git_root is None:
        raise WorktreeError(
            "Workspace isolation requires a Git repository; refusing to run in "
            "the current workspace."
        )
    base_commit = _git_output(git_root, "rev-parse", "HEAD")
    if base_commit is None:
        raise WorktreeError(
            "Workspace isolation requires a Git base commit; refusing to run in "
            "the current workspace."
        )
    base_branch = _git_output(git_root, "branch", "--show-current")
    worktree_path = _worktree_path(data_dir, session_id, run_id)
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    if worktree_path.exists():
        removed = _git_run(
            git_root,
            "worktree",
            "remove",
            "--force",
            str(worktree_path),
            timeout=30,
        )
        if removed.returncode != 0 and worktree_path.exists():
            shutil.rmtree(worktree_path)
            _git_run(git_root, "worktree", "prune", timeout=30)
    created = _git_run(
        git_root,
        "worktree",
        "add",
        "--detach",
        str(worktree_path),
        base_commit,
        timeout=30,
    )
    if created.returncode != 0:
        reason = _stderr(created) or "git worktree add failed"
        raise WorktreeError(
            f"Could not create an isolated Git worktree ({reason}); refusing to "
            "run in the current workspace."
        )
    return WorkspaceExecution(
        requested_policy=parsed_policy,
        policy=WorkspacePolicy.WORKTREE,
        source_workspace=source_workspace,
        source_git_root=git_root,
        effective_workspace=str(worktree_path),
        worktree_path=str(worktree_path),
        base_branch=base_branch,
        base_commit=base_commit,
    )


def capture_workspace_diff(execution: WorkspaceExecution) -> WorkspaceDiff | None:
    """Capture a git diff for the prepared workspace."""
    workspace = execution.request_workspace
    if workspace is None:
        return None
    git_root = _git_output(workspace, "rev-parse", "--show-toplevel")
    if git_root is None:
        return WorkspaceDiff(
            patch="No diff captured.",
            error="workspace is not inside a git repository",
        )
    status = _git_status(git_root)
    if status is None:
        return WorkspaceDiff(patch="No diff captured.", error="git status failed")
    untracked = tuple(path for code, path in status if code == "??")
    changed = tuple(path for code, path in status if code != "??")
    diff = _capture_git_diff(git_root, untracked)
    if diff.returncode != 0:
        return WorkspaceDiff(
            patch="No diff captured.",
            changed_files=changed,
            untracked_files=untracked,
            error=_stderr(diff) or "git diff failed",
        )
    patch, truncated = _bounded_text(diff.stdout)
    captured = bool(patch.strip())
    return WorkspaceDiff(
        patch=patch if captured else "No diff captured.",
        changed_files=changed,
        untracked_files=untracked,
        captured=captured,
        truncated=truncated,
    )


def run_diff_response(run_metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Return an API-friendly diff payload from stored run metadata."""
    execution = _workspace_execution_metadata(run_metadata)
    patch = str(execution.get("patch") or run_metadata.get("diff") or "")
    changed_files = _string_list(execution.get("changed_files"))
    untracked_files = _string_list(execution.get("untracked_files"))
    return {
        "workspace_execution": dict(execution),
        "patch": patch,
        "changed_files": changed_files,
        "untracked_files": untracked_files,
        "can_apply": _can_apply(execution, patch),
        "can_discard": _can_discard(execution),
    }


def apply_run_diff(
    run_metadata: Mapping[str, Any],
    *,
    branch_name: str | None = None,
) -> dict[str, Any]:
    """Apply one captured worktree patch back to its source git checkout."""
    execution = _workspace_execution_metadata(run_metadata)
    if execution.get("policy") != WorkspacePolicy.WORKTREE.value:
        raise WorktreeError("Run did not use an isolated worktree.")
    if execution.get("applied_at"):
        raise WorktreeError("Run diff has already been applied.")
    if execution.get("discarded_at"):
        raise WorktreeError("Run worktree has already been discarded.")
    if execution.get("truncated"):
        raise WorktreeError("Run patch is truncated and cannot be applied safely.")
    source_root = _required_metadata_text(execution, "source_git_root")
    base_commit = _required_metadata_text(execution, "base_commit")
    patch = _required_metadata_text(execution, "patch")
    if patch == "No diff captured.":
        raise WorktreeError("Run has no captured patch to apply.")
    current_head = _git_output(source_root, "rev-parse", "HEAD")
    if current_head != base_commit:
        raise WorktreeConflictError(
            "Target checkout is not at the run base commit; refusing to apply."
        )
    dirty = _git_run(source_root, "status", "--porcelain=v1", timeout=10)
    if dirty.returncode != 0:
        raise WorktreeError("Could not inspect target checkout status.")
    if dirty.stdout.strip():
        raise WorktreeConflictError(
            "Target checkout has local changes; refusing to apply."
        )
    clean_branch = _optional_branch_name(branch_name)
    check = _git_apply(source_root, patch, "--check")
    if check.returncode != 0:
        raise WorktreeConflictError(_stderr(check) or "git apply --check failed")
    if clean_branch:
        created = _git_run(
            source_root,
            "switch",
            "-c",
            clean_branch,
            base_commit,
            timeout=20,
        )
        if created.returncode != 0:
            raise WorktreeConflictError(_stderr(created) or "git switch failed")
    applied = _git_apply(source_root, patch)
    if applied.returncode != 0:
        raise WorktreeConflictError(_stderr(applied) or "git apply failed")
    updated = dict(execution)
    updated["applied_at"] = utc_now()
    if clean_branch:
        updated["applied_branch"] = clean_branch
    return updated


def discard_run_worktree(run_metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Remove an isolated worktree for one run."""
    execution = _workspace_execution_metadata(run_metadata)
    if execution.get("policy") != WorkspacePolicy.WORKTREE.value:
        raise WorktreeError("Run did not use an isolated worktree.")
    worktree_path = _required_metadata_text(execution, "worktree_path")
    source_root = _required_metadata_text(execution, "source_git_root")
    path = Path(worktree_path)
    if path.exists():
        removed = _git_run(
            source_root,
            "worktree",
            "remove",
            "--force",
            worktree_path,
            timeout=30,
        )
        if removed.returncode != 0 and path.exists():
            shutil.rmtree(path, ignore_errors=True)
            _git_run(source_root, "worktree", "prune", timeout=30)
    updated = dict(execution)
    updated["discarded_at"] = utc_now()
    updated["worktree_exists"] = path.exists()
    return updated


def detect_overlapping_run_diffs(
    run_metadatas: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Return conservative file-level conflicts across isolated run patches."""
    owners: dict[str, list[str]] = {}
    for run_id, metadata in run_metadatas.items():
        execution = _workspace_execution_metadata(metadata)
        for path in execution.get("changed_files", ()):
            owners.setdefault(str(path), []).append(str(run_id))
        for path in execution.get("untracked_files", ()):
            owners.setdefault(str(path), []).append(str(run_id))
    return tuple(
        {"path": path, "run_ids": sorted(set(run_ids))}
        for path, run_ids in sorted(owners.items())
        if len(set(run_ids)) > 1
    )


def prepare_run_diff_merge(
    run_metadatas: Mapping[str, Mapping[str, Any]],
    *,
    data_dir: str | Path,
    session_id: str,
    merge_id: str,
) -> dict[str, Any]:
    """Build a reviewable combined patch in a retained isolated worktree."""
    if not run_metadatas:
        raise WorktreeError("Merge queue has no selected run patches.")
    conflicts = detect_overlapping_run_diffs(run_metadatas)
    if conflicts:
        paths = ", ".join(item["path"] for item in conflicts)
        raise WorktreeConflictError(f"Selected patches overlap: {paths}")
    executions = {
        run_id: _workspace_execution_metadata(metadata)
        for run_id, metadata in run_metadatas.items()
    }
    source_roots = {
        _required_metadata_text(execution, "source_git_root")
        for execution in executions.values()
    }
    base_commits = {
        _required_metadata_text(execution, "base_commit")
        for execution in executions.values()
    }
    if len(source_roots) != 1 or len(base_commits) != 1:
        raise WorktreeConflictError(
            "Selected patches do not share one source checkout and base commit."
        )
    for execution in executions.values():
        if execution.get("policy") != WorkspacePolicy.WORKTREE.value:
            raise WorktreeError("Every merge candidate must use an isolated worktree.")
        if execution.get("truncated"):
            raise WorktreeError("A truncated patch cannot enter the merge queue.")
        if execution.get("discarded_at"):
            raise WorktreeError("A discarded worktree cannot enter the merge queue.")
        if not str(execution.get("patch") or "").strip():
            raise WorktreeError("Every merge candidate must contain a captured patch.")
    source_root = next(iter(source_roots))
    merged = prepare_workspace_execution(
        requested_policy=WorkspacePolicy.WORKTREE,
        harness_kind="agent-cli",
        mode="edit",
        workspace=source_root,
        data_dir=data_dir,
        session_id=session_id,
        run_id=merge_id,
    )
    merge_workspace = merged.request_workspace or ""
    for run_id in sorted(executions):
        patch = str(executions[run_id].get("patch") or "")
        checked = _git_apply(merge_workspace, patch, "--check")
        if checked.returncode != 0:
            raise WorktreeConflictError(
                f"Patch {run_id} does not apply cleanly in the merge queue: "
                f"{_stderr(checked) or 'git apply --check failed'}"
            )
        applied = _git_apply(merge_workspace, patch)
        if applied.returncode != 0:
            raise WorktreeConflictError(
                f"Patch {run_id} failed in the merge queue: "
                f"{_stderr(applied) or 'git apply failed'}"
            )
    diff = capture_workspace_diff(merged)
    if diff is None or not diff.captured:
        raise WorktreeError("Merge queue did not produce a combined patch.")
    return {
        **merged.to_metadata(),
        **diff.to_metadata(),
        "source_run_ids": sorted(executions),
        "prepared_at": utc_now(),
        "conflicts": [],
    }


def open_worktree_response(run_metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Return the local worktree path and a shell command to enter it."""
    execution = _workspace_execution_metadata(run_metadata)
    path = str(execution.get("worktree_path") or "")
    exists = bool(path and Path(path).exists())
    return {
        "workspace_execution": dict(execution),
        "path": path or None,
        "exists": exists,
        "command": f"cd {shlex_quote(path)}" if path else None,
    }


def shlex_quote(value: str) -> str:
    """Quote a string for display in a POSIX shell."""
    if value and all(char.isalnum() or char in "_./:=@-" for char in value):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


def _worktree_path(data_dir: str | Path, session_id: str, run_id: str) -> Path:
    return (
        Path(data_dir).expanduser()
        / "worktrees"
        / _safe_path_part(session_id)
        / _safe_path_part(run_id)
    )


def _safe_path_part(value: str) -> str:
    return "".join(char if char.isalnum() or char in "_-" else "_" for char in value)


def _workspace_execution_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    value = metadata.get("workspace_execution")
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _required_metadata_text(metadata: Mapping[str, Any], key: str) -> str:
    value = metadata.get(key)
    if value is None or not str(value).strip():
        raise WorktreeError(f"Run worktree metadata is missing {key}.")
    return str(value)


def _optional_branch_name(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    text = value.strip()
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/_-.")
    if any(char not in allowed for char in text) or text.startswith("-"):
        raise WorktreeError("branch_name contains unsupported characters.")
    return text


def _git_status(cwd: str) -> tuple[tuple[str, str], ...] | None:
    result = _git_run(cwd, "status", "--porcelain=v1", "--untracked-files=all")
    if result.returncode != 0:
        return None
    rows: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        rows.append((line[:2], line[3:]))
    return tuple(rows)


def _git_output(cwd: str, *args: str) -> str | None:
    result = _git_run(cwd, *args)
    if result.returncode != 0:
        return None
    text = result.stdout.strip()
    return text or None


def _git_run(
    cwd: str,
    *args: str,
    input_text: str | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float = 10,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ("git", "-C", cwd, *args),
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={**os.environ, **dict(env or {})},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(
            ("git", "-C", cwd, *args),
            returncode=1,
            stdout="",
            stderr=str(exc),
        )


def _git_apply(
    cwd: str,
    patch: str,
    *extra_args: str,
) -> subprocess.CompletedProcess[str]:
    return _git_run(
        cwd,
        "apply",
        "--binary",
        *extra_args,
        "-",
        input_text=patch,
        timeout=20,
    )


def _stderr(result: subprocess.CompletedProcess[str]) -> str:
    return result.stderr.strip()[-1000:]


def _bounded_text(value: str) -> tuple[str, bool]:
    if len(value) <= MAX_PATCH_CHARS:
        return value, False
    return value[-MAX_PATCH_CHARS:], True


def _capture_git_diff(
    git_root: str,
    untracked: tuple[str, ...],
) -> subprocess.CompletedProcess[str]:
    if not untracked:
        return _git_run(
            git_root,
            "diff",
            "--binary",
            "--no-ext-diff",
            "HEAD",
            "--",
            timeout=20,
        )
    with tempfile.TemporaryDirectory(prefix="gpt2giga-index-") as temporary_dir:
        index_env = {"GIT_INDEX_FILE": str(Path(temporary_dir) / "index")}
        initialized = _git_run(git_root, "read-tree", "HEAD", env=index_env)
        if initialized.returncode != 0:
            return initialized
        add_intent = _git_run(
            git_root,
            "add",
            "-N",
            "--",
            *untracked,
            timeout=10,
            env=index_env,
        )
        if add_intent.returncode != 0:
            return add_intent
        return _git_run(
            git_root,
            "diff",
            "--binary",
            "--no-ext-diff",
            "HEAD",
            "--",
            timeout=20,
            env=index_env,
        )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _can_apply(execution: Mapping[str, Any], patch: str) -> bool:
    return (
        execution.get("policy") == WorkspacePolicy.WORKTREE.value
        and bool(patch.strip())
        and patch.strip() != "No diff captured."
        and not execution.get("truncated")
        and not execution.get("applied_at")
        and not execution.get("discarded_at")
    )


def _can_discard(execution: Mapping[str, Any]) -> bool:
    return execution.get(
        "policy"
    ) == WorkspacePolicy.WORKTREE.value and not execution.get("discarded_at")
