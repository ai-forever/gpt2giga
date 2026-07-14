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
from gpt2giga_harness.tools import (
    CompositeSecretResolver,
    EnvironmentSecretResolver,
    SecretReference,
    SecretReferenceKind,
    SecretResolver,
)


MANAGED_MARKER = "gpt2giga-managed-mcp-v1"
HEADLESS_SNAPSHOT_MARKER = "gpt2giga-headless-mcp-snapshot-v1"
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


@dataclass(frozen=True)
class HeadlessManagedMCPSnapshot:
    """Immutable secret-free MCP configuration selected for one headless run."""

    snapshot_id: str
    snapshot_hash: str
    project_id: str
    harness_id: str
    server_ids: tuple[str, ...]
    created_at: str
    descriptors: tuple[Mapping[str, Any], ...]

    def public_ref(self) -> dict[str, Any]:
        """Return the descriptor-free reference safe for runs and APIs."""
        return {
            "schema_version": 1,
            "marker": HEADLESS_SNAPSHOT_MARKER,
            "snapshot_id": self.snapshot_id,
            "snapshot_hash": self.snapshot_hash,
            "project_id": self.project_id,
            "harness_id": self.harness_id,
            "server_ids": list(self.server_ids),
            "created_at": self.created_at,
            "enforcement": "delegated_to_external_cli",
            "tool_calls_observable": False,
        }


