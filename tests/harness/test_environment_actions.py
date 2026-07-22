from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient
import pytest

from gpt2giga_harness import environment_actions
from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.environment_actions import (
    EnvironmentCommitError,
    EnvironmentCommitService,
)
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.ui.app import create_app


COMMIT_CLOCK = datetime(2026, 7, 22, 9, 0, tzinfo=timezone.utc)


def test_environment_commit_api_requires_exact_approval_and_is_idempotent(tmp_path):
    repository = _repository(tmp_path)
    state = tmp_path / "state"
    client = TestClient(
        create_app(
            HarnessConfig(data_dir=str(state)),
            registry=create_default_registry(include_entry_points=False),
            environment_commit_service=EnvironmentCommitService(
                state,
                clock=lambda: COMMIT_CLOCK,
            ),
        )
    )

    preview_response = client.post(
        "/api/environment/commit/preview",
        json={
            "workspace": str(repository),
            "message": "feat: governed commit",
            "author_name": "Workbench Operator",
            "author_email": "operator@example.com",
        },
    )

    assert preview_response.status_code == 200
    preview = preview_response.json()["preview"]
    assert preview["head"] == _git_output(repository, "rev-parse", "HEAD")
    assert preview["staged_count"] == 1
    assert preview["hooks_executed"] is False
    assert preview_response.json()["approval"]["action"] == "git.commit"

    requested = client.post(
        "/api/environment/commit/apply",
        json={"preview_id": preview["id"], "workspace": str(repository)},
    )

    assert requested.status_code == 202
    approval = requested.json()["approval"]
    assert approval["action"] == "git.commit"
    assert approval["enforcement_owner"] == "environment.commit"
    assert approval["preview"]["head"] == preview["head"]
    assert approval["preview"]["diff_sha256"] == preview["diff_sha256"]
    assert approval["preview"]["message"] == "feat: governed commit"

    decided = client.post(
        f"/api/approvals/{approval['id']}/decision",
        json={"decision": "allow_once"},
    )
    assert decided.status_code == 200

    committed = client.post(
        "/api/environment/commit/apply",
        json={"preview_id": preview["id"], "workspace": str(repository)},
    )

    assert committed.status_code == 200
    result = committed.json()["result"]
    assert result["parent_head"] == preview["head"]
    assert result["commit_head"] == _git_output(repository, "rev-parse", "HEAD")
    assert _git_output(repository, "log", "-1", "--format=%s") == (
        "feat: governed commit"
    )
    assert _git_output(repository, "log", "-1", "--format=%an <%ae>") == (
        "Workbench Operator <operator@example.com>"
    )
    assert _git_output(repository, "status", "--porcelain") == ""

    replay = client.post(
        "/api/environment/commit/apply",
        json={"preview_id": preview["id"], "workspace": str(repository)},
    )

    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["result"]["commit_head"] == result["commit_head"]
    assert _git_output(repository, "rev-list", "--count", "HEAD") == "2"


def test_environment_commit_rejects_stale_preview_before_approval_consumption(
    tmp_path,
):
    repository = _repository(tmp_path)
    state = tmp_path / "state"
    client = TestClient(
        create_app(
            HarnessConfig(data_dir=str(state)),
            registry=create_default_registry(include_entry_points=False),
            environment_commit_service=EnvironmentCommitService(
                state,
                clock=lambda: COMMIT_CLOCK,
            ),
        )
    )
    preview = client.post(
        "/api/environment/commit/preview",
        json={
            "workspace": str(repository),
            "message": "fix: exact staged state",
            "author_name": "Workbench Operator",
            "author_email": "operator@example.com",
        },
    ).json()["preview"]
    (repository / "tracked.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    _git(repository, "add", "tracked.txt")

    stale = client.post(
        "/api/environment/commit/apply",
        json={"preview_id": preview["id"], "workspace": str(repository)},
    )

    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_preview"
    assert client.get("/api/approvals").json()["approvals"] == []
    assert _git_output(repository, "rev-list", "--count", "HEAD") == "1"


def test_environment_commit_recovers_completion_after_result_write_gap(tmp_path):
    repository = _repository(tmp_path)
    state = tmp_path / "state"
    service = EnvironmentCommitService(state, clock=lambda: COMMIT_CLOCK)
    preview = service.preview(
        repository,
        message="test: recover exact commit",
        author_name="Workbench Operator",
        author_email="operator@example.com",
    )
    committed = service.apply(preview.id)
    result_path = state / "environment_commits" / "results" / f"{preview.id}.json"
    result_path.unlink()

    recovered = service.apply(preview.id)

    assert recovered.commit_head == committed.commit_head
    assert recovered.recovered is True
    assert _git_output(repository, "rev-list", "--count", "HEAD") == "2"


def test_environment_commit_rejects_index_race_after_tree_capture(
    tmp_path, monkeypatch
):
    repository = _repository(tmp_path)
    service = EnvironmentCommitService(
        tmp_path / "state",
        clock=lambda: COMMIT_CLOCK,
    )
    preview = service.preview(
        repository,
        message="test: bind exact tree",
        author_name="Workbench Operator",
        author_email="operator@example.com",
    )
    required_sha = service._required_sha

    def stage_after_tree(root, *args):
        tree = required_sha(root, *args)
        (repository / "tracked.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
        _git(repository, "add", "tracked.txt")
        return tree

    monkeypatch.setattr(service, "_required_sha", stage_after_tree)

    with pytest.raises(EnvironmentCommitError) as error:
        service.apply(preview.id)

    assert error.value.code == "stale_preview"
    assert _git_output(repository, "rev-list", "--count", "HEAD") == "1"


def test_environment_commit_validation_errors_are_content_free(tmp_path):
    repository = _repository(tmp_path)
    client = TestClient(
        create_app(
            HarnessConfig(data_dir=str(tmp_path / "state")),
            registry=create_default_registry(include_entry_points=False),
        )
    )

    response = client.post(
        "/api/environment/commit/preview",
        json={
            "workspace": str(repository),
            "message": "canary-message",
            "author_name": "canary-author",
            "author_email": "not-an-email-canary",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "author_invalid"
    assert "not-an-email-canary" not in response.text
    assert "canary-message" not in response.text
    assert str(repository) not in response.text


def test_ui_starts_without_git_and_commit_preview_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(environment_actions.shutil, "which", lambda _command: None)
    client = TestClient(
        create_app(
            HarnessConfig(data_dir=str(tmp_path / "state")),
            registry=create_default_registry(include_entry_points=False),
        )
    )

    health = client.get("/healthz")
    preview = client.post(
        "/api/environment/commit/preview",
        json={
            "workspace": str(tmp_path),
            "message": "test: unavailable git",
            "author_name": "Workbench Operator",
            "author_email": "operator@example.com",
        },
    )

    assert health.status_code == 200
    assert preview.status_code == 409
    assert preview.json()["detail"]["code"] == "git_unavailable"


def _repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    _git(tmp_path, "init", "-q", str(repository))
    _git(repository, "config", "user.name", "Fixture User")
    _git(repository, "config", "user.email", "fixture@example.com")
    tracked = repository / "tracked.txt"
    tracked.write_text("one\n", encoding="utf-8")
    _git(repository, "add", "tracked.txt")
    _git(repository, "commit", "-qm", "fixture")
    tracked.write_text("one\ntwo\n", encoding="utf-8")
    _git(repository, "add", "tracked.txt")
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
