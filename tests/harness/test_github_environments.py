from __future__ import annotations

from datetime import datetime, timezone
import json
import subprocess
import sys
import threading
import time

from fastapi.testclient import TestClient

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.environments import EnvironmentSnapshot, HostedRepositoryHint
from gpt2giga_harness.github_environments import (
    GitHubCountRollup,
    GitHubEnvironmentSnapshot,
    GitHubEnvironmentService,
    GitHubPullRequestState,
    GitHubRepositoryIdentity,
    _CommandResult,
    _run_gh_command,
)
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.ui.app import create_app


CHECKED_AT = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
HINT = HostedRepositoryHint("github.com", "ferriscorp/gigalo")


def test_github_enrichment_is_content_free_bounded_and_cached(tmp_path):
    commands: list[tuple[str, ...]] = []
    monotonic = [0.0]

    def runner(command, cwd, timeout, cancel_event):
        assert cwd == tmp_path
        assert 0 < timeout <= 3
        assert cancel_event.is_set() is False
        commands.append(command)
        if command[1:3] == ("auth", "status"):
            return _CommandResult(0, b"", b"")
        if command[1:3] == ("repo", "view"):
            return _json_result(
                {
                    "nameWithOwner": "ferriscorp/gigalo",
                    "url": "https://github.com/ferriscorp/gigalo",
                    "isFork": False,
                    "defaultBranchRef": {"name": "main"},
                }
            )
        if command[1:3] == ("pr", "list"):
            return _json_result(
                [
                    {
                        "number": 164,
                        "state": "OPEN",
                        "url": "https://github.com/ferriscorp/gigalo/pull/164",
                        "isDraft": False,
                        "headRefName": "feature/environment",
                        "baseRefName": "main",
                        "closingIssuesReferences": [
                            {
                                "number": 77,
                                "state": "OPEN",
                                "url": "https://github.com/ferriscorp/gigalo/issues/77",
                            }
                        ],
                        "statusCheckRollup": [
                            {"name": "secret job name", "conclusion": "SUCCESS"},
                            {"context": "private context", "state": "PENDING"},
                        ],
                    }
                ]
            )
        if command[1:3] == ("run", "list"):
            return _json_result(
                [
                    {
                        "databaseId": 123,
                        "status": "completed",
                        "conclusion": "success",
                        "headSha": "a" * 40,
                        "url": "https://github.com/ferriscorp/gigalo/actions/runs/123",
                        "createdAt": "2026-07-22T11:55:00Z",
                        "updatedAt": "2026-07-22T11:59:00Z",
                    }
                ]
            )
        assert command[1:3] == ("run", "view")
        return _json_result(
            {
                "jobs": [
                    {"name": "content omitted", "conclusion": "success"},
                    {"name": "content omitted too", "status": "in_progress"},
                ]
            }
        )

    service = GitHubEnvironmentService(
        gh_executable="/fixture/gh",
        command_runner=runner,
        clock=lambda: CHECKED_AT,
        monotonic=lambda: monotonic[0],
    )
    environment = _environment(tmp_path)

    snapshot = service.inspect(environment, HINT)
    cached = service.inspect(environment, HINT)

    assert snapshot.status == "ready"
    assert snapshot.auth_status == "authenticated"
    assert snapshot.repository.name_with_owner == "ferriscorp/gigalo"
    assert snapshot.pull_request.number == 164
    assert snapshot.pull_request.checks.to_dict() == {
        "status": "pending",
        "total": 2,
        "passed": 1,
        "failed": 0,
        "pending": 1,
        "skipped": 0,
        "cancelled": 0,
        "unknown": 0,
    }
    assert snapshot.runs[0].jobs.status == "pending"
    assert cached.cached is True
    assert len(commands) == 5
    assert all("--show-token" not in command for command in commands)
    assert all(
        command[1:3]
        not in {
            ("pr", "create"),
            ("repo", "create"),
            ("run", "rerun"),
        }
        for command in commands
    )
    serialized = json.dumps(snapshot.to_dict(), sort_keys=True)
    assert "secret job name" not in serialized
    assert "private context" not in serialized

    monotonic[0] = 31.0

    def rate_limited(command, cwd, timeout, cancel_event):
        return _CommandResult(1, b"", b"API rate limit exceeded TOKEN=canary")

    service._runner = rate_limited
    stale = service.inspect(environment, HINT)

    assert stale.status == "stale"
    assert stale.reason_code == "rate_limited"
    assert stale.cached is True
    assert stale.repository == snapshot.repository
    assert "canary" not in repr(stale)


