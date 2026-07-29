import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "release_guard.py"


def load_release_guard_module():
    spec = importlib.util.spec_from_file_location("release_guard", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def release_repository(tmp_path: Path) -> dict[str, str | Path]:
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Release Test")
    git(root, "config", "user.email", "release@example.test")

    metadata = root / "pyproject.toml"
    metadata.write_text(
        '[project]\nname = "gigaloom"\nversion = "0.5.1a1"\n',
        encoding="utf-8",
    )
    git(root, "add", "pyproject.toml")
    git(root, "commit", "-m", "historical source")
    historical = git(root, "rev-parse", "HEAD")

    (root / "TARGET").write_text("target history begins\n", encoding="utf-8")
    git(root, "add", "TARGET")
    git(root, "commit", "-m", "target history floor")
    floor = git(root, "rev-parse", "HEAD")

    policy = root / "release-policy.json"
    policy.write_text(
        json.dumps(
            {
                "default_branch": "main",
                "distribution": "gigaloom",
                "first_target_release": {
                    "history_floor": floor,
                    "tag": "gigaloom-v0.5.1a1",
                    "version": "0.5.1a1",
                },
                "repository": "krakenalt/gigaloom",
                "tag_prefix": "gigaloom-v",
            }
        ),
        encoding="utf-8",
    )
    git(root, "add", "release-policy.json")
    git(root, "commit", "-m", "release policy")
    commit = git(root, "rev-parse", "HEAD")
    tag = "gigaloom-v0.5.1a1"
    git(root, "tag", tag)
    return {
        "commit": commit,
        "floor": floor,
        "historical": historical,
        "metadata": metadata,
        "policy": policy,
        "root": root,
        "tag": tag,
    }


def validate(module, repository_data, **overrides):
    values = {
        "root": repository_data["root"],
        "policy_path": repository_data["policy"],
        "metadata_path": repository_data["metadata"],
        "event_name": "release",
        "repository": "krakenalt/gigaloom",
        "ref": f"refs/tags/{repository_data['tag']}",
        "commit": repository_data["commit"],
        "release_tag": repository_data["tag"],
        "release_target": "main",
        "main_ref": "main",
    }
    values.update(overrides)
    return module.validate_release(**values)


def test_release_guard_accepts_exact_release_and_main_manual_run(tmp_path: Path):
    module = load_release_guard_module()
    repository = release_repository(tmp_path)

    assert validate(module, repository) == {
        "mode": "publish",
        "tag": "gigaloom-v0.5.1a1",
        "version": "0.5.1a1",
    }
    assert (
        validate(
            module,
            repository,
            event_name="workflow_dispatch",
            ref="refs/heads/main",
            release_tag="",
            release_target="",
        )["mode"]
        == "manual"
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"repository": "ai-forever/gpt2giga"}, "is not the target"),
        ({"release_tag": "v0.5.1a1"}, "must equal"),
        ({"release_target": "archive"}, "default branch"),
        (
            {
                "event_name": "workflow_dispatch",
                "ref": "refs/heads/release/test",
                "release_tag": "",
                "release_target": "",
            },
            "must run from refs/heads/main",
        ),
    ],
)
def test_release_guard_rejects_wrong_identity(
    tmp_path: Path,
    overrides: dict[str, str],
    message: str,
):
    module = load_release_guard_module()
    repository = release_repository(tmp_path)

    with pytest.raises(module.ReleaseGuardError, match=message):
        validate(module, repository, **overrides)


def test_release_guard_rejects_pre_target_history(tmp_path: Path):
    module = load_release_guard_module()
    repository = release_repository(tmp_path)

    with pytest.raises(module.ReleaseGuardError, match="is not an ancestor"):
        validate(module, repository, commit=repository["historical"])


def test_release_guard_rejects_version_before_first_target_release(tmp_path: Path):
    module = load_release_guard_module()
    repository = release_repository(tmp_path)
    repository["metadata"].write_text(
        '[project]\nname = "gigaloom"\nversion = "0.5.0a1"\n',
        encoding="utf-8",
    )

    with pytest.raises(module.ReleaseGuardError, match="predates"):
        validate(module, repository)
