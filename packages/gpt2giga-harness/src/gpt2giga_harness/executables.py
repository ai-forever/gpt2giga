"""User-owned executable configuration and resolution."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Mapping

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback.
    import tomli as tomllib


USER_CONFIG_RELATIVE_PATH = Path(".gpt2giga") / "harness" / "config.toml"
_EXECUTABLES_TABLE = "executables"
_HARNESS_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_TABLE_PATTERN = re.compile(r"^\s*\[([^]]+)]\s*(?:#.*)?$")


class UserHarnessConfigError(ValueError):
    """Raised when the user-owned Harness config is invalid."""


@dataclass(frozen=True)
class ExecutableResolution:
    """Describe where one external Harness executable came from."""

    harness_id: str
    command_name: str
    executable: str | None
    source: str
    configured: str | None = None
    error: str | None = None

    @property
    def available(self) -> bool:
        """Return whether an executable is ready to launch."""
        return self.executable is not None and self.error is None


class ExecutableResolver:
    """Resolve external Harness executables from user config, then ``PATH``."""

    def __init__(
        self,
        executables: Mapping[str, Any] | None = None,
        *,
        config_path: str | Path | None = None,
        config_error: str | None = None,
    ) -> None:
        self.executables = dict(executables or {})
        self.config_path = Path(config_path) if config_path is not None else None
        self.config_error = config_error

    @classmethod
    def from_user_config(
        cls,
        config_path: str | Path | None = None,
    ) -> "ExecutableResolver":
        """Load executable overrides from the user-owned Harness TOML file."""
        path = Path(config_path) if config_path is not None else user_config_path()
        try:
            executables = load_user_executables(path)
        except UserHarnessConfigError as exc:
            return cls(config_path=path, config_error=str(exc))
        return cls(executables, config_path=path)

    @classmethod
    def path_only(cls) -> "ExecutableResolver":
        """Create a resolver that does not read user configuration."""
        return cls()

    def resolve(self, harness_id: str, command_name: str) -> ExecutableResolution:
        """Resolve one executable with explicit user config taking precedence."""
        if self.config_error is not None:
            return ExecutableResolution(
                harness_id=harness_id,
                command_name=command_name,
                executable=None,
                source="user_config",
                error=self.config_error,
            )
        if harness_id in self.executables:
            return self._resolve_configured(
                harness_id,
                command_name,
                self.executables[harness_id],
            )
        executable = shutil.which(command_name)
        return ExecutableResolution(
            harness_id=harness_id,
            command_name=command_name,
            executable=executable,
            source="path" if executable is not None else "missing",
        )

    def _resolve_configured(
        self,
        harness_id: str,
        command_name: str,
        value: Any,
    ) -> ExecutableResolution:
        if not isinstance(value, str) or not value.strip():
            return self._configured_error(
                harness_id,
                command_name,
                value if isinstance(value, str) else None,
                "must be a non-empty string",
            )
        configured = value.strip()
        expanded = Path(configured).expanduser()
        if not expanded.is_absolute():
            return self._configured_error(
                harness_id,
                command_name,
                configured,
                "must be an absolute path",
            )
        executable = shutil.which(str(expanded))
        if executable is None:
            return self._configured_error(
                harness_id,
                command_name,
                configured,
                "does not exist or is not executable",
            )
        return ExecutableResolution(
            harness_id=harness_id,
            command_name=command_name,
            executable=executable,
            source="user_config",
            configured=configured,
        )

    def _configured_error(
        self,
        harness_id: str,
        command_name: str,
        configured: str | None,
        detail: str,
    ) -> ExecutableResolution:
        key = f"executables.{harness_id}"
        path = f" in {self.config_path}" if self.config_path is not None else ""
        return ExecutableResolution(
            harness_id=harness_id,
            command_name=command_name,
            executable=None,
            source="user_config",
            configured=configured,
            error=f"{key}{path} {detail}",
        )


def user_config_path() -> Path:
    """Return the fixed user-owned Unified Harness config path."""
    return Path.home() / USER_CONFIG_RELATIVE_PATH


def load_user_executables(
    config_path: str | Path | None = None,
) -> Mapping[str, Any]:
    """Load the optional ``[executables]`` table from user configuration."""
    path = Path(config_path) if config_path is not None else user_config_path()
    if not path.exists():
        return {}
    try:
        with path.open("rb") as stream:
            document = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise UserHarnessConfigError(
            f"Could not read Harness config {path}: {exc}"
        ) from exc
    executables = document.get(_EXECUTABLES_TABLE, {})
    if not isinstance(executables, Mapping):
        raise UserHarnessConfigError(
            f"Harness config [{_EXECUTABLES_TABLE}] in {path} must be a table"
        )
    return dict(executables)


def set_user_executable(
    harness_id: str,
    executable: str,
    *,
    config_path: str | Path | None = None,
) -> Path:
    """Set one executable path while preserving unrelated TOML text."""
    _validate_harness_id(harness_id)
    normalized = executable.strip()
    if not normalized:
        raise UserHarnessConfigError("Executable path must not be empty")
    expanded = Path(normalized).expanduser()
    if not expanded.is_absolute():
        raise UserHarnessConfigError("Executable path must be absolute")
    path = Path(config_path) if config_path is not None else user_config_path()
    text = _read_config_text(path)
    updated = _update_executable_text(text, harness_id, normalized)
    _validate_config_text(updated, path)
    _atomic_write(path, updated)
    return path


def unset_user_executable(
    harness_id: str,
    *,
    config_path: str | Path | None = None,
) -> tuple[Path, bool]:
    """Remove one executable override while preserving unrelated TOML text."""
    _validate_harness_id(harness_id)
    path = Path(config_path) if config_path is not None else user_config_path()
    if not path.exists():
        return path, False
    text = _read_config_text(path)
    updated, removed = _remove_executable_text(text, harness_id)
    if removed:
        _validate_config_text(updated, path)
        _atomic_write(path, updated)
    return path, removed


def executable_resolution_to_dict(
    resolution: ExecutableResolution,
) -> dict[str, str | None]:
    """Serialize a resolution for CLI diagnostics."""
    return {
        "executable": resolution.executable,
        "executable_source": resolution.source,
        "configured_executable": resolution.configured,
        "executable_error": resolution.error,
    }


def _validate_harness_id(harness_id: str) -> None:
    if _HARNESS_ID_PATTERN.fullmatch(harness_id) is None:
        raise UserHarnessConfigError(
            "Harness id must contain only letters, numbers, underscores, or hyphens"
        )


def _read_config_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UserHarnessConfigError(
            f"Could not read Harness config {path}: {exc}"
        ) from exc
    _validate_config_text(text, path)
    return text


def _update_executable_text(text: str, harness_id: str, executable: str) -> str:
    lines = text.splitlines(keepends=True)
    start, end = _table_bounds(lines, _EXECUTABLES_TABLE)
    assignment = f"{json.dumps(harness_id)} = {json.dumps(executable)}\n"
    if start is None:
        prefix = text
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        if prefix and not prefix.endswith("\n\n"):
            prefix += "\n"
        return f"{prefix}[{_EXECUTABLES_TABLE}]\n{assignment}"
    key_pattern = _assignment_pattern(harness_id)
    for index in range(start + 1, end):
        if key_pattern.match(lines[index]):
            lines[index] = assignment
            return "".join(lines)
    lines.insert(end, assignment)
    return "".join(lines)


def _remove_executable_text(text: str, harness_id: str) -> tuple[str, bool]:
    lines = text.splitlines(keepends=True)
    start, end = _table_bounds(lines, _EXECUTABLES_TABLE)
    if start is None:
        return text, False
    key_pattern = _assignment_pattern(harness_id)
    for index in range(start + 1, end):
        if key_pattern.match(lines[index]):
            del lines[index]
            return "".join(lines), True
    return text, False


def _table_bounds(
    lines: list[str],
    table_name: str,
) -> tuple[int | None, int]:
    start: int | None = None
    for index, line in enumerate(lines):
        match = _TABLE_PATTERN.match(line.rstrip("\r\n"))
        if match is None:
            continue
        if start is not None:
            return start, index
        table = match.group(1).strip()
        if table in {table_name, json.dumps(table_name), f"'{table_name}'"}:
            start = index
    return start, len(lines)


def _assignment_pattern(harness_id: str) -> re.Pattern[str]:
    quoted = re.escape(json.dumps(harness_id))
    literal = re.escape(f"'{harness_id}'")
    bare = re.escape(harness_id)
    return re.compile(rf"^\s*(?:{quoted}|{literal}|{bare})\s*=")


def _validate_config_text(text: str, path: Path) -> None:
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise UserHarnessConfigError(f"Invalid Harness config {path}: {exc}") from exc
    executables = document.get(_EXECUTABLES_TABLE, {})
    if not isinstance(executables, Mapping):
        raise UserHarnessConfigError(
            f"Harness config [{_EXECUTABLES_TABLE}] in {path} must be a table"
        )


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
