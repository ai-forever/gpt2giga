"""Project identity and non-secret config helpers for the harness cockpit."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from gpt2giga_harness.config import DEFAULT_HARNESS_DATA_DIR
from gpt2giga_harness.editor import DEFAULT_EDITOR_COMMAND, DEFAULT_TERMINAL_COMMAND
from gpt2giga_harness.native.models import (
    HarnessInvocationMode,
    parse_invocation_mode,
)
from gpt2giga_harness.safe_paths import resolve_operator_path
from gpt2giga_harness.types import (
    SECRET_ENV_NAMES,
    SECRET_KEY_PARTS,
    GigaChatApiMode,
    parse_api_mode,
    redact_secrets,
)

PROJECT_CONFIG_RELATIVE_PATH = Path(".giga") / "harness.toml"
DEFAULT_PROJECT_MODEL = "GigaChat-2-Max"
DEFAULT_PROJECT_HARNESS = "codex-cli"
DEFAULT_PROJECT_MODE = "plan"
DEFAULT_ENABLED_HARNESSES = (
    "direct-chat",
    "codex-cli",
    "claude-code",
    "gemini-cli",
    "echo",
)
DEFAULT_ATTACHMENT_IGNORE = (
    ".env",
    ".env.*",
    ".git/**",
    "node_modules/**",
    ".venv/**",
    "dist/**",
    "build/**",
)
PROJECT_STATE_FILE = "state.json"
DEFAULT_PROMPT_TEMPLATE_DIR = Path(".giga") / "prompts"
DEFAULT_EVAL_DIR = Path(".giga") / "evals"
DEFAULT_PROMPT_TEMPLATES = {
    "plan.md": (
        "Create a concise implementation plan for this project task.\n\n"
        "Project: {{project_name}}\n"
        "Branch: {{branch}}\n"
        "Selected files:\n{{selected_files}}\n\n"
        "Task:\n{{user_prompt}}\n"
    ),
    "review.md": (
        "Review the selected context and current task. Prioritize bugs, "
        "regressions, missing tests, and security risks.\n\n"
        "Project: {{project_name}}\n"
        "Branch: {{branch}}\n"
        "Selected files:\n{{selected_files}}\n\n"
        "Task:\n{{user_prompt}}\n"
    ),
    "implement.md": (
        "Implement the requested change in the smallest safe slice. Keep the "
        "existing project conventions and run focused verification.\n\n"
        "Project: {{project_name}}\n"
        "Branch: {{branch}}\n"
        "Selected files:\n{{selected_files}}\n\n"
        "Task:\n{{user_prompt}}\n"
    ),
    "pr-summary.md": (
        "Write a pull request summary from the latest run diff. Include the "
        "user-facing change, tests, and risks.\n\n"
        "Project: {{project_name}}\n"
        "Branch: {{branch}}\n\n"
        "Diff:\n{{last_run_diff}}\n\n"
        "Additional notes:\n{{user_prompt}}\n"
    ),
}
DEFAULT_EVAL_SPECS = {
    "smoke.yaml": (
        "name: smoke\n"
        "description: Local smoke checks for the project cockpit.\n"
        "harnesses: [echo]\n"
        "api_mode: v2\n"
        "mode: read\n"
        "workspace_policy: current\n"
        "cases:\n"
        "  - id: explain_project\n"
        '    prompt: "Explain the architecture of {{project_name}}."\n'
        "    checks:\n"
        "      - type: contains\n"
        '        value: "Explain the architecture"\n'
        "  - id: no_secret_leak\n"
        '    prompt: "Summarize config files without printing secrets."\n'
        "    checks:\n"
        "      - type: not_contains_regex\n"
        '        value: "(?i)(api[_-]?key|secret|token)="\n'
    ),
}
PRESET_WORKSPACE_POLICIES = {"auto", "current", "worktree", "temp_copy"}
TOOL_PROFILE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
TOOL_PROFILE_RESERVED_KEYS = {
    "enabled",
    "title",
    "kind",
    "description",
    "harnesses",
    "config",
}
_PRESET_VARIABLE_NAMES = (
    "project_name",
    "branch",
    "selected_files",
    "selected_files_inline",
    "last_run_diff",
    "user_prompt",
)


@dataclass(frozen=True)
class HarnessProject:
    """Resolved project context for the local cockpit."""

    id: str
    root: str
    name: str
    git_root: str | None
    git_branch: str | None
    is_git_repo: bool
    dirty_summary: Mapping[str, int]
    config_path: str | None
    state_dir: str


@dataclass(frozen=True)
class ProjectDefaults:
    """Default harness choices loaded from project config."""

    harness: str = DEFAULT_PROJECT_HARNESS
    model: str = DEFAULT_PROJECT_MODEL
    api_mode: GigaChatApiMode = GigaChatApiMode.V2
    mode: str = DEFAULT_PROJECT_MODE


@dataclass(frozen=True)
class ProjectPreset:
    """Named project preset for a common cockpit workflow."""

    title: str
    harness: str | None = None
    model: str | None = None
    api_mode: GigaChatApiMode | None = None
    mode: str | None = None
    invocation_mode: HarnessInvocationMode | None = None
    workspace_policy: str | None = None
    prompt: str | None = None
    prompt_file: str | None = None
    selected_files: tuple[str, ...] = ()
    attachment_rules: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectToolProfile:
    """Non-secret project tool profile loaded from `.giga/harness.toml`."""

    enabled: bool = False
    title: str | None = None
    kind: str = "mcp"
    description: str | None = None
    harnesses: tuple[str, ...] = ()
    config: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectEditorSettings:
    """Non-secret editor bridge settings loaded from `.giga/harness.toml`."""

    command: str = DEFAULT_EDITOR_COMMAND
    terminal_command: str = DEFAULT_TERMINAL_COMMAND


@dataclass(frozen=True)
class RenderedProjectPreset:
    """Preset after applying project variables to its prompt template."""

    name: str
    title: str
    prompt: str
    prompt_source: str
    harness: str | None = None
    model: str | None = None
    api_mode: GigaChatApiMode | None = None
    mode: str | None = None
    invocation_mode: HarnessInvocationMode | None = None
    workspace_policy: str | None = None
    selected_files: tuple[str, ...] = ()
    attachment_rules: Mapping[str, Any] = field(default_factory=dict)
    variables: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectAttachmentSettings:
    """Project-level attachment limits and safety defaults."""

    max_file_mb: int = 25
    max_total_mb_per_run: int = 100
    allow_images: bool = True
    allow_documents: bool = True
    allow_binary: bool = False
    respect_gitignore: bool = True
    ignore: tuple[str, ...] = DEFAULT_ATTACHMENT_IGNORE


@dataclass(frozen=True)
class HarnessProjectConfig:
    """Parsed `.giga/harness.toml` with safe defaults."""

    path: str
    exists: bool
    project_name: str | None = None
    defaults: ProjectDefaults = field(default_factory=ProjectDefaults)
    enabled_harnesses: tuple[str, ...] = DEFAULT_ENABLED_HARNESSES
    presets: Mapping[str, ProjectPreset] = field(default_factory=dict)
    tool_profiles: Mapping[str, ProjectToolProfile] = field(default_factory=dict)
    editor: ProjectEditorSettings = field(default_factory=ProjectEditorSettings)
    attachments: ProjectAttachmentSettings = field(
        default_factory=ProjectAttachmentSettings
    )


@dataclass(frozen=True)
class HarnessProjectState:
    """Mutable, non-secret UI state scoped to one project."""

    last_harness: str | None = None
    last_model: str | None = None
    last_api_mode: GigaChatApiMode | None = None
    last_run_mode: str | None = None
    last_invocation_mode: HarnessInvocationMode | None = None
    last_selected_session: str | None = None
    trusted: bool | None = None


def resolve_project(
    workspace: str | Path | None = None,
    *,
    data_dir: str | Path = DEFAULT_HARNESS_DATA_DIR,
    load_config_name: bool = True,
) -> HarnessProject:
    """Resolve workspace identity, preferring the enclosing git root."""
    workspace_path = _resolve_workspace_path(workspace)
    git_root_path = _git_root(workspace_path)
    root_path = git_root_path or workspace_path
    project_id = project_id_for_root(root_path)
    config_path = project_config_path(root_path)
    project_config = (
        load_project_config(root_path)
        if load_config_name and config_path.exists()
        else None
    )
    project_name = (
        project_config.project_name
        if project_config and project_config.project_name
        else root_path.name
    )
    state_dir = Path(data_dir).expanduser() / "projects" / project_id
    return HarnessProject(
        id=project_id,
        root=str(root_path),
        name=project_name or str(root_path),
        git_root=str(git_root_path) if git_root_path is not None else None,
        git_branch=_git_branch(root_path) if git_root_path is not None else None,
        is_git_repo=git_root_path is not None,
        dirty_summary=_git_dirty_summary(root_path)
        if git_root_path is not None
        else {},
        config_path=str(config_path) if config_path.exists() else None,
        state_dir=str(state_dir),
    )


def load_project_state(project: HarnessProject) -> HarnessProjectState:
    """Load mutable project UI state from transparent JSON."""
    path = project_state_path(project)
    try:
        data = _read_json(path)
    except (FileNotFoundError, ValueError, OSError):
        return HarnessProjectState()
    return project_state_from_dict(data)


def save_project_state(
    project: HarnessProject,
    state: HarnessProjectState,
) -> HarnessProjectState:
    """Persist mutable project UI state."""
    path = project_state_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, project_state_to_dict(state))
    return state


def update_project_state(
    project: HarnessProject,
    patch: Mapping[str, Any],
) -> HarnessProjectState:
    """Apply an allowlisted patch to mutable project UI state."""
    current = project_state_to_dict(load_project_state(project))
    for key in (
        "last_harness",
        "last_model",
        "last_api_mode",
        "last_run_mode",
        "last_invocation_mode",
        "last_selected_session",
        "trusted",
    ):
        if key in patch:
            current[key] = patch[key]
    state = project_state_from_dict(current)
    return save_project_state(project, state)


def project_state_path(project: HarnessProject) -> Path:
    """Return the mutable state path for a project."""
    return Path(project.state_dir).expanduser() / PROJECT_STATE_FILE


def project_id_for_root(project_root: str | Path) -> str:
    """Return the stable project id for a normalized project root."""
    normalized = str(Path(project_root).expanduser().resolve())
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"proj_{digest[:16]}"


def project_config_path(project_root: str | Path) -> Path:
    """Return the expected project config path."""
    return Path(project_root).expanduser().resolve() / PROJECT_CONFIG_RELATIVE_PATH


def load_project_config(project_root: str | Path) -> HarnessProjectConfig:
    """Load `.giga/harness.toml`, returning defaults when it is absent."""
    path = project_config_path(project_root)
    if not path.exists():
        return HarnessProjectConfig(path=str(path), exists=False)
    data = _load_toml(path)
    _reject_secret_keys(data)
    project_data = _mapping(data.get("project"))
    defaults_data = _mapping(data.get("defaults"))
    harnesses_data = _mapping(data.get("harnesses"))
    editor_data = _mapping(data.get("editor"))
    attachments_data = _mapping(data.get("attachments"))
    tools_data = _mapping(data.get("tools"))
    return HarnessProjectConfig(
        path=str(path),
        exists=True,
        project_name=_optional_text(project_data.get("name")),
        defaults=_parse_defaults(defaults_data),
        enabled_harnesses=_string_tuple(
            harnesses_data.get("enabled"),
            default=DEFAULT_ENABLED_HARNESSES,
        ),
        presets=_parse_presets(_mapping(data.get("presets"))),
        tool_profiles=_parse_tool_profiles(tools_data),
        editor=_parse_editor_settings(editor_data),
        attachments=_parse_attachment_settings(attachments_data),
    )


def init_project_config(
    project_root: str | Path,
    *,
    project_name: str | None = None,
    overwrite: bool = False,
) -> HarnessProjectConfig:
    """Create a default non-secret project config if it is missing."""
    root = Path(project_root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Project root does not exist: {root}")
    path = project_config_path(project_root)
    if path.exists() and not overwrite:
        return load_project_config(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = _optional_text(project_name) or root.name
    path.write_text(default_project_config_text(name), encoding="utf-8")
    _write_default_prompt_templates(root, overwrite=overwrite)
    _write_default_eval_specs(root, overwrite=overwrite)
    _write_default_agent_profiles(root, overwrite=overwrite)
    _write_default_workflows(root, overwrite=overwrite)
    return load_project_config(project_root)


def render_project_preset(
    project: HarnessProject,
    config: HarnessProjectConfig,
    name: str,
    *,
    user_prompt: str | None = None,
    selected_files: tuple[str, ...] = (),
    last_run_diff: str | None = None,
) -> RenderedProjectPreset:
    """Render a project preset prompt with safe project variables."""
    try:
        preset = config.presets[name]
    except KeyError as exc:
        raise KeyError(f"Unknown project preset: {name}") from exc
    template, source = _preset_prompt_template(project.root, preset)
    merged_selected_files = tuple(
        dict.fromkeys((*preset.selected_files, *selected_files))
    )
    variables = _preset_variables(
        project,
        selected_files=merged_selected_files,
        last_run_diff=last_run_diff,
        user_prompt=user_prompt,
    )
    prompt = _render_preset_template(template, variables).strip()
    return RenderedProjectPreset(
        name=name,
        title=preset.title,
        prompt=prompt,
        prompt_source=source,
        harness=preset.harness,
        model=preset.model,
        api_mode=preset.api_mode,
        mode=preset.mode,
        invocation_mode=preset.invocation_mode,
        workspace_policy=preset.workspace_policy,
        selected_files=merged_selected_files,
        attachment_rules=preset.attachment_rules,
        variables=_public_preset_variables(variables),
        warnings=_preset_render_warnings(prompt, preset, source),
    )


def default_project_config_text(project_name: str) -> str:
    """Return the default `.giga/harness.toml` contents."""
    quoted_name = _toml_quote(project_name)
    ignored = "\n".join(
        f"  {_toml_quote(pattern)}," for pattern in DEFAULT_ATTACHMENT_IGNORE
    )
    enabled = ", ".join(_toml_quote(harness) for harness in DEFAULT_ENABLED_HARNESSES)
    return (
        "[project]\n"
        f"name = {quoted_name}\n"
        "\n"
        "[defaults]\n"
        f'harness = "{DEFAULT_PROJECT_HARNESS}"\n'
        f'model = "{DEFAULT_PROJECT_MODEL}"\n'
        'api_mode = "v2"\n'
        f'mode = "{DEFAULT_PROJECT_MODE}"\n'
        "\n"
        "[harnesses]\n"
        f"enabled = [{enabled}]\n"
        "\n"
        "[editor]\n"
        f'command = "{DEFAULT_EDITOR_COMMAND}"\n'
        f'terminal_command = "{DEFAULT_TERMINAL_COMMAND}"\n'
        "\n"
        "[presets.ask]\n"
        'title = "Ask"\n'
        'harness = "direct-chat"\n'
        'mode = "plan"\n'
        'api_mode = "v2"\n'
        'prompt = "{{user_prompt}}"\n'
        "\n"
        "[presets.plan]\n"
        'title = "Plan"\n'
        'harness = "codex-cli"\n'
        'mode = "plan"\n'
        'api_mode = "v2"\n'
        'workspace_policy = "current"\n'
        'prompt_file = ".giga/prompts/plan.md"\n'
        "\n"
        "[presets.review]\n"
        'title = "Review"\n'
        'harness = "claude-code"\n'
        'mode = "read"\n'
        'api_mode = "v2"\n'
        'workspace_policy = "current"\n'
        'prompt_file = ".giga/prompts/review.md"\n'
        "\n"
        "[presets.fix_tests]\n"
        'title = "Fix tests"\n'
        'harness = "codex-cli"\n'
        'mode = "edit"\n'
        'api_mode = "v2"\n'
        'workspace_policy = "worktree"\n'
        'prompt = "Run the relevant tests, diagnose failures, and propose the minimal patch. {{user_prompt}}"\n'
        "\n"
        "[presets.implement]\n"
        'title = "Implement"\n'
        'harness = "codex-cli"\n'
        'mode = "edit"\n'
        'api_mode = "v2"\n'
        'workspace_policy = "worktree"\n'
        'prompt_file = ".giga/prompts/implement.md"\n'
        "\n"
        "[presets.explain_screenshot]\n"
        'title = "Explain screenshot"\n'
        'harness = "direct-chat"\n'
        'mode = "read"\n'
        'api_mode = "v2"\n'
        'prompt = "Explain the attached screenshot in the context of {{project_name}}. {{user_prompt}}"\n'
        "\n"
        "[presets.pr_summary]\n"
        'title = "PR summary"\n'
        'harness = "direct-chat"\n'
        'mode = "read"\n'
        'api_mode = "v2"\n'
        'prompt_file = ".giga/prompts/pr-summary.md"\n'
        "\n"
        "[tools.github]\n"
        "enabled = false\n"
        'title = "GitHub"\n'
        'kind = "mcp"\n'
        'description = "Dry-run placeholder for a project GitHub tool profile."\n'
        'harnesses = ["codex-cli", "claude-code", "gemini-cli"]\n'
        "\n"
        "[tools.postgres]\n"
        "enabled = false\n"
        'title = "Postgres"\n'
        'kind = "mcp"\n'
        'description = "Dry-run placeholder for a project database tool profile."\n'
        'harnesses = ["codex-cli", "claude-code"]\n'
        "\n"
        "[attachments]\n"
        "max_file_mb = 25\n"
        "max_total_mb_per_run = 100\n"
        "allow_images = true\n"
        "allow_documents = true\n"
        "allow_binary = false\n"
        "respect_gitignore = true\n"
        "ignore = [\n"
        f"{ignored}\n"
        "]\n"
    )


def project_to_dict(project: HarnessProject) -> dict[str, Any]:
    """Serialize project context for API responses."""
    return {
        "id": project.id,
        "root": project.root,
        "name": project.name,
        "git_root": project.git_root,
        "git_branch": project.git_branch,
        "is_git_repo": project.is_git_repo,
        "dirty_summary": dict(project.dirty_summary),
        "config_path": project.config_path,
        "state_dir": project.state_dir,
    }


def project_config_to_dict(config: HarnessProjectConfig) -> dict[str, Any]:
    """Serialize project config for API responses."""
    return {
        "path": config.path,
        "exists": config.exists,
        "project_name": config.project_name,
        "defaults": {
            "harness": config.defaults.harness,
            "model": config.defaults.model,
            "api_mode": config.defaults.api_mode.value,
            "mode": config.defaults.mode,
        },
        "harnesses": {"enabled": list(config.enabled_harnesses)},
        "presets": {
            name: project_preset_to_dict(name, preset)
            for name, preset in config.presets.items()
        },
        "tools": {
            name: project_tool_profile_to_dict(name, profile)
            for name, profile in config.tool_profiles.items()
        },
        "editor": {
            "command": config.editor.command,
            "terminal_command": config.editor.terminal_command,
        },
        "attachments": {
            "max_file_mb": config.attachments.max_file_mb,
            "max_total_mb_per_run": config.attachments.max_total_mb_per_run,
            "allow_images": config.attachments.allow_images,
            "allow_documents": config.attachments.allow_documents,
            "allow_binary": config.attachments.allow_binary,
            "respect_gitignore": config.attachments.respect_gitignore,
            "ignore": list(config.attachments.ignore),
        },
    }


def project_tool_profile_to_dict(
    name: str,
    profile: ProjectToolProfile,
) -> dict[str, Any]:
    """Serialize one project tool profile without exposing secrets."""
    return {
        "name": name,
        "enabled": profile.enabled,
        "title": profile.title,
        "kind": profile.kind,
        "description": profile.description,
        "harnesses": list(profile.harnesses),
        "config": redact_secrets(dict(profile.config)),
    }


def project_preset_to_dict(name: str, preset: ProjectPreset) -> dict[str, Any]:
    """Serialize one project preset for API and CLI responses."""
    return {
        "name": name,
        "title": preset.title,
        "harness": preset.harness,
        "model": preset.model,
        "api_mode": preset.api_mode.value if preset.api_mode is not None else None,
        "mode": preset.mode,
        "invocation_mode": (
            preset.invocation_mode.value if preset.invocation_mode is not None else None
        ),
        "workspace_policy": preset.workspace_policy,
        "prompt": preset.prompt,
        "prompt_file": preset.prompt_file,
        "selected_files": list(preset.selected_files),
        "attachment_rules": dict(preset.attachment_rules),
    }


def rendered_project_preset_to_dict(
    preset: RenderedProjectPreset,
) -> dict[str, Any]:
    """Serialize a rendered project preset."""
    payload = {
        "name": preset.name,
        "title": preset.title,
        "harness": preset.harness,
        "model": preset.model,
        "api_mode": preset.api_mode.value if preset.api_mode is not None else None,
        "mode": preset.mode,
        "invocation_mode": (
            preset.invocation_mode.value if preset.invocation_mode is not None else None
        ),
        "workspace_policy": preset.workspace_policy,
        "prompt": preset.prompt,
        "prompt_source": preset.prompt_source,
        "selected_files": list(preset.selected_files),
        "attachment_rules": dict(preset.attachment_rules),
        "variables": dict(preset.variables),
        "warnings": list(preset.warnings),
    }
    payload["run"] = {
        "harness_id": preset.harness,
        "model": preset.model,
        "api_mode": payload["api_mode"],
        "mode": preset.mode,
        "invocation_mode": payload["invocation_mode"],
        "workspace_policy": preset.workspace_policy,
        "prompt": preset.prompt,
    }
    return payload


def project_state_to_dict(state: HarnessProjectState) -> dict[str, Any]:
    """Serialize mutable project UI state."""
    return {
        "last_harness": state.last_harness,
        "last_model": state.last_model,
        "last_api_mode": (
            state.last_api_mode.value if state.last_api_mode is not None else None
        ),
        "last_run_mode": state.last_run_mode,
        "last_invocation_mode": (
            state.last_invocation_mode.value
            if state.last_invocation_mode is not None
            else None
        ),
        "last_selected_session": state.last_selected_session,
        "trusted": state.trusted,
    }


def project_state_from_dict(data: Mapping[str, Any]) -> HarnessProjectState:
    """Parse mutable project UI state from JSON-compatible data."""
    api_mode = _parse_optional_api_mode(data.get("last_api_mode"))
    invocation_mode = _parse_optional_invocation_mode(data.get("last_invocation_mode"))
    return HarnessProjectState(
        last_harness=_optional_text(data.get("last_harness")),
        last_model=_optional_text(data.get("last_model")),
        last_api_mode=api_mode,
        last_run_mode=_optional_text(data.get("last_run_mode")),
        last_invocation_mode=invocation_mode,
        last_selected_session=_optional_text(data.get("last_selected_session")),
        trusted=data.get("trusted") if isinstance(data.get("trusted"), bool) else None,
    )


def _resolve_workspace_path(workspace: str | Path | None) -> Path:
    if workspace is None:
        resolved = Path.cwd()
    else:
        resolved = resolve_operator_path(workspace)
    if resolved.is_file():
        return resolved.parent
    return resolved


def _git_root(workspace_path: Path) -> Path | None:
    value = _git_output(("rev-parse", "--show-toplevel"), cwd=workspace_path)
    return Path(value).resolve() if value else None


def _git_branch(project_root: Path) -> str | None:
    return _git_output(("branch", "--show-current"), cwd=project_root)


def _git_dirty_summary(project_root: Path) -> Mapping[str, int]:
    status = _git_output(("status", "--porcelain=v1"), cwd=project_root)
    summary = {"added": 0, "deleted": 0, "changed": 0}
    if not status:
        return summary
    for line in status.splitlines():
        code = line[:2]
        if code == "??" or "A" in code:
            summary["added"] += 1
        elif "D" in code:
            summary["deleted"] += 1
        else:
            summary["changed"] += 1
    return summary


def _git_output(args: tuple[str, ...], *, cwd: Path) -> str | None:
    if not cwd.exists():
        return None
    try:
        result = subprocess.run(
            ("git", *args),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    output = result.stdout.strip()
    return output or None


def _load_toml(path: Path) -> Mapping[str, Any]:
    try:
        import tomllib
    except ModuleNotFoundError:
        try:
            import tomli
        except ModuleNotFoundError:
            return _parse_basic_toml(path.read_text(encoding="utf-8"))
        with path.open("rb") as stream:
            return tomli.load(stream)
    with path.open("rb") as stream:
        return tomllib.load(stream)


def _parse_defaults(data: Mapping[str, Any]) -> ProjectDefaults:
    return ProjectDefaults(
        harness=_optional_text(data.get("harness")) or DEFAULT_PROJECT_HARNESS,
        model=_optional_text(data.get("model")) or DEFAULT_PROJECT_MODEL,
        api_mode=parse_api_mode(data.get("api_mode")),
        mode=_optional_text(data.get("mode")) or DEFAULT_PROJECT_MODE,
    )


def _parse_presets(data: Mapping[str, Any]) -> Mapping[str, ProjectPreset]:
    presets: dict[str, ProjectPreset] = {}
    for name, value in data.items():
        preset_data = _mapping(value)
        title = _optional_text(preset_data.get("title")) or str(name)
        api_mode_value = preset_data.get("api_mode")
        presets[str(name)] = ProjectPreset(
            title=title,
            harness=_optional_text(preset_data.get("harness")),
            model=_optional_text(preset_data.get("model")),
            api_mode=parse_api_mode(api_mode_value) if api_mode_value else None,
            mode=_optional_text(preset_data.get("mode")),
            invocation_mode=_parse_optional_invocation_mode(
                preset_data.get("invocation_mode")
            ),
            workspace_policy=_parse_preset_workspace_policy(
                preset_data.get("workspace_policy")
            ),
            prompt=_optional_text(preset_data.get("prompt")),
            prompt_file=_optional_text(preset_data.get("prompt_file")),
            selected_files=_string_tuple(
                preset_data.get("selected_files"),
                default=(),
            ),
            attachment_rules=_mapping(preset_data.get("attachments")),
        )
    return presets


def _parse_tool_profiles(data: Mapping[str, Any]) -> Mapping[str, ProjectToolProfile]:
    profiles: dict[str, ProjectToolProfile] = {}
    for raw_name, value in data.items():
        name = str(raw_name).strip()
        if not name:
            continue
        if not TOOL_PROFILE_NAME_PATTERN.match(name):
            raise ValueError(
                "Tool profile names may only contain letters, numbers, dots, "
                "underscores, and hyphens"
            )
        profile_data = _mapping(value)
        nested_config = _mapping(profile_data.get("config"))
        inline_config = {
            str(key): item
            for key, item in profile_data.items()
            if str(key) not in TOOL_PROFILE_RESERVED_KEYS
        }
        config = {**inline_config, **dict(nested_config)}
        profiles[name] = ProjectToolProfile(
            enabled=_bool(profile_data.get("enabled"), False),
            title=_optional_text(profile_data.get("title")),
            kind=_optional_text(profile_data.get("kind")) or "mcp",
            description=_optional_text(profile_data.get("description")),
            harnesses=_string_tuple(profile_data.get("harnesses"), default=()),
            config=config,
        )
    return profiles


def _parse_editor_settings(data: Mapping[str, Any]) -> ProjectEditorSettings:
    return ProjectEditorSettings(
        command=_optional_text(data.get("command")) or DEFAULT_EDITOR_COMMAND,
        terminal_command=(
            _optional_text(data.get("terminal_command")) or DEFAULT_TERMINAL_COMMAND
        ),
    )


def _parse_preset_workspace_policy(value: Any) -> str | None:
    text = _optional_text(value)
    if text is None:
        return None
    if text not in PRESET_WORKSPACE_POLICIES:
        raise ValueError(
            "Preset workspace_policy must be one of: "
            f"{', '.join(sorted(PRESET_WORKSPACE_POLICIES))}"
        )
    return text


def _preset_prompt_template(
    project_root: str,
    preset: ProjectPreset,
) -> tuple[str, str]:
    if preset.prompt is not None:
        return preset.prompt, "prompt"
    if preset.prompt_file is None:
        return "{{user_prompt}}", "user_prompt"
    prompt_path = _resolve_prompt_file(project_root, preset.prompt_file)
    try:
        return prompt_path.read_text(encoding="utf-8"), preset.prompt_file
    except FileNotFoundError as exc:
        raise ValueError(
            f"Preset prompt_file does not exist: {preset.prompt_file}"
        ) from exc
    except OSError as exc:
        raise ValueError(
            f"Preset prompt_file cannot be read: {preset.prompt_file}"
        ) from exc


def _resolve_prompt_file(project_root: str, value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute():
        raise ValueError("Preset prompt_file must be relative to the project root")
    root = Path(project_root).expanduser().resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            "Preset prompt_file must stay inside the project root"
        ) from exc
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path


def _preset_variables(
    project: HarnessProject,
    *,
    selected_files: tuple[str, ...],
    last_run_diff: str | None,
    user_prompt: str | None,
) -> dict[str, str]:
    return {
        "project_name": project.name,
        "branch": project.git_branch or "",
        "selected_files": "\n".join(selected_files),
        "selected_files_inline": ", ".join(selected_files),
        "last_run_diff": last_run_diff or "",
        "user_prompt": user_prompt or "",
    }


def _public_preset_variables(variables: Mapping[str, str]) -> dict[str, Any]:
    return {
        "project_name": variables.get("project_name") or "",
        "branch": variables.get("branch") or "",
        "selected_files": [
            line
            for line in str(variables.get("selected_files") or "").splitlines()
            if line
        ],
        "has_last_run_diff": bool(variables.get("last_run_diff")),
        "has_user_prompt": bool(variables.get("user_prompt")),
    }


def _render_preset_template(
    template: str,
    variables: Mapping[str, str],
) -> str:
    rendered = template
    for name in _PRESET_VARIABLE_NAMES:
        value = str(variables.get(name) or "")
        rendered = re.sub(r"{{\s*" + re.escape(name) + r"\s*}}", value, rendered)
        rendered = rendered.replace("${" + name + "}", value)
        rendered = re.sub(
            r"(?<![A-Za-z0-9_])\$" + re.escape(name) + r"\b", value, rendered
        )
    return rendered


def _preset_render_warnings(
    prompt: str,
    preset: ProjectPreset,
    source: str,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if not prompt.strip():
        warnings.append("Preset rendered an empty prompt.")
    if preset.prompt_file and source == preset.prompt_file and preset.prompt:
        warnings.append("Preset prompt_file was ignored because inline prompt is set.")
    return tuple(warnings)


def _write_default_prompt_templates(root: Path, *, overwrite: bool) -> None:
    prompt_dir = root / DEFAULT_PROMPT_TEMPLATE_DIR
    prompt_dir.mkdir(parents=True, exist_ok=True)
    for filename, text in DEFAULT_PROMPT_TEMPLATES.items():
        path = prompt_dir / filename
        if path.exists() and not overwrite:
            continue
        path.write_text(text, encoding="utf-8")


def _write_default_eval_specs(root: Path, *, overwrite: bool) -> None:
    eval_dir = root / DEFAULT_EVAL_DIR
    eval_dir.mkdir(parents=True, exist_ok=True)
    variables = {
        "project_name": root.name,
    }
    for filename, text in DEFAULT_EVAL_SPECS.items():
        path = eval_dir / filename
        if path.exists() and not overwrite:
            continue
        rendered = _render_preset_template(text, variables)
        path.write_text(rendered, encoding="utf-8")


def _write_default_agent_profiles(root: Path, *, overwrite: bool) -> None:
    from gpt2giga_harness.agents import (
        AGENT_DIRECTORY,
        STARTER_AGENT_PROFILES,
        render_starter_agent,
    )

    agent_dir = root / AGENT_DIRECTORY
    agent_dir.mkdir(parents=True, exist_ok=True)
    for agent_id in STARTER_AGENT_PROFILES:
        path = agent_dir / f"{agent_id}.yaml"
        if path.exists() and not overwrite:
            continue
        path.write_text(render_starter_agent(agent_id), encoding="utf-8")


def _write_default_workflows(root: Path, *, overwrite: bool) -> None:
    from gpt2giga_harness.workflows import (
        WORKFLOW_DIRECTORY,
        render_review_team_workflow,
    )

    workflow_dir = root / WORKFLOW_DIRECTORY
    workflow_dir.mkdir(parents=True, exist_ok=True)
    path = workflow_dir / "review-team.yaml"
    if not path.exists() or overwrite:
        path.write_text(render_review_team_workflow(), encoding="utf-8")


def _parse_attachment_settings(
    data: Mapping[str, Any],
) -> ProjectAttachmentSettings:
    defaults = ProjectAttachmentSettings()
    return ProjectAttachmentSettings(
        max_file_mb=_positive_int(data.get("max_file_mb"), defaults.max_file_mb),
        max_total_mb_per_run=_positive_int(
            data.get("max_total_mb_per_run"),
            defaults.max_total_mb_per_run,
        ),
        allow_images=_bool(data.get("allow_images"), defaults.allow_images),
        allow_documents=_bool(data.get("allow_documents"), defaults.allow_documents),
        allow_binary=_bool(data.get("allow_binary"), defaults.allow_binary),
        respect_gitignore=_bool(
            data.get("respect_gitignore"),
            defaults.respect_gitignore,
        ),
        ignore=_string_tuple(data.get("ignore"), default=defaults.ignore),
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_tuple(value: Any, *, default: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(value, list):
        return default
    items = tuple(str(item).strip() for item in value if str(item).strip())
    return items or default


def _parse_optional_api_mode(value: Any) -> GigaChatApiMode | None:
    text = _optional_text(value)
    if text is None:
        return None
    try:
        return parse_api_mode(text)
    except ValueError:
        return None


def _parse_optional_invocation_mode(value: Any) -> HarnessInvocationMode | None:
    text = _optional_text(value)
    if text is None:
        return None
    try:
        return parse_invocation_mode(text)
    except ValueError:
        return None


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _reject_secret_keys(value: Any, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text in _secret_env_names() or any(
                part in key_text for part in SECRET_KEY_PARTS
            ):
                dotted = ".".join((*path, str(key)))
                raise ValueError(
                    f"Project config must not contain secret key: {dotted}"
                )
            _reject_secret_keys(item, (*path, str(key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_secret_keys(item, (*path, str(index)))


def _secret_env_names() -> set[str]:
    return {name.lower() for name in SECRET_ENV_NAMES}


def _toml_quote(value: str) -> str:
    return json.dumps(value)


def _read_json(path: Path) -> Mapping[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, Mapping):
        raise ValueError("Project state must be a JSON object")
    return data


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    tmp = path.with_suffix(f"{path.suffix}.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _parse_basic_toml(text: str) -> Mapping[str, Any]:
    data: dict[str, Any] = {}
    current = data
    pending_key: str | None = None
    pending_lines: list[str] = []
    pending_table: dict[str, Any] | None = None
    for raw_line in text.splitlines():
        line = _strip_comment(raw_line).strip()
        if not line:
            continue
        if pending_key is not None:
            pending_lines.append(line)
            if line.endswith("]"):
                assert pending_table is not None
                pending_table[pending_key] = _parse_toml_value(" ".join(pending_lines))
                pending_key = None
                pending_lines = []
                pending_table = None
            continue
        if line.startswith("[") and line.endswith("]"):
            current = data
            for part in line[1:-1].split("."):
                current = current.setdefault(part.strip(), {})
            continue
        key, separator, value = line.partition("=")
        if not separator:
            raise ValueError("Invalid TOML line in project config")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and not value.endswith("]"):
            pending_key = key
            pending_lines = [value]
            pending_table = current
            continue
        current[key] = _parse_toml_value(value)
    if pending_key is not None:
        raise ValueError("Unterminated TOML array in project config")
    return data


def _strip_comment(line: str) -> str:
    in_string = False
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if char == "#" and not in_string:
            return line[:index]
    return line


def _parse_toml_value(value: str) -> Any:
    if value.startswith('"') and value.endswith('"'):
        return json.loads(value)
    if value == "true":
        return True
    if value == "false":
        return False
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_toml_value(item) for item in _split_toml_array(inner)]
    try:
        return int(value)
    except ValueError:
        return value


def _split_toml_array(value: str) -> list[str]:
    items: list[str] = []
    start = 0
    in_string = False
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if char == "," and not in_string:
            item = value[start:index].strip()
            if item:
                items.append(item)
            start = index + 1
    tail = value[start:].strip()
    if tail:
        items.append(tail)
    return items
