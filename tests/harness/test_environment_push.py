from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient
import pytest

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.environment_push import (
    EnvironmentPushError,
    EnvironmentPushService,
)
from gpt2giga_harness.environments import HostedRepositoryHint
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.ui.app import create_app


PUSH_CLOCK = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
HOSTED_REPOSITORY = HostedRepositoryHint("github.com", "fixture/repository")


def test_environment_push_api_requires_exact_approval_and_is_idempotent(tmp_path):
    repository, remote = _repository(tmp_path)
    state = tmp_path / "state"
    client = TestClient(
        create_app(
            HarnessConfig(data_dir=str(state)),
            registry=create_default_registry(include_entry_points=False),
            environment_push_service=_service(state),
        )
    )

    preview_response = client.post(
        "/api/environment/push/preview",
        json={"workspace": str(repository)},
    )

    assert preview_response.status_code == 200
    preview = preview_response.json()["preview"]
    assert preview["head"] == _git_output(repository, "rev-parse", "HEAD")
    assert preview["remote"] == "origin"
    assert preview["upstream"] == "origin/main"
    assert preview["target_branch"] == "main"
    assert preview["remote_head"] == _remote_head(remote)
    assert preview["permissions"] == {
        "network_connect": True,
        "remote_write": True,
        "create_remote_branch": False,
        "set_upstream": False,
        "force_update": False,
        "delete_remote_branch": False,
        "follow_tags": False,
        "execute_hooks": False,
    }
    assert preview_response.json()["approval"]["action"] == "git.push"

    requested = client.post(
        "/api/environment/push/apply",
        json={"preview_id": preview["id"], "workspace": str(repository)},
    )

    assert requested.status_code == 202
    approval = requested.json()["approval"]
    assert approval["action"] == "git.push"
    assert approval["enforcement_owner"] == "environment.push"
    assert approval["preview"]["head"] == preview["head"]
    assert approval["preview"]["remote_head"] == preview["remote_head"]
    assert approval["preview"]["permissions"]["remote_write"] is True

    decided = client.post(
        f"/api/approvals/{approval['id']}/decision",
        json={"decision": "allow_once"},
    )
    assert decided.status_code == 200

    pushed = client.post(
        "/api/environment/push/apply",
        json={"preview_id": preview["id"], "workspace": str(repository)},
    )

    assert pushed.status_code == 200
    result = pushed.json()["result"]
    assert result["commit_head"] == preview["head"] == _remote_head(remote)
    assert result["remote_commit_url"].endswith(f"/commit/{preview['head']}")
    assert result["run_evidence_url"].endswith(f"/commit/{preview['head']}/checks")
    assert result["recovered"] is False

    replay = client.post(
        "/api/environment/push/apply",
        json={"preview_id": preview["id"], "workspace": str(repository)},
    )

    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["result"] == result


def test_environment_push_rejects_local_and_remote_staleness_before_approval(
    tmp_path,
):
    repository, remote = _repository(tmp_path)
    state = tmp_path / "state"
    client = TestClient(
        create_app(
            HarnessConfig(data_dir=str(state)),
            registry=create_default_registry(include_entry_points=False),
            environment_push_service=_service(state),
        )
    )
    preview = client.post(
        "/api/environment/push/preview",
        json={"workspace": str(repository)},
    ).json()["preview"]
    (repository / "tracked.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")

    local_stale = client.post(
        "/api/environment/push/apply",
        json={"preview_id": preview["id"], "workspace": str(repository)},
    )

    assert local_stale.status_code == 409
    assert local_stale.json()["detail"]["code"] == "stale_preview"
    assert client.get("/api/approvals").json()["approvals"] == []

    _git(repository, "restore", "tracked.txt")
    second_preview = client.post(
        "/api/environment/push/preview",
        json={"workspace": str(repository)},
    ).json()["preview"]
    racer = tmp_path / "racer"
    _git(tmp_path, "clone", "-q", str(remote), str(racer))
    _git(racer, "config", "user.name", "Racer")
    _git(racer, "config", "user.email", "racer@example.com")
    (racer / "race.txt").write_text("race\n", encoding="utf-8")
    _git(racer, "add", "race.txt")
    _git(racer, "commit", "-qm", "race")
    _git(racer, "push", "-q", "origin", "HEAD:main")

    remote_stale = client.post(
        "/api/environment/push/apply",
        json={"preview_id": second_preview["id"], "workspace": str(repository)},
    )

    assert remote_stale.status_code == 409
    assert remote_stale.json()["detail"]["code"] == "remote_changed"
    assert client.get("/api/approvals").json()["approvals"] == []