def test_github_enrichment_fails_closed_for_auth_and_repository_mismatch(tmp_path):
    environment = _environment(tmp_path)

    def unauthenticated(command, cwd, timeout, cancel_event):
        return _CommandResult(1, b"", b"not logged into github.com TOKEN=canary")

    unauthenticated_service = GitHubEnvironmentService(
        gh_executable="/fixture/gh",
        command_runner=unauthenticated,
        clock=lambda: CHECKED_AT,
    )
    snapshot = unauthenticated_service.inspect(environment, HINT)

    assert snapshot.status == "unavailable"
    assert snapshot.auth_status == "unauthenticated"
    assert snapshot.reason_code == "unauthenticated"
    assert "canary" not in repr(snapshot)

    def mismatch(command, cwd, timeout, cancel_event):
        if command[1:3] == ("auth", "status"):
            return _CommandResult(0, b"", b"")
        return _json_result(
            {
                "nameWithOwner": "other/repository",
                "url": "https://github.com/other/repository",
                "isFork": False,
                "defaultBranchRef": {"name": "main"},
            }
        )

    mismatch_service = GitHubEnvironmentService(
        gh_executable="/fixture/gh",
        command_runner=mismatch,
        clock=lambda: CHECKED_AT,
    )

    mismatch_snapshot = mismatch_service.inspect(environment, HINT)

    assert mismatch_snapshot.status == "unavailable"
    assert mismatch_snapshot.reason_code == "repository_mismatch"


def test_gh_subprocess_is_killed_on_cancellation(tmp_path):
    cancel = threading.Event()
    timer = threading.Timer(0.1, cancel.set)
    timer.start()
    started = time.monotonic()
    try:
        try:
            _run_gh_command(
                (
                    sys.executable,
                    "-c",
                    "import time; time.sleep(30)",
                ),
                tmp_path,
                5.0,
                cancel,
            )
        except Exception as exc:
            assert getattr(exc, "code", None) == "cancelled"
        else:  # pragma: no cover - defensive assertion
            raise AssertionError("cancelled command unexpectedly completed")
    finally:
        timer.cancel()
    assert time.monotonic() - started < 2.0


def test_environment_api_projects_optional_github_state(tmp_path):
    repository = tmp_path / "repository"
    _git(tmp_path, "init", "-q", str(repository))
    _git(repository, "config", "user.email", "test@example.com")
    _git(repository, "config", "user.name", "Harness Tests")
    (repository / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(repository, "add", "README.md")
    _git(repository, "commit", "-qm", "fixture")
    _git(
        repository,
        "remote",
        "add",
        "origin",
        "https://github.com/ferriscorp/gigalo.git",
    )

    class StubGitHubService:
        def inspect(self, environment, hint, *, cancel_event=None):
            assert environment.branch
            assert hint == HINT
            assert cancel_event is not None
            return GitHubEnvironmentSnapshot(
                status="ready",
                auth_status="authenticated",
                checked_at="2026-07-22T12:00:00Z",
                repository=GitHubRepositoryIdentity(
                    "github.com",
                    "ferriscorp/gigalo",
                    "https://github.com/ferriscorp/gigalo",
                    "main",
                    False,
                ),
                pull_request=GitHubPullRequestState(
                    164,
                    "open",
                    "https://github.com/ferriscorp/gigalo/pull/164",
                    False,
                    environment.branch,
                    "main",
                    GitHubCountRollup(total=1, passed=1),
                    (),
                ),
            )

    client = TestClient(
        create_app(
            HarnessConfig(data_dir=str(tmp_path / "state")),
            registry=create_default_registry(include_entry_points=False),
            github_environment_service=StubGitHubService(),
        )
    )

    response = client.get("/api/environment", params={"workspace": str(repository)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["github"]["repository"]["name_with_owner"] == "ferriscorp/gigalo"
    assert payload["issue_pr"] == {
        "status": "open",
        "kind": "pull_request",
        "number": 164,
        "url": "https://github.com/ferriscorp/gigalo/pull/164",
        "checks": {
            "status": "passed",
            "total": 1,
            "passed": 1,
            "failed": 0,
            "pending": 0,
            "skipped": 0,
            "cancelled": 0,
            "unknown": 0,
        },
        "issues": [],
    }


def _environment(tmp_path) -> EnvironmentSnapshot:
    return EnvironmentSnapshot(
        provider_id="git",
        repository_root=str(tmp_path),
        worktree_root=str(tmp_path),
        branch="feature/environment",
        detached=False,
        head="a" * 40,
        base_identity="b" * 40,
        upstream="origin/feature/environment",
        ahead=1,
        behind=0,
        remote="origin",
        staged_count=1,
        unstaged_count=0,
        untracked_count=0,
        additions=1,
        deletions=0,
        changed_paths=("README.md",),
        changed_paths_truncated=False,
        diff_sha256="c" * 64,
        captured_at="2026-07-22T12:00:00Z",
        push_ready=True,
        push_blocker=None,
    )


def _json_result(payload) -> _CommandResult:
    return _CommandResult(0, json.dumps(payload).encode(), b"")


def _git(cwd, *args):
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    )
