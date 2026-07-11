import hashlib
import shutil
import subprocess

import pytest

from gpt2giga_harness.project import (
    DEFAULT_ATTACHMENT_IGNORE,
    DEFAULT_ENABLED_HARNESSES,
    init_project_config,
    load_project_state,
    load_project_config,
    project_config_to_dict,
    project_id_for_root,
    project_state_path,
    project_state_to_dict,
    project_to_dict,
    render_project_preset,
    rendered_project_preset_to_dict,
    resolve_project,
    update_project_state,
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
    assert config.tool_profiles == {}
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
    assert config.editor.command == "code"
    assert config.editor.terminal_command == "auto"
    assert "plan" in config.presets
    assert config.tool_profiles["github"].enabled is False
    assert config.tool_profiles["postgres"].kind == "mcp"
    assert (tmp_path / ".giga" / "prompts" / "plan.md").exists()
    assert (tmp_path / ".giga" / "evals" / "smoke.yaml").exists()


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

[editor]
command = "cursor"
terminal_command = "wezterm"

[tools.github]
enabled = true
title = "GitHub"
kind = "mcp"
description = "Project issue tracker"
harnesses = ["codex-cli", "claude-code"]
command = "github-mcp"

[tools.github.config]
header = "Bearer abcdefghijk"
readonly = true

[presets.ask]
title = "Ask"
harness = "direct-chat"
api_mode = "v2"
mode = "plan"
prompt = "Ask {{project_name}}: {{user_prompt}}"

[presets.fix_tests]
title = "Fix tests"
harness = "codex-cli"
api_mode = "v2"
mode = "edit"
invocation_mode = "headless"
workspace_policy = "worktree"
prompt_file = ".giga/prompts/fix.md"
selected_files = ["tests/test_demo.py"]

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
    assert config.editor.command == "cursor"
    assert config.editor.terminal_command == "wezterm"
    assert config.presets["ask"].harness == "direct-chat"
    assert config.presets["ask"].api_mode.value == "v2"
    assert config.presets["ask"].prompt == "Ask {{project_name}}: {{user_prompt}}"
    assert config.presets["fix_tests"].mode == "edit"
    assert config.presets["fix_tests"].invocation_mode.value == "headless"
    assert config.presets["fix_tests"].workspace_policy == "worktree"
    assert config.presets["fix_tests"].prompt_file == ".giga/prompts/fix.md"
    assert config.presets["fix_tests"].selected_files == ("tests/test_demo.py",)
    assert config.tool_profiles["github"].enabled is True
    assert config.tool_profiles["github"].title == "GitHub"
    assert config.tool_profiles["github"].kind == "mcp"
    assert config.tool_profiles["github"].harnesses == ("codex-cli", "claude-code")
    assert config.tool_profiles["github"].config["command"] == "github-mcp"
    assert config.tool_profiles["github"].config["readonly"] is True
    assert config.attachments.max_file_mb == 10
    assert config.attachments.max_total_mb_per_run == 20
    assert config.attachments.allow_images is False
    assert config.attachments.allow_binary is True
    assert config.attachments.respect_gitignore is False
    assert config.attachments.ignore == (".env", "private/**")
    config_payload = project_config_to_dict(config)
    assert config_payload["defaults"]["api_mode"] == "v1"
    assert config_payload["editor"]["terminal_command"] == "wezterm"
    assert config_payload["tools"]["github"]["config"]["header"] == "<redacted>"


def test_render_project_preset_applies_safe_template_variables(tmp_path):
    config_path = tmp_path / ".giga" / "harness.toml"
    prompt_path = tmp_path / ".giga" / "prompts" / "fix.md"
    prompt_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[project]
name = "render-demo"

[presets.fix_tests]
title = "Fix tests"
harness = "codex-cli"
mode = "edit"
workspace_policy = "worktree"
prompt_file = ".giga/prompts/fix.md"
selected_files = ["tests/test_project.py"]
""",
        encoding="utf-8",
    )
    prompt_path.write_text(
        "Project {{ project_name }} on ${branch}\n"
        "Files:\n{{selected_files}}\n"
        "Task: $user_prompt\n"
        "Diff:\n{{last_run_diff}}\n",
        encoding="utf-8",
    )
    project = resolve_project(tmp_path, data_dir=tmp_path / "data")
    config = load_project_config(tmp_path)

    rendered = render_project_preset(
        project,
        config,
        "fix_tests",
        user_prompt="repair failing tests",
        selected_files=("packages/gpt2giga-harness/src/gpt2giga_harness/project.py",),
        last_run_diff="diff --git a/x b/x",
    )
    payload = rendered_project_preset_to_dict(rendered)

    assert rendered.workspace_policy == "worktree"
    assert rendered.selected_files == (
        "tests/test_project.py",
        "packages/gpt2giga-harness/src/gpt2giga_harness/project.py",
    )
    assert "Project render-demo" in rendered.prompt
    assert "repair failing tests" in rendered.prompt
    assert "diff --git a/x b/x" in rendered.prompt
    assert payload["run"]["workspace_policy"] == "worktree"
    assert payload["variables"]["selected_files"] == [
        "tests/test_project.py",
        "packages/gpt2giga-harness/src/gpt2giga_harness/project.py",
    ]


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


def test_load_project_config_rejects_secret_tool_keys(tmp_path):
    config_path = tmp_path / ".giga" / "harness.toml"
    config_path.parent.mkdir()
    config_path.write_text(
        """
[tools.github]
enabled = true
access_token = "secret"
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


def test_project_state_persists_mutable_cockpit_defaults(tmp_path):
    project = resolve_project(tmp_path, data_dir=tmp_path / "data")

    empty = load_project_state(project)
    assert project_state_to_dict(empty) == {
        "last_harness": None,
        "last_model": None,
        "last_api_mode": None,
        "last_run_mode": None,
        "last_invocation_mode": None,
        "last_selected_session": None,
        "trusted": None,
    }

    state = update_project_state(
        project,
        {
            "last_harness": "codex-cli",
            "last_model": "GigaChat-2-Max",
            "last_api_mode": "v1",
            "last_run_mode": "edit",
            "last_invocation_mode": "native",
            "last_selected_session": "sess_demo",
            "trusted": True,
            "ignored": "value",
        },
    )

    assert project_state_path(project).exists()
    assert project_state_to_dict(state) == {
        "last_harness": "codex-cli",
        "last_model": "GigaChat-2-Max",
        "last_api_mode": "v1",
        "last_run_mode": "edit",
        "last_invocation_mode": "native",
        "last_selected_session": "sess_demo",
        "trusted": True,
    }
    assert load_project_state(project) == state


def test_project_state_tolerates_corrupt_json(tmp_path):
    project = resolve_project(tmp_path, data_dir=tmp_path / "data")
    path = project_state_path(project)
    path.parent.mkdir(parents=True)
    path.write_text("not json", encoding="utf-8")

    assert project_state_to_dict(load_project_state(project))["last_harness"] is None