class HeadlessManagedMCPSnapshotStore:
    """Persist immutable, redaction-safe headless MCP snapshots by content hash."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.root = self.data_dir / "tools" / "headless_mcp_snapshots"

    def create(
        self,
        *,
        project_id: str,
        harness_id: str,
        descriptors: Sequence[ToolServerDescriptor],
        server_ids: Sequence[str],
    ) -> HeadlessManagedMCPSnapshot:
        """Freeze exactly the requested trusted descriptors for one adapter."""
        _validate_harness(harness_id)
        _validate_project_id(project_id)
        requested = tuple(dict.fromkeys(str(item).strip() for item in server_ids))
        if not requested or any(not item for item in requested):
            raise ValueError("managed MCP server_ids must contain non-empty values")
        by_id = {item.id: item for item in descriptors}
        missing = sorted(set(requested) - set(by_id))
        if missing:
            raise ValueError(f"Managed MCP servers not found: {', '.join(missing)}")
        selected: list[ToolServerDescriptor] = []
        for server_id in requested:
            descriptor = by_id[server_id]
            if not descriptor.enabled:
                raise ValueError(f"Managed MCP server is disabled: {server_id}")
            if not descriptor.trusted:
                raise ValueError(f"Managed MCP server is not trusted: {server_id}")
            if descriptor.harnesses and harness_id not in descriptor.harnesses:
                raise ValueError(
                    f"Managed MCP server {server_id} is incompatible with {harness_id}"
                )
            selected.append(descriptor)
        content = {
            "schema_version": 1,
            "marker": HEADLESS_SNAPSHOT_MARKER,
            "project_id": project_id,
            "harness_id": harness_id,
            "server_ids": list(requested),
            "descriptors": [_descriptor_to_snapshot(item) for item in selected],
        }
        snapshot_hash = _json_hash(content)
        snapshot_id = f"mcp_{snapshot_hash[:32]}"
        path = self._path(snapshot_id)
        with exclusive_file_lock(self.root / f".{snapshot_id}"):
            if path.exists():
                return self.load(
                    {
                        "snapshot_id": snapshot_id,
                        "snapshot_hash": snapshot_hash,
                        "project_id": project_id,
                        "harness_id": harness_id,
                    }
                )
            record = {
                **content,
                "snapshot_id": snapshot_id,
                "snapshot_hash": snapshot_hash,
                "created_at": utc_now(),
            }
            _atomic_write(path, json.dumps(record, indent=2, sort_keys=True) + "\n")
        return _snapshot_from_record(record)

    def load(self, reference: Mapping[str, Any]) -> HeadlessManagedMCPSnapshot:
        """Load and integrity-check one stored snapshot reference."""
        snapshot_id = str(reference.get("snapshot_id") or "").strip()
        if not snapshot_id.startswith("mcp_") or not snapshot_id[4:].isalnum():
            raise ValueError("Invalid managed MCP snapshot id")
        try:
            record = json.loads(self._path(snapshot_id).read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError("Managed MCP snapshot was not found") from exc
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError("Managed MCP snapshot is unreadable") from exc
        if not isinstance(record, Mapping):
            raise ValueError("Managed MCP snapshot must be an object")
        snapshot = _snapshot_from_record(record)
        expected_hash = str(reference.get("snapshot_hash") or "").strip()
        if (
            len(expected_hash) != 64
            or not expected_hash.isalnum()
            or expected_hash != snapshot.snapshot_hash
        ):
            raise ValueError("Managed MCP snapshot hash does not match")
        for field_name in ("project_id", "harness_id"):
            expected = str(reference.get(field_name) or "").strip()
            if expected and expected != str(getattr(snapshot, field_name)):
                raise ValueError(f"Managed MCP snapshot {field_name} does not match")
        return snapshot

    def _path(self, snapshot_id: str) -> Path:
        return self.root / f"{snapshot_id}.json"


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


def materialize_headless_mcp_snapshot(
    harness_id: str,
    home: str | Path,
    reference: Mapping[str, Any] | None,
    *,
    data_dir: str | Path | None,
    resolver: SecretResolver | None = None,
) -> Mapping[str, Any] | None:
    """Write one verified snapshot into the active temporary CLI home."""
    if reference is None:
        return None
    if data_dir is None:
        raise ValueError("Harness data_dir is required for managed MCP snapshots")
    snapshot = HeadlessManagedMCPSnapshotStore(data_dir).load(reference)
    if snapshot.harness_id != harness_id:
        raise ValueError("Managed MCP snapshot harness_id does not match adapter")
    home_path = Path(home).expanduser().resolve()
    path = config_path_for_home(harness_id, home_path)
    home_path.mkdir(parents=True, exist_ok=True)
    secret_resolver = resolver or CompositeSecretResolver(
        (EnvironmentSecretResolver(),)
    )
    descriptors = tuple(
        _descriptor_from_snapshot(item) for item in snapshot.descriptors
    )
    owner = f"headless-mcp:{snapshot.snapshot_id}:{harness_id}"
    with exclusive_file_lock(home_path / ".gpt2giga-config"):
        current = _read_text(path)
        content = _compose_resolved_managed_config(
            harness_id,
            current,
            descriptors,
            resolver=secret_resolver,
            owner=owner,
        )
        if content != current:
            _atomic_write(path, content)
    return {
        **snapshot.public_ref(),
        "materialized": True,
        "active_home": "temporary",
    }


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
    *,
    resolver: SecretResolver | None = None,
    owner: str | None = None,
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
            environment, skipped = _literal_values(
                item.environment, resolver=resolver, owner=owner
            )
            warnings.extend(f"{item.id}: {value}" for value in skipped)
            if environment:
                lines.append(f"[mcp_servers.{_toml_key(item.id)}.env]")
                for key, value in sorted(environment.items()):
                    lines.append(f'{_toml_key(key)} = "{_toml_string(value)}"')
        else:
            lines.append(f'url = "{_toml_string(item.url or "")}"')
            headers, skipped = _literal_values(
                item.headers, resolver=resolver, owner=owner
            )
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
    *,
    resolver: SecretResolver | None = None,
    owner: str | None = None,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    result: dict[str, Any] = {}
    warnings: list[str] = []
    for item in descriptors:
        if item.transport is MCPTransport.STDIO:
            values, skipped = _literal_values(
                item.environment, resolver=resolver, owner=owner
            )
            entry: dict[str, Any] = {
                "command": item.command,
                "args": list(item.args),
            }
            if values:
                entry["env"] = values
        else:
            values, skipped = _literal_values(
                item.headers, resolver=resolver, owner=owner
            )
            entry = {"url": item.url, "type": "http"}
            if values:
                entry["headers"] = values
        warnings.extend(f"{item.id}: {value}" for value in skipped)
        result[item.id] = entry
    return result, tuple(warnings)


def _literal_values(
    values: Mapping[str, str | SecretReference],
    *,
    resolver: SecretResolver | None = None,
    owner: str | None = None,
) -> tuple[dict[str, str], tuple[str, ...]]:
    literals: dict[str, str] = {}
    warnings: list[str] = []
    for key, value in values.items():
        if isinstance(value, SecretReference):
            if resolver is None or owner is None:
                warnings.append(
                    f"secret reference {key} was not copied; use an explicit secret flow"
                )
            else:
                resolved = resolver.resolve(value, owner=owner)
                literals[key] = resolved.reveal_for(owner)
        else:
            literals[key] = value
    return literals, tuple(warnings)


def _compose_resolved_managed_config(
    harness_id: str,
    current: str,
    descriptors: Sequence[ToolServerDescriptor],
    *,
    resolver: SecretResolver,
    owner: str,
) -> str:
    selected = _selected(descriptors, harness_id)
    if harness_id == "codex-cli":
        base = _remove_codex_managed_block(current).rstrip()
        block, _warnings = _codex_block(selected, resolver=resolver, owner=owner)
        content = f"{base}\n\n{block}" if base else block
        return content.rstrip() + "\n"
    try:
        parsed = json.loads(current) if current.strip() else {}
    except json.JSONDecodeError as exc:
        raise ValueError("Managed CLI JSON config is invalid") from exc
    data = dict(parsed) if isinstance(parsed, Mapping) else {}
    entries, _warnings = _json_servers(selected, resolver=resolver, owner=owner)
    data["mcpServers"] = entries
    data["_gpt2giga"] = {"marker": MANAGED_MARKER}
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


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


def _json_hash(value: Mapping[str, Any]) -> str:
    content = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _content_hash(content)


def _descriptor_to_snapshot(descriptor: ToolServerDescriptor) -> dict[str, Any]:
    return {
        "id": descriptor.id,
        "title": descriptor.title,
        "transport": descriptor.transport.value,
        "description": descriptor.description,
        "command": descriptor.command,
        "args": list(descriptor.args),
        "cwd": descriptor.cwd,
        "url": descriptor.url,
        "environment": _values_to_snapshot(descriptor.environment),
        "headers": _values_to_snapshot(descriptor.headers),
        "instructions": descriptor.instructions,
        "source": descriptor.source,
        "trusted": descriptor.trusted,
        "enabled": descriptor.enabled,
        "timeout_seconds": descriptor.timeout_seconds,
        "harnesses": list(descriptor.harnesses),
    }


def _descriptor_from_snapshot(value: Mapping[str, Any]) -> ToolServerDescriptor:
    try:
        descriptor = ToolServerDescriptor(
            id=str(value["id"]),
            title=str(value["title"]),
            transport=MCPTransport(str(value["transport"])),
            description=str(value.get("description") or ""),
            command=str(value["command"]) if value.get("command") else None,
            args=tuple(str(item) for item in value.get("args") or ()),
            cwd=str(value["cwd"]) if value.get("cwd") else None,
            url=str(value["url"]) if value.get("url") else None,
            environment=_values_from_snapshot(value.get("environment")),
            headers=_values_from_snapshot(value.get("headers")),
            instructions=str(value.get("instructions") or ""),
            source=str(value.get("source") or "project"),
            trusted=bool(value.get("trusted")),
            enabled=bool(value.get("enabled")),
            timeout_seconds=float(value.get("timeout_seconds") or 10.0),
            harnesses=tuple(str(item) for item in value.get("harnesses") or ()),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Managed MCP snapshot descriptor is invalid") from exc
    if not descriptor.trusted or not descriptor.enabled:
        raise ValueError(
            "Managed MCP snapshot contains an untrusted or disabled server"
        )
    return descriptor


def _values_to_snapshot(
    values: Mapping[str, str | SecretReference],
) -> dict[str, Any]:
    return {
        key: (
            {
                "secret_ref": {
                    "kind": value.kind.value,
                    "name": value.name,
                    "service": value.service,
                    "account": value.account,
                    "expires_at": value.expires_at,
                }
            }
            if isinstance(value, SecretReference)
            else {"literal": value}
        )
        for key, value in sorted(values.items())
    }


def _values_from_snapshot(value: Any) -> dict[str, str | SecretReference]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str | SecretReference] = {}
    for raw_key, raw_item in value.items():
        key = str(raw_key).strip()
        if not key or not isinstance(raw_item, Mapping):
            raise ValueError("Managed MCP snapshot value is invalid")
        reference = raw_item.get("secret_ref")
        if isinstance(reference, Mapping):
            result[key] = SecretReference(
                kind=SecretReferenceKind(str(reference.get("kind") or "environment")),
                name=str(reference.get("name") or ""),
                service=(
                    str(reference["service"])
                    if reference.get("service") is not None
                    else None
                ),
                account=(
                    str(reference["account"])
                    if reference.get("account") is not None
                    else None
                ),
                expires_at=(
                    str(reference["expires_at"])
                    if reference.get("expires_at") is not None
                    else None
                ),
            )
        elif "literal" in raw_item and isinstance(raw_item["literal"], str):
            result[key] = raw_item["literal"]
        else:
            raise ValueError("Managed MCP snapshot value is invalid")
    return result


def _snapshot_from_record(record: Mapping[str, Any]) -> HeadlessManagedMCPSnapshot:
    content = {
        "schema_version": record.get("schema_version"),
        "marker": record.get("marker"),
        "project_id": record.get("project_id"),
        "harness_id": record.get("harness_id"),
        "server_ids": record.get("server_ids"),
        "descriptors": record.get("descriptors"),
    }
    if content["schema_version"] != 1 or content["marker"] != HEADLESS_SNAPSHOT_MARKER:
        raise ValueError("Unsupported managed MCP snapshot schema")
    snapshot_hash = str(record.get("snapshot_hash") or "")
    if snapshot_hash != _json_hash(content):
        raise ValueError("Managed MCP snapshot integrity check failed")
    snapshot_id = str(record.get("snapshot_id") or "")
    if snapshot_id != f"mcp_{snapshot_hash[:32]}":
        raise ValueError("Managed MCP snapshot id does not match content")
    project_id = str(content["project_id"] or "")
    harness_id = str(content["harness_id"] or "")
    _validate_project_id(project_id)
    _validate_harness(harness_id)
    raw_server_ids = content["server_ids"]
    raw_descriptors = content["descriptors"]
    if not isinstance(raw_server_ids, list) or not all(
        isinstance(item, str) and item for item in raw_server_ids
    ):
        raise ValueError("Managed MCP snapshot server_ids are invalid")
    if not isinstance(raw_descriptors, list) or not all(
        isinstance(item, Mapping) for item in raw_descriptors
    ):
        raise ValueError("Managed MCP snapshot descriptors are invalid")
    descriptors = tuple(dict(item) for item in raw_descriptors)
    parsed_ids = tuple(_descriptor_from_snapshot(item).id for item in descriptors)
    if parsed_ids != tuple(raw_server_ids):
        raise ValueError("Managed MCP snapshot descriptor ids do not match")
    return HeadlessManagedMCPSnapshot(
        snapshot_id=snapshot_id,
        snapshot_hash=snapshot_hash,
        project_id=project_id,
        harness_id=harness_id,
        server_ids=tuple(raw_server_ids),
        created_at=str(record.get("created_at") or ""),
        descriptors=descriptors,
    )


def _validate_harness(harness_id: str) -> None:
    if harness_id not in SUPPORTED_HARNESSES:
        raise ValueError(f"Unsupported managed MCP harness: {harness_id}")


def _validate_project_id(project_id: str) -> None:
    if not project_id.startswith("proj_") or not project_id.replace("_", "").isalnum():
        raise ValueError("Invalid project id")


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
