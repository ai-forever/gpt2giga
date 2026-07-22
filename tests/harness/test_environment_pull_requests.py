from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.environment_pull_requests import (
    EnvironmentPullRequestService,
    _CommandResult,
)
from gpt2giga_harness.environments import HostedRepositoryHint
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.ui.app import create_app


PR_CLOCK = datetime(2026, 7, 22, 14, 0, tzinfo=timezone.utc)
HOSTED_REPOSITORY = HostedRepositoryHint("github.com", "fixture/repository")


class HostedFixture:
    def __init__(self, head: str) -> None:
        self.head = head
        self.pull_request: dict[str, object] | None = None
        self.write_inputs: list[dict[str, object]] = []
        self.lose_write_response = False

    def __call__(
        self,
        command: tuple[str, ...],
        _cwd: Path,
        input_bytes: bytes | None,
        _timeout: float,
    ) -> _CommandResult:
        args = command[1:]
        if args[:2] == ("auth", "status"):
            return _CommandResult(0, b"", b"")
        if args[:2] == ("repo", "view"):
            return self._json(
                {
                    "nameWithOwner": "fixture/repository",
                    "url": "https://github.com/fixture/repository",
                    "defaultBranchRef": {"name": "main"},
                    "isFork": False,
                }
            )
        if args[:2] == ("pr", "list"):
            return self._json([self.pull_request] if self.pull_request else [])
        if args[0] == "api":
            assert "--input" in args
            assert input_bytes is not None
            payload = json.loads(input_bytes)
            self.write_inputs.append(payload)
            self.pull_request = {
                "number": 17,
                "html_url": "https://github.com/fixture/repository/pull/17",
                "url": "https://github.com/fixture/repository/pull/17",
                "state": "open",
                "head": {"ref": "feature/pr", "sha": self.head},
                "base": {"ref": "main"},
                "headRefName": "feature/pr",
                "headRefOid": self.head,
                "baseRefName": "main",
            }
            if self.lose_write_response:
                return _CommandResult(1, b"", b"connection lost")
            return self._json(self.pull_request)
        raise AssertionError(f"unexpected hosted command: {args!r}")

    @staticmethod
    def _json(value: object) -> _CommandResult:
        return _CommandResult(0, json.dumps(value).encode(), b"")