def test_environment_push_recovers_network_loss_after_remote_write(
    tmp_path, monkeypatch
):
    repository, remote = _repository(tmp_path)
    service = _service(tmp_path / "state")
    preview = service.preview(repository)
    original_run = service._run
    interrupted = False

    def lose_response(root: Path, *args: str):
        nonlocal interrupted
        result = original_run(root, *args)
        if args and args[0] == "push" and not interrupted:
            interrupted = True
            return type(result)(1, result.stdout, b"network response lost")
        return result

    monkeypatch.setattr(service, "_run", lose_response)

    result = service.apply(preview.id)

    assert result.commit_head == preview.head == _remote_head(remote)
    assert result.recovered is True
    assert service.apply(preview.id) == result


def test_environment_push_disables_hooks_and_rejects_push_url_override(tmp_path):
    repository, remote = _repository(tmp_path)
    service = _service(tmp_path / "state")
    hook_marker = tmp_path / "hook-ran"
    hook = repository / ".git" / "hooks" / "pre-push"
    hook.write_text(f"#!/bin/sh\ntouch '{hook_marker}'\n", encoding="utf-8")
    hook.chmod(0o755)
    preview = service.preview(repository)

    result = service.apply(preview.id)

    assert result.commit_head == _remote_head(remote)
    assert not hook_marker.exists()

    next_file = repository / "next.txt"
    next_file.write_text("next\n", encoding="utf-8")
    _git(repository, "add", "next.txt")
    _git(repository, "commit", "-qm", "next")
    next_preview = service.preview(repository)
    _git(repository, "config", "remote.origin.pushurl", str(remote))

    with pytest.raises(EnvironmentPushError) as error:
        service.validate_current(next_preview)

    assert error.value.code == "push_url_override"
    assert _remote_head(remote) != next_preview.head


def test_environment_push_previews_and_configures_new_upstream_explicitly(tmp_path):
    repository, remote = _repository(tmp_path)
    _git(repository, "switch", "-qc", "feature/new-upstream")
    service = _service(tmp_path / "state")

    preview = service.preview(repository)

    assert preview.upstream is None
    assert preview.target_branch == "feature/new-upstream"
    assert preview.remote_head is None
    assert preview.to_dict()["permissions"]["create_remote_branch"] is True
    assert preview.to_dict()["permissions"]["set_upstream"] is True

    result = service.apply(preview.id)

    assert result.commit_head == _git_output(
        remote, "rev-parse", "refs/heads/feature/new-upstream"
    )
    assert result.upstream_configured is True
    assert (
        _git_output(
            repository, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"
        )
        == "origin/feature/new-upstream"
    )


def _service(state: Path) -> EnvironmentPushService:
    return EnvironmentPushService(
        state,
        clock=lambda: PUSH_CLOCK,
        repository_resolver=lambda _snapshot: HOSTED_REPOSITORY,
    )


def _repository(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    repository = tmp_path / "repository"
    _git(tmp_path, "init", "--bare", "-q", "--initial-branch=main", str(remote))
    _git(tmp_path, "init", "-q", "--initial-branch=main", str(repository))
    _git(repository, "config", "user.name", "Fixture User")
    _git(repository, "config", "user.email", "fixture@example.com")
    tracked = repository / "tracked.txt"
    tracked.write_text("one\n", encoding="utf-8")
    _git(repository, "add", "tracked.txt")
    _git(repository, "commit", "-qm", "fixture")
    _git(repository, "remote", "add", "origin", str(remote))
    _git(repository, "push", "-qu", "origin", "main")
    tracked.write_text("one\ntwo\n", encoding="utf-8")
    _git(repository, "add", "tracked.txt")
    _git(repository, "commit", "-qm", "ahead")
    return repository, remote


def _remote_head(remote: Path) -> str:
    return _git_output(remote, "rev-parse", "refs/heads/main")


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
