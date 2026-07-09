import subprocess
from pathlib import Path

from gpt2giga.harness.worktrees import (
    WorkspacePolicy,
    apply_run_diff,
    capture_workspace_diff,
    discard_run_worktree,
    prepare_workspace_execution,
)


def test_worktree_execution_captures_and_applies_patch(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    data_dir = tmp_path / "data"

    execution = prepare_workspace_execution(
        requested_policy="worktree",
        harness_kind="agent-cli",
        mode="edit",
        workspace=str(repo),
        data_dir=data_dir,
        session_id="sess_test",
        run_id="run_test",
    )

    assert execution.policy is WorkspacePolicy.WORKTREE
    assert execution.source_git_root == str(repo)
    assert execution.request_workspace != str(repo)

    worktree = Path(execution.request_workspace or "")
    (worktree / "app.txt").write_text("changed\n", encoding="utf-8")
    (worktree / "new.txt").write_text("new\n", encoding="utf-8")

    diff = capture_workspace_diff(execution)

    assert diff is not None
    assert diff.captured is True
    assert "app.txt" in diff.changed_files
    assert "new.txt" in diff.untracked_files
    assert "diff --git a/app.txt b/app.txt" in diff.patch
    assert "diff --git a/new.txt b/new.txt" in diff.patch
    assert (repo / "app.txt").read_text(encoding="utf-8") == "base\n"

    metadata = {
        "workspace_execution": {**execution.to_metadata(), **diff.to_metadata()}
    }
    applied = apply_run_diff(metadata)

    assert applied["applied_at"]
    assert (repo / "app.txt").read_text(encoding="utf-8") == "changed\n"
    assert (repo / "new.txt").read_text(encoding="utf-8") == "new\n"


def test_discard_run_worktree_removes_isolated_checkout(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    execution = prepare_workspace_execution(
        requested_policy="worktree",
        harness_kind="agent-cli",
        mode="edit",
        workspace=str(repo),
        data_dir=tmp_path / "data",
        session_id="sess_test",
        run_id="run_discard",
    )
    worktree = Path(execution.request_workspace or "")
    assert worktree.exists()

    discarded = discard_run_worktree({"workspace_execution": execution.to_metadata()})

    assert discarded["discarded_at"]
    assert not worktree.exists()
    assert (repo / "app.txt").read_text(encoding="utf-8") == "base\n"


def test_worktree_policy_falls_back_outside_git(tmp_path):
    workspace = tmp_path / "plain"
    workspace.mkdir()

    execution = prepare_workspace_execution(
        requested_policy="worktree",
        harness_kind="agent-cli",
        mode="edit",
        workspace=str(workspace),
        data_dir=tmp_path / "data",
        session_id="sess_test",
        run_id="run_plain",
    )

    assert execution.policy is WorkspacePolicy.CURRENT
    assert execution.request_workspace == str(workspace)
    assert execution.fallback_reason == "workspace is not inside a git repository"


def _git_repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test User")
    (path / "app.txt").write_text("base\n", encoding="utf-8")
    _git(path, "add", "app.txt")
    _git(path, "commit", "-m", "initial")
    return path


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ("git", "-C", str(cwd), *args),
        check=True,
        capture_output=True,
        text=True,
    )