def test_environment_pull_request_api_requires_distinct_approval_and_replays(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    head = _git_output(repository, "rev-parse", "HEAD")
    hosted = HostedFixture(head)
    state = tmp_path / "state"
    service = EnvironmentPullRequestService(
        state,
        gh_executable="/fixture/gh",
        command_runner=hosted,
        clock=lambda: PR_CLOCK,
        repository_resolver=lambda _snapshot: HOSTED_REPOSITORY,
    )
    client = TestClient(
        create_app(
            HarnessConfig(data_dir=str(state)),
            registry=create_default_registry(include_entry_points=False),
            environment_pull_request_service=service,
        )
    )

    preview_response = client.post(
        "/api/environment/pull-request/preview",
        json={
            "workspace": str(repository),
            "title": "Ship governed PRs",
            "body": "Exact reviewed body.",
        },
    )

    assert preview_response.status_code == 200
    preview = preview_response.json()["preview"]
    assert preview["repository"]["name_with_owner"] == "fixture/repository"
    assert preview["remote"] == "origin"
    assert preview["source_branch"] == "feature/pr"
    assert preview["source_head"] == head == preview["source_remote_head"]
    assert preview["base_branch"] == "main"
    assert preview["title"] == "Ship governed PRs"
    assert preview["body"] == "Exact reviewed body."
    assert preview_response.json()["approval"]["action"] == (
        "github.pull_request.create"
    )

    requested = client.post(
        "/api/environment/pull-request/apply",
        json={"preview_id": preview["id"], "workspace": str(repository)},
    )

    assert requested.status_code == 202
    approval = requested.json()["approval"]
    assert approval["action"] == "github.pull_request.create"
    assert approval["enforcement_owner"] == "environment.pull_request"
    assert approval["preview"]["title"] == "Ship governed PRs"
    assert approval["preview"]["source_head"] == head
    assert hosted.write_inputs == []

    assert (
        client.post(
            f"/api/approvals/{approval['id']}/decision",
            json={"decision": "allow_once"},
        ).status_code
        == 200
    )
    created = client.post(
        "/api/environment/pull-request/apply",
        json={"preview_id": preview["id"], "workspace": str(repository)},
    )

    assert created.status_code == 200
    result = created.json()["result"]
    assert result["number"] == 17
    assert result["commit_head"] == head
    assert result["pull_request_url"].endswith("/pull/17")
    assert result["commit_url"].endswith(f"/commit/{head}")
    assert result["checks_url"].endswith("/pull/17/checks")
    assert "/actions?query=branch%3Afeature%2Fpr" in result["run_evidence_url"]
    assert hosted.write_inputs == [
        {
            "base": "main",
            "body": "Exact reviewed body.",
            "draft": False,
            "head": "feature/pr",
            "title": "Ship governed PRs",
        }
    ]

    replay = client.post(
        "/api/environment/pull-request/apply",
        json={"preview_id": preview["id"], "workspace": str(repository)},
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["result"] == result
    assert len(hosted.write_inputs) == 1


def test_environment_pull_request_rejects_stale_remote_before_approval(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    state = tmp_path / "state"
    hosted = HostedFixture(_git_output(repository, "rev-parse", "HEAD"))
    service = EnvironmentPullRequestService(
        state,
        gh_executable="/fixture/gh",
        command_runner=hosted,
        clock=lambda: PR_CLOCK,
        repository_resolver=lambda _snapshot: HOSTED_REPOSITORY,
    )
    client = TestClient(
        create_app(
            HarnessConfig(data_dir=str(state)),
            registry=create_default_registry(include_entry_points=False),
            environment_pull_request_service=service,
        )
    )
    preview = client.post(
        "/api/environment/pull-request/preview",
        json={"workspace": str(repository), "title": "Exact PR", "body": ""},
    ).json()["preview"]
    _git(repository, "switch", "main")
    (repository / "base-race.txt").write_text("race\n", encoding="utf-8")
    _git(repository, "add", "base-race.txt")
    _git(repository, "commit", "-qm", "base race")
    _git(repository, "push", "-q", "origin", "main")
    _git(repository, "switch", "feature/pr")

    stale = client.post(
        "/api/environment/pull-request/apply",
        json={"preview_id": preview["id"], "workspace": str(repository)},
    )

    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "remote_changed"
    assert client.get("/api/approvals").json()["approvals"] == []
    assert hosted.write_inputs == []


def test_environment_pull_request_recovers_network_loss_after_hosted_write(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    head = _git_output(repository, "rev-parse", "HEAD")
    hosted = HostedFixture(head)
    hosted.lose_write_response = True
    service = EnvironmentPullRequestService(
        tmp_path / "state",
        gh_executable="/fixture/gh",
        command_runner=hosted,
        clock=lambda: PR_CLOCK,
        repository_resolver=lambda _snapshot: HOSTED_REPOSITORY,
    )
    preview = service.preview(
        repository,
        title="Recover exact PR",
        body="Network response may disappear.",
    )

    result = service.apply(preview.id)

    assert result.number == 17
    assert result.commit_head == head
    assert result.recovered is True
    assert service.apply(preview.id) == result
    assert len(hosted.write_inputs) == 1


def _repository(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    repository = tmp_path / "repository"
    _git(tmp_path, "init", "--bare", "-q", "--initial-branch=main", str(remote))
    _git(tmp_path, "init", "-q", "--initial-branch=main", str(repository))
    _git(repository, "config", "user.name", "Fixture User")
    _git(repository, "config", "user.email", "fixture@example.com")
    (repository / "tracked.txt").write_text("main\n", encoding="utf-8")
    _git(repository, "add", "tracked.txt")
    _git(repository, "commit", "-qm", "main")
    _git(repository, "remote", "add", "origin", str(remote))
    _git(repository, "push", "-qu", "origin", "main")
    _git(repository, "switch", "-qc", "feature/pr")
    (repository / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(repository, "add", "feature.txt")
    _git(repository, "commit", "-qm", "feature")
    _git(repository, "push", "-qu", "origin", "feature/pr")
    return repository


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _git_output(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
