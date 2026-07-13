"""Managed MCP configuration composition, apply, provenance, and rollback."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import difflib
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable, Mapping, Sequence

from gpt2giga_harness.mcp import MCPTransport, ToolServerDescriptor
from gpt2giga_harness.sessions.locking import exclusive_file_lock
from gpt2giga_harness.sessions.store import utc_now
from gpt2giga_harness.tools import SecretReference


MANAGED_MARKER = "gpt2giga-managed-mcp-v1"
SUPPORTED_HARNESSES = ("codex-cli", "claude-code", "gemini-cli")


class ManagedConfigConflictError(RuntimeError):
    """Raised when a managed home is active or changed since preview."""


class ManagedConfigOwnershipError(RuntimeError):
    """Raised when rollback cannot prove that gpt2giga owns the config."""


@dataclass(frozen=True)
class ManagedConfigPlan:
    """Redaction-safe preview for one managed CLI configuration."""

    harness_id: str
    home: str
    config_path: str
    server_ids: tuple[str, ...]
    current_hash: str
    content_hash: str
    changed: bool
    diff: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ManagedConfigResult:
    """Persisted result of an apply or rollback operation."""

    harness_id: str
    home: str
    config_path: str
    content_hash: str
    server_ids: tuple[str, ...]
    applied_at: str
    backup_path: str | None = None
    rolled_back: bool = False


class ManagedMCPConfigService:
    """Write MCP configuration only inside Harness-owned homes."""

    def __init__(
        self,
        data_dir: str | Path,
        *,
        home_active: Callable[[Path], bool] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.home_active = home_active or (lambda _home: False)

    def managed_home(self, harness_id: str, project_id: str) -> Path:
        """Return a validated Harness-owned native home."""
        _validate_harness(harness_id)
        if (
            not project_id.startswith("proj_")
            or not project_id.replace("_", "").isalnum()
        ):
            raise ValueError("Invalid project id")
        family = harness_id.removesuffix("-cli").replace("-code", "")
        home = self.data_dir / "native" / family / "homes" / project_id
        return _validate_owned_home(self.data_dir, home)

    def preview(
        self,
        harness_id: str,
        project_id: str,
        descriptors: Sequence[ToolServerDescriptor],
    ) -> ManagedConfigPlan:
        """Build an exact redacted diff without changing filesystem state."""
        home = self.managed_home(harness_id, project_id)
        path = config_path_for_home(harness_id, home)
        current = _read_text(path)
        composed, warnings = compose_managed_config(harness_id, current, descriptors)
        return ManagedConfigPlan(
            harness_id=harness_id,
            home=str(home),
            config_path=str(path),
            server_ids=tuple(item.id for item in _selected(descriptors, harness_id)),
            current_hash=_content_hash(current),
            content_hash=_content_hash(composed),
            changed=current != composed,
            diff=_redacted_diff(current, composed, path.name),
            warnings=warnings,
        )

    def apply(
        self,
        harness_id: str,
        project_id: str,
        descriptors: Sequence[ToolServerDescriptor],
        *,
        expected_hash: str,
    ) -> ManagedConfigResult:
        """Atomically apply a previously previewed managed configuration."""
        home = self.managed_home(harness_id, project_id)
        path = config_path_for_home(harness_id, home)
        lock_path = home / ".gpt2giga-config"
        home.mkdir(parents=True, exist_ok=True)
        with exclusive_file_lock(lock_path):
            if self.home_active(home):
                raise ManagedConfigConflictError(
                    "Managed config cannot change while a native process owns this home"
                )
            current = _read_text(path)
            if _content_hash(current) != expected_hash:
                raise ManagedConfigConflictError(
                    "Managed config changed after preview; refresh the diff"
                )
            composed, _warnings = compose_managed_config(
                harness_id, current, descriptors
            )
            backup = _backup(path, current) if path.exists() else None
            _atomic_write(path, composed)
            selected = tuple(item.id for item in _selected(descriptors, harness_id))
            result = ManagedConfigResult(
                harness_id=harness_id,
                home=str(home),
                config_path=str(path),
                content_hash=_content_hash(composed),
                server_ids=selected,
                applied_at=utc_now(),
                backup_path=str(backup) if backup else None,
            )
            _write_ownership(home, result)
            return result

    def rollback(self, harness_id: str, project_id: str) -> ManagedConfigResult:
        """Restore the most recent backup after verifying ownership and hash."""
        home = self.managed_home(harness_id, project_id)
        path = config_path_for_home(harness_id, home)
        lock_path = home / ".gpt2giga-config"
        with exclusive_file_lock(lock_path):
            if self.home_active(home):
                raise ManagedConfigConflictError(
                    "Managed config cannot change while a native process owns this home"
                )
            marker = _read_ownership(home)
            if marker.get("marker") != MANAGED_MARKER:
                raise ManagedConfigOwnershipError("Managed ownership marker is missing")
            current = _read_text(path)
            if _content_hash(current) != marker.get("content_hash"):
                raise ManagedConfigOwnershipError(
                    "Managed config changed outside gpt2giga; refusing rollback"
                )
            backup_value = marker.get("backup_path")
            if backup_value:
                backup = _validate_owned_home(self.data_dir, Path(str(backup_value)))
                restored = backup.read_text(encoding="utf-8")
                _atomic_write(path, restored)
            else:
                path.unlink(missing_ok=True)
                restored = ""
            result = ManagedConfigResult(
                harness_id=harness_id,
                home=str(home),
                config_path=str(path),
                content_hash=_content_hash(restored),
                server_ids=(),
                applied_at=utc_now(),
                backup_path=str(backup_value) if backup_value else None,
                rolled_back=True,
            )
            _ownership_path(home).unlink(missing_ok=True)
            return result


def config_path_for_home(harness_id: str, home: Path) -> Path:
    """Return the CLI-specific config path inside one managed home."""
    _validate_harness(harness_id)
    if harness_id == "codex-cli":
        return home / "config.toml"
    if harness_id == "claude-code":
        return home / ".claude.json"
    return home / ".gemini" / "settings.json"


def compose_managed_config(
    harness_id: str,
    current: str,
    descriptors: Sequence[ToolServerDescriptor],
) -> tuple[str, tuple[str, ...]]:
    """Merge owned MCP entries while preserving non-MCP startup settings."""
    selected = _selected(descriptors, harness_id)
    if harness_id == "codex-cli":
        base = _remove_codex_managed_block(current).rstrip()
        block, warnings = _codex_block(selected)
        content = f"{base}\n\n{block}" if base else block
        return content.rstrip() + "\n", warnings
    data: dict[str, Any]
    try:
        parsed = json.loads(current) if current.strip() else {}
        data = dict(parsed) if isinstance(parsed, Mapping) else {}
    except json.JSONDecodeError as exc:
        raise ValueError("Managed CLI JSON config is invalid") from exc
    entries, warnings = _json_servers(selected)
    data["mcpServers"] = entries
    data["_gpt2giga"] = {"marker": MANAGED_MARKER}
    return json.dumps(
        data, indent=2, sort_keys=True, ensure_ascii=False
    ) + "\n", warnings


def compose_startup_config(
    harness_id: str,
    current: str,
    base: str | Mapping[str, Any],
) -> str:
    """Refresh CLI startup settings without erasing managed MCP entries."""
    _validate_harness(harness_id)
    if harness_id == "codex-cli":
        base_text = str(base).rstrip()
        begin = f"# BEGIN {MANAGED_MARKER}"
        block = ""
        if begin in current:
            block = begin + current.split(begin, 1)[1]
        return f"{base_text}\n\n{block}".rstrip() + "\n"
    try:
        parsed = json.loads(current) if current.strip() else {}
    except json.JSONDecodeError as exc:
        raise ValueError("Managed CLI JSON config is invalid") from exc
    existing = dict(parsed) if isinstance(parsed, Mapping) else {}
    if not isinstance(base, Mapping):
        raise TypeError("JSON CLI startup settings must be a mapping")
    for key, value in base.items():
        if (
            harness_id == "claude-code"
            and key == "projects"
            and isinstance(existing.get(key), Mapping)
            and isinstance(value, Mapping)
        ):
            projects = dict(existing[key])
            for project_path, project_settings in value.items():
                current_settings = projects.get(project_path)
                if isinstance(current_settings, Mapping) and isinstance(
                    project_settings, Mapping
                ):
                    projects[project_path] = {
                        **dict(current_settings),
                        **dict(project_settings),
                    }
                else:
                    projects[project_path] = project_settings
            existing[key] = projects
        else:
            existing[key] = value
    return json.dumps(existing, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_startup_config(
    harness_id: str,
    home: str | Path,
    base: str | Mapping[str, Any],
) -> str:
    """Atomically refresh startup settings under the shared per-home lock."""
    home_path = Path(home).expanduser().resolve()
    path = config_path_for_home(harness_id, home_path)
    home_path.mkdir(parents=True, exist_ok=True)
    with exclusive_file_lock(home_path / ".gpt2giga-config"):
        current = _read_text(path)
        content = compose_startup_config(harness_id, current, base)
        if content != current:
            _atomic_write(path, content)
            marker = dict(_read_ownership(home_path))
            if marker.get("marker") == MANAGED_MARKER and marker.get(
                "content_hash"
            ) == _content_hash(current):
                marker["content_hash"] = _content_hash(content)
                _atomic_write(
                    _ownership_path(home_path),
                    json.dumps(marker, indent=2, sort_keys=True) + "\n",
                )
        return _content_hash(content)


def managed_config_plan_to_dict(plan: ManagedConfigPlan) -> dict[str, Any]:
    """Serialize a managed config preview."""
    return asdict(plan)


def managed_config_result_to_dict(result: ManagedConfigResult) -> dict[str, Any]:
    """Serialize applied config provenance."""
    return asdict(result)


def _selected(
    descriptors: Sequence[ToolServerDescriptor], harness_id: str
) -> tuple[ToolServerDescriptor, ...]:
    _validate_harness(harness_id)
    return tuple(
        sorted(
            (
                item
                for item in descriptors
                if item.enabled
                and item.trusted
                and (not item.harnesses or harness_id in item.harnesses)
            ),
            key=lambda item: item.id,
        )
    )


def _codex_block(
    descriptors: Sequence[ToolServerDescriptor],
) -> tuple[str, tuple[str, ...]]:
    lines = [f"# BEGIN {MANAGED_MARKER}"]
    warnings: list[str] = []
    for item in descriptors:
        lines.append(f"[mcp_servers.{_toml_key(item.id)}]")
        if item.transport is MCPTransport.STDIO:
            lines.append(f'command = "{_toml_string(item.command or "")}"')
            if item.args:
                values = ", ".join(f'"{_toml_string(value)}"' for value in item.args)
                lines.append(f"args = [{values}]")
            environment, skipped = _literal_values(item.environment)
            warnings.extend(f"{item.id}: {value}" for value in skipped)
            if environment:
                lines.append(f"[mcp_servers.{_toml_key(item.id)}.env]")
                for key, value in sorted(environment.items()):
                    lines.append(f'{_toml_key(key)} = "{_toml_string(value)}"')
        else:
            lines.append(f'url = "{_toml_string(item.url or "")}"')
            headers, skipped = _literal_values(item.headers)
            warnings.extend(f"{item.id}: {value}" for value in skipped)
            if headers:
                lines.append(f"[mcp_servers.{_toml_key(item.id)}.http_headers]")
                for key, value in sorted(headers.items()):
                    lines.append(f'{_toml_key(key)} = "{_toml_string(value)}"')
        lines.append("")
    lines.append(f"# END {MANAGED_MARKER}")
    return "\n".join(lines), tuple(warnings)


def _json_servers(
    descriptors: Sequence[ToolServerDescriptor],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    result: dict[str, Any] = {}
    warnings: list[str] = []
    for item in descriptors:
        if item.transport is MCPTransport.STDIO:
            values, skipped = _literal_values(item.environment)
            entry: dict[str, Any] = {
                "command": item.command,
                "args": list(item.args),
            }
            if values:
                entry["env"] = values
        else:
            values, skipped = _literal_values(item.headers)
            entry = {"url": item.url, "type": "http"}
            if values:
                entry["headers"] = values
        warnings.extend(f"{item.id}: {value}" for value in skipped)
        result[item.id] = entry
    return result, tuple(warnings)


def _literal_values(
    values: Mapping[str, str | SecretReference],
) -> tuple[dict[str, str], tuple[str, ...]]:
    literals: dict[str, str] = {}
    warnings: list[str] = []
    for key, value in values.items():
        if isinstance(value, SecretReference):
            warnings.append(
                f"secret reference {key} was not copied; use an explicit secret flow"
            )
        else:
            literals[key] = value
    return literals, tuple(warnings)


def _remove_codex_managed_block(content: str) -> str:
    begin = f"# BEGIN {MANAGED_MARKER}"
    end = f"# END {MANAGED_MARKER}"
    if begin not in content:
        return content
    before, remainder = content.split(begin, 1)
    if end not in remainder:
        raise ValueError("Managed Codex MCP block is incomplete")
    _owned, after = remainder.split(end, 1)
    return f"{before.rstrip()}\n{after.lstrip()}".strip()


def _redacted_diff(before: str, after: str, name: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"{name}.current",
            tofile=f"{name}.managed",
        )
    )


def _backup(path: Path, content: str) -> Path:
    backup_dir = path.parent / ".gpt2giga-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"{path.name}.{_content_hash(content)[:12]}.bak"
    if not backup.exists():
        _atomic_write(backup, content)
    return backup


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(raw_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _write_ownership(home: Path, result: ManagedConfigResult) -> None:
    payload = {"marker": MANAGED_MARKER, **asdict(result)}
    _atomic_write(
        _ownership_path(home),
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
    )


def _read_ownership(home: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(_ownership_path(home).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, Mapping) else {}


def _ownership_path(home: Path) -> Path:
    return home / ".gpt2giga-mcp-owner.json"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _validate_harness(harness_id: str) -> None:
    if harness_id not in SUPPORTED_HARNESSES:
        raise ValueError(f"Unsupported managed MCP harness: {harness_id}")


def _validate_owned_home(data_dir: Path, path: Path) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(data_dir)
    except ValueError as exc:
        raise ManagedConfigOwnershipError("Path is outside Harness data dir") from exc
    return resolved


def _toml_key(value: str) -> str:
    if value.replace("_", "").replace("-", "").isalnum():
        return value
    return f'"{_toml_string(value)}"'


def _toml_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
