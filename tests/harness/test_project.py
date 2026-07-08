import hashlib
import shutil
import subprocess

import pytest

from gpt2giga.harness.project import (
    DEFAULT_ATTACHMENT_IGNORE,
    DEFAULT_ENABLED_HARNESSES,
    init_project_config,
    load_project_config,
    project_config_to_dict,
    project_id_for_root,
    project_to_dict,
    resolve_project,
)


def test_resolve_project_uses_plain_workspace_root(tmp_path):
    workspace = tmp_path / "plain"
    data_dir = tmp_path / "data"
    workspace.mkdir()

    project = resolve_project(workspace, data_dir=data_dir)

    expected_digest = hashlib.sha256(str(workspace.resolve()).encode()).hexdigest()
    assert project.id == f"proj_{expected_digest[:16]}"
    assert project.root == str(workspace.resolve())
    assert project.name == "plain"
    assert project.git_root is None
    assert project.git_branch is None
    assert project.is_git_repo is False
    assert project.dirty_summary == {}
    assert project.config_path is None
    assert project.state_dir == str(data_dir / "projects" / project.id)
    assert project_to_dict(project)["id"] == project.id


def test_project_id_uses_normalized_absolute_root(tmp_path, monkeypatch):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    monkeypatch.chdir(tmp_path)

    assert project_id_for_root("repo") == project_id_for_root(workspace.resolve())


def test_resolve_project_prefers_git_root_and_reports_branch(tmp_path):
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not installed")
    repo = tmp_path / "repo"
    nested = repo / "src" / "pkg"
    nested.mkdir(parents=True)
    subprocess.run((git, "init", "-b", "main"), cwd=repo, check=True)
    (repo / "tracked.txt").write_text("hello", encoding="utf-8")

    project = resolve_project(nested, data_dir=tmp_path / "data")

    assert project.root == str(repo.resolve())
    assert project.git_root == str(repo.resolve())
    assert project.git_branch == "main"
    assert project.is_git_repo is True
    assert project.dirty_summary["added"] == 1


def test_load_project_config_returns_defaults_when_missing(tmp_path):
    config = load_project_config(tmp_path)

    assert config.exists is False
    assert config.project_name is None
    assert config.defaults.harness == "codex-cli"
    assert config.defaults.model == "GigaChat-2-Max"
    assert config.defaults.api_mode.value == "v2"
    assert config.defaults.mode == "plan"
    assert config.enabled_harnesses == DEFAULT_ENABLED_HARNESSES
    assert config.attachments.ignore == DEFAULT_ATTACHMENT_IGNORE


def test_init_project_config_writes_non_secret_template(tmp_path):
    config = init_project_config(tmp_path, project_name="demo")
    config_path = tmp_path / ".giga" / "harness.toml"

    assert config.exists is True
    assert config.project_name == "demo"
    assert config_path.exists()
    text = config_path.read_text(encoding="utf-8")
    assert "API_KEY" not in text
    assert "TOKEN" not in text
    assert config.defaults.harness == "codex-cli"
    assert "plan" in config.presets


def test_load_project_config_parses_defaults_presets_and_attachments(tmp_path):
    config_path = tmp_path / ".giga" / "harness.toml"
    config_path.parent.mkdir()
    config_path.write_text(
        """
[project]
name = "custom"

[defaults]
harness = "echo"
model = "GigaChat"
api_mode = "v1"
mode = "read"

[harnesses]
enabled = ["echo", "direct-chat"]

[presets.ask]
title = "Ask"
harness = "direct-chat"
api_mode = "v2"
mode = "plan"

[attachments]
max_file_mb = 10
max_total_mb_per_run = 20
allow_images = false
allow_documents = true
allow_binary = true
respect_gitignore = false
ignore = [
  ".env",
  "private/**",
]
""",
        encoding="utf-8",
    )

    config = load_project_config(tmp_path)

    assert config.exists is True
    assert config.project_name == "custom"
    assert config.defaults.harness == "echo"
    assert config.defaults.api_mode.value == "v1"
    assert config.defaults.mode == "read"
    assert config.enabled_harnesses == ("echo", "direct-chat")
    assert config.presets["ask"].harness == "direct-chat"
    assert config.presets["ask"].api_mode.value == "v2"
    assert config.attachments.max_file_mb == 10
    assert config.attachments.max_total_mb_per_run == 20
    assert config.attachments.allow_images is False
    assert config.attachments.allow_binary is True
    assert config.attachments.respect_gitignore is False
    assert config.attachments.ignore == (".env", "private/**")
    assert project_config_to_dict(config)["defaults"]["api_mode"] == "v1"


def test_load_project_config_rejects_secret_keys(tmp_path):
    config_path = tmp_path / ".giga" / "harness.toml"
    config_path.parent.mkdir()
    config_path.write_text(
        """
[defaults]
api_key = "sk-test-secret"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="secret key"):
        load_project_config(tmp_path)


def test_resolve_project_uses_configured_project_name(tmp_path):
    init_project_config(tmp_path, project_name="configured-name")

    project = resolve_project(tmp_path, data_dir=tmp_path / "data")

    assert project.name == "configured-name"
    assert project.config_path == str(tmp_path / ".giga" / "harness.toml")
