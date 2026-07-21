from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import subprocess

import pytest

from gpt2giga_harness import environments as environment_module
from gpt2giga_harness.environments import (
    ENVIRONMENT_PROVIDER_ENTRY_POINTS,
    MAX_CHANGED_PATHS,
    NEUTRAL_ENVIRONMENT_ENTRY_POINT_GROUP,
    EnvironmentProviderRegistry,
    EnvironmentSnapshot,
    GitEnvironmentProvider,
    git_environment_provider_plugin,
)
from gpt2giga_harness.registries import RegistryCollisionError


CAPTURED_AT = datetime(2026, 7, 22, 8, 30, tzinfo=timezone.utc)


def test_git_environment_snapshot_captures_exact_bounded_local_state(tmp_path):
    repository = tmp_path / "repository"
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", str(remote))
    _init_repository(repository)
    _git(repository, "remote", "add", "origin", str(remote))
    _git(repository, "push", "-u", "origin", "HEAD")

    tracked = repository / "tracked.txt"
    tracked.write_text("one\ntwo\n", encoding="utf-8")
    _git(repository, "add", "tracked.txt")
    tracked.write_text("one\ntwo\nthree\n", encoding="utf-8")
    (repository / "untracked.txt").write_text("safe\n", encoding="utf-8")
    (repository / ".env.production").write_text("TOKEN=canary\n", encoding="utf-8")
    (repository / "ignored.txt").write_text("ignored\n", encoding="utf-8")
    local = repository / "local"
    local.mkdir()
    (local / "private.txt").write_text("private\n", encoding="utf-8")

    provider = GitEnvironmentProvider(clock=lambda: CAPTURED_AT)
    snapshot = provider.snapshot(repository)

    assert snapshot.provider_id == "git"
    assert snapshot.repository_root == str(repository.resolve())
    assert snapshot.worktree_root == str(repository.resolve())
    assert snapshot.branch == _git_output(repository, "branch", "--show-current")
    assert snapshot.detached is False
    assert snapshot.head == _git_output(repository, "rev-parse", "HEAD")
    assert snapshot.base_identity == snapshot.head
    assert snapshot.upstream == f"origin/{snapshot.branch}"
    assert snapshot.ahead == 0
    assert snapshot.behind == 0
    assert snapshot.remote == "origin"
    assert snapshot.staged_count == 1
    assert snapshot.unstaged_count == 1
    assert snapshot.untracked_count == 2
    assert snapshot.additions == 2
    assert snapshot.deletions == 0
    assert snapshot.changed_paths == ("tracked.txt", "untracked.txt")
    assert snapshot.changed_paths_truncated is False
    assert len(snapshot.diff_sha256) == 64
    assert snapshot.captured_at == "2026-07-22T08:30:00Z"
    assert snapshot.push_ready is True
    assert snapshot.push_blocker is None
    serialized = snapshot.to_dict()
    assert EnvironmentSnapshot.from_dict(serialized) == snapshot
    assert "canary" not in repr(snapshot)
    assert ".env" not in repr(snapshot)
    assert "ignored" not in repr(snapshot)
    assert "local" not in snapshot.changed_paths

    tracked.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
    changed = provider.snapshot(repository)

    assert changed.diff_sha256 != snapshot.diff_sha256
    assert changed.additions == 3

    tracked.write_text("one\ntwo\nthree\n", encoding="utf-8")
    untracked = repository / "untracked.txt"
    untracked.write_text("changed safely\n", encoding="utf-8")
    changed_untracked = provider.snapshot(repository)

    assert changed_untracked.diff_sha256 != snapshot.diff_sha256


def test_git_environment_snapshot_tracks_ahead_base_and_linked_worktree(tmp_path):
    repository = tmp_path / "repository"
    remote = tmp_path / "remote.git"
    linked = tmp_path / "linked"
    _git(tmp_path, "init", "--bare", str(remote))
    _init_repository(repository)
    _git(repository, "remote", "add", "origin", str(remote))
    _git(repository, "push", "-u", "origin", "HEAD")
    (repository / "ahead.txt").write_text("ahead\n", encoding="utf-8")
    _git(repository, "add", "ahead.txt")
    _git(repository, "commit", "-qm", "ahead")
    branch = _git_output(repository, "branch", "--show-current")
    _git(repository, "worktree", "add", "-q", "-b", "linked", str(linked), "HEAD")
    _git(linked, "branch", "--set-upstream-to", f"origin/{branch}")

    snapshot = GitEnvironmentProvider(clock=lambda: CAPTURED_AT).snapshot(linked)

    assert snapshot.repository_root == str(repository.resolve())
    assert snapshot.worktree_root == str(linked.resolve())
    assert snapshot.ahead == 1
    assert snapshot.behind == 0
    assert snapshot.base_identity == _git_output(
        repository, "rev-parse", f"origin/{branch}"
    )


def test_git_environment_snapshot_bounds_path_summary_and_rejects_future_shape(
    tmp_path,
):
    repository = tmp_path / "repository"
    _init_repository(repository)
    for index in range(MAX_CHANGED_PATHS + 1):
        (repository / f"path-{index:03}.txt").write_text("value\n", encoding="utf-8")

    snapshot = GitEnvironmentProvider(clock=lambda: CAPTURED_AT).snapshot(repository)

    assert len(snapshot.changed_paths) == MAX_CHANGED_PATHS
    assert snapshot.changed_paths_truncated is True
    assert snapshot.push_ready is False
    assert snapshot.push_blocker == "remote_unavailable"
    payload = snapshot.to_dict()
    payload["future"] = True
    with pytest.raises(ValueError, match="fields are invalid"):
        EnvironmentSnapshot.from_dict(payload)
    with pytest.raises(ValueError, match="changed_paths contain an unsafe path"):
        replace(snapshot, changed_paths=(".env",))


def test_environment_provider_entry_points_use_neutral_registry_kernel(monkeypatch):
    plugin = git_environment_provider_plugin()

    class FakeEntryPoint:
        name = "git"
        value = "gpt2giga_harness.environments:git_environment_provider_plugin"

        def load(self):
            return git_environment_provider_plugin

    class FakeEntryPoints:
        def select(self, *, group):
            assert group == NEUTRAL_ENVIRONMENT_ENTRY_POINT_GROUP
            return (FakeEntryPoint(),)

    monkeypatch.setattr(environment_module, "entry_points", lambda: FakeEntryPoints())
    registry = EnvironmentProviderRegistry.with_builtins()

    registry.load_entry_points()

    assert ENVIRONMENT_PROVIDER_ENTRY_POINTS.registry_id == "environment_provider"
    assert registry.list() == (plugin.descriptor,)
    assert registry.create_provider("git").descriptor == plugin.descriptor
    assert registry.discovery_errors == []
    with pytest.raises(RegistryCollisionError):
        registry.register(
            replace(
                plugin,
                descriptor=replace(plugin.descriptor, display_name="Other Git"),
            )
        )


def _init_repository(path):
    _git(path.parent, "init", "-q", str(path))
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Harness Tests")
    (path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (path / "tracked.txt").write_text("one\n", encoding="utf-8")
    _git(path, "add", ".gitignore", "tracked.txt")
    _git(path, "commit", "-qm", "fixture")


def _git(cwd, *args):
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _git_output(cwd, *args):
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
