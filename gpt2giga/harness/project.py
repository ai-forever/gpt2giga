"""Project identity and non-secret config helpers for the harness cockpit."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from gpt2giga.harness.config import DEFAULT_HARNESS_DATA_DIR
from gpt2giga.harness.types import (
    SECRET_ENV_NAMES,
    SECRET_KEY_PARTS,
    GigaChatApiMode,
    parse_api_mode,
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
    attachments: ProjectAttachmentSettings = field(
        default_factory=ProjectAttachmentSettings
    )


def resolve_project(
    workspace: str | Path | None = None,
    *,
    data_dir: str | Path = DEFAULT_HARNESS_DATA_DIR,
) -> HarnessProject:
    """Resolve workspace identity, preferring the enclosing git root."""
    workspace_path = _resolve_workspace_path(workspace)
    git_root_path = _git_root(workspace_path)
    root_path = git_root_path or workspace_path
    project_id = project_id_for_root(root_path)
    config_path = project_config_path(root_path)
    project_config = load_project_config(root_path) if config_path.exists() else None
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
    attachments_data = _mapping(data.get("attachments"))
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
        attachments=_parse_attachment_settings(attachments_data),
    )


def init_project_config(
    project_root: str | Path,
    *,
    project_name: str | None = None,
    overwrite: bool = False,
) -> HarnessProjectConfig:
    """Create a default non-secret project config if it is missing."""
    path = project_config_path(project_root)
    if path.exists() and not overwrite:
        return load_project_config(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = (
        _optional_text(project_name) or Path(project_root).expanduser().resolve().name
    )
    path.write_text(default_project_config_text(name), encoding="utf-8")
    return load_project_config(project_root)


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
        "[presets.ask]\n"
        'title = "Ask"\n'
        'harness = "direct-chat"\n'
        'mode = "plan"\n'
        'api_mode = "v2"\n'
        "\n"
        "[presets.plan]\n"
        'title = "Plan"\n'
        'harness = "codex-cli"\n'
        'mode = "plan"\n'
        'api_mode = "v2"\n'
        "\n"
        "[presets.review]\n"
        'title = "Review"\n'
        'harness = "claude-code"\n'
        'mode = "read"\n'
        'api_mode = "v2"\n'
        "\n"
        "[presets.implement]\n"
        'title = "Implement"\n'
        'harness = "codex-cli"\n'
        'mode = "edit"\n'
        'api_mode = "v2"\n'
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
            name: {
                "title": preset.title,
                "harness": preset.harness,
                "model": preset.model,
                "api_mode": (
                    preset.api_mode.value if preset.api_mode is not None else None
                ),
                "mode": preset.mode,
            }
            for name, preset in config.presets.items()
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


def _resolve_workspace_path(workspace: str | Path | None) -> Path:
    if workspace is None:
        path = Path.cwd()
    else:
        path = Path(workspace).expanduser()
    resolved = path.resolve()
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
        )
    return presets


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
