import subprocess
from pathlib import Path

import pytest

import gpt2giga.harness.worktrees as worktrees
from gpt2giga.harness.worktrees import (
    WorktreeError,
    WorkspacePolicy,
    apply_run_diff,
    capture_workspace_diff,
    discard_run_worktree,
    prepare_workspace_execution,
    run_diff_response,
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


def test_worktree_policy_fails_closed_outside_git(tmp_path):
    workspace = tmp_path / "plain"
    workspace.mkdir()

    with pytest.raises(WorktreeError, match="requires a Git repository"):
        prepare_workspace_execution(
            requested_policy="worktree",
            harness_kind="agent-cli",
            mode="edit",
            workspace=str(workspace),
            data_dir=tmp_path / "data",
            session_id="sess_test",
            run_id="run_plain",
        )


def test_current_workspace_diff_does_not_modify_index(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    execution = prepare_workspace_execution(
        requested_policy="current",
        harness_kind="agent-cli",
        mode="edit",
        workspace=str(repo),
        data_dir=tmp_path / "data",
        session_id="sess_test",
        run_id="run_current",
    )

    diff = capture_workspace_diff(execution)

    assert diff is not None
    assert "diff --git a/new.txt b/new.txt" in diff.patch
    status = subprocess.run(
        ("git", "-C", str(repo), "status", "--porcelain=v1"),
        check=True,
        capture_output=True,
        text=True,
    )
    assert status.stdout == "?? new.txt\n"


def test_truncated_patch_cannot_be_applied(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "repo")
    execution = prepare_workspace_execution(
        requested_policy="worktree",
        harness_kind="agent-cli",
        mode="edit",
        workspace=str(repo),
        data_dir=tmp_path / "data",
        session_id="sess_test",
        run_id="run_large",
    )
    Path(execution.request_workspace or "", "app.txt").write_text(
        "changed content that exceeds the test patch limit\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(worktrees, "MAX_PATCH_CHARS", 20)
    diff = capture_workspace_diff(execution)
    assert diff is not None
    assert diff.truncated is True
    metadata = {
        "workspace_execution": {**execution.to_metadata(), **diff.to_metadata()}
    }

    assert run_diff_response(metadata)["can_apply"] is False
    with pytest.raises(WorktreeError, match="truncated"):
        apply_run_diff(metadata)


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
