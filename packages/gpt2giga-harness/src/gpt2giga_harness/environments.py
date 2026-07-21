"""Provider-neutral, bounded snapshots of local source environments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from importlib.metadata import entry_points
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import threading
from typing import Any, Callable, Mapping, Protocol

from gpt2giga_harness.registries import (
    EntryPointFamily,
    RegistrationOutcome,
    RegistryCollisionError,
    VersionedRegistryKernel,
)
from gpt2giga_harness.types import redact_secrets


ENVIRONMENT_SNAPSHOT_SCHEMA_VERSION = 1
NEUTRAL_ENVIRONMENT_ENTRY_POINT_GROUP = "agent_workbench.environment_providers.v1"
ENVIRONMENT_PROVIDER_ENTRY_POINTS = EntryPointFamily(
    registry_id="environment_provider",
    api_version=1,
    primary_group=NEUTRAL_ENVIRONMENT_ENTRY_POINT_GROUP,
)
MAX_DISCOVERY_ERRORS = 20
MAX_DISCOVERY_ERROR_CHARS = 400
MAX_COMMAND_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_DIFF_HASH_BYTES = 32 * 1024 * 1024
MAX_CHANGED_PATHS = 100
MAX_CAPTURED_PATHS = 512
MAX_PATH_CHARS = 512
GIT_TIMEOUT_SECONDS = 10.0
_HEX_SHA_RE = re.compile(r"[0-9a-f]{40,64}\Z")
_IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+@~-]{0,127}\Z")
_SECRET_FILENAMES = frozenset(
    {
        ".netrc",
        "auth.json",
        "credentials",
        "credentials.json",
        "id_dsa",
        "id_ed25519",
        "id_rsa",
        "token.json",
    }
)
_SECRET_SUFFIXES = (".jks", ".key", ".keystore", ".p12", ".pem", ".pfx")


def _validate_identity(value: str, field_name: str) -> None:
    if not isinstance(value, str) or _IDENTITY_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} is invalid")


def _validate_bounded_text(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_PATH_CHARS
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError(f"environment {field_name} is invalid")


class EnvironmentCaptureError(RuntimeError):
    """Fail-closed bounded reason an environment snapshot could not be captured."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class EnvironmentProviderDescriptor:
    """Versioned declaration for one environment projection provider."""

    id: str
    display_name: str
    capabilities: tuple[str, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported environment provider schema_version")
        _validate_identity(self.id, "environment provider id")
        if not self.display_name.strip():
            raise ValueError("environment provider display_name is required")
        capabilities = tuple(sorted(set(self.capabilities)))
        if not capabilities:
            raise ValueError("environment provider capabilities are required")
        for capability in capabilities:
            _validate_identity(capability, "environment provider capability")
        object.__setattr__(self, "capabilities", capabilities)


@dataclass(frozen=True)
class EnvironmentSnapshot:
    """Canonical content-free identity of one local Git worktree state."""

    provider_id: str
    repository_root: str
    worktree_root: str
    branch: str | None
    detached: bool
    head: str | None
    base_identity: str | None
    upstream: str | None
    ahead: int
    behind: int
    remote: str | None
    staged_count: int
    unstaged_count: int
    untracked_count: int
    additions: int
    deletions: int
    changed_paths: tuple[str, ...]
    changed_paths_truncated: bool
    diff_sha256: str
    captured_at: str
    push_ready: bool
    push_blocker: str | None
    schema_version: int = ENVIRONMENT_SNAPSHOT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != ENVIRONMENT_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError("unsupported environment snapshot schema_version")
        _validate_identity(self.provider_id, "environment provider id")
        for value, name in (
            (self.repository_root, "repository_root"),
            (self.worktree_root, "worktree_root"),
        ):
            if not value or len(value) > 4096:
                raise ValueError(f"environment {name} is invalid")
        if self.branch is not None:
            _validate_bounded_text(self.branch, "branch")
        if not isinstance(self.detached, bool):
            raise ValueError("environment detached must be a boolean")
        for value, name in (
            (self.head, "head"),
            (self.base_identity, "base_identity"),
        ):
            if value is not None and _HEX_SHA_RE.fullmatch(value) is None:
                raise ValueError(f"environment {name} is invalid")
        for value, name in (
            (self.upstream, "upstream"),
            (self.remote, "remote"),
            (self.push_blocker, "push_blocker"),
        ):
            if value is not None:
                _validate_bounded_text(value, name)
        for name in (
            "ahead",
            "behind",
            "staged_count",
            "unstaged_count",
            "untracked_count",
            "additions",
            "deletions",
        ):
            if not isinstance(getattr(self, name), int) or getattr(self, name) < 0:
                raise ValueError(f"environment {name} must be a non-negative integer")
        paths = tuple(self.changed_paths)
        if len(paths) > MAX_CHANGED_PATHS or paths != tuple(sorted(set(paths))):
            raise ValueError("environment changed_paths are not canonical")
        if any(not _is_safe_summary_path(path) for path in paths):
            raise ValueError("environment changed_paths contain an unsafe path")
        object.__setattr__(self, "changed_paths", paths)
        if not isinstance(self.changed_paths_truncated, bool):
            raise ValueError("changed_paths_truncated must be a boolean")
        if (
            len(self.diff_sha256) != 64
            or _HEX_SHA_RE.fullmatch(self.diff_sha256) is None
        ):
            raise ValueError("environment diff_sha256 is invalid")
        _parse_timestamp(self.captured_at)
        if not isinstance(self.push_ready, bool):
            raise ValueError("environment push_ready must be a boolean")
        if self.push_ready == (self.push_blocker is not None):
            raise ValueError("environment push readiness is inconsistent")

    def to_dict(self) -> dict[str, Any]:
        """Serialize the strict forward-only snapshot shape."""
        return {
            "schema_version": self.schema_version,
            "provider_id": self.provider_id,
            "repository_root": self.repository_root,
            "worktree_root": self.worktree_root,
            "branch": self.branch,
            "detached": self.detached,
            "head": self.head,
            "base_identity": self.base_identity,
            "upstream": self.upstream,
            "ahead": self.ahead,
            "behind": self.behind,
            "remote": self.remote,
            "staged_count": self.staged_count,
            "unstaged_count": self.unstaged_count,
            "untracked_count": self.untracked_count,
            "additions": self.additions,
            "deletions": self.deletions,
            "changed_paths": list(self.changed_paths),
            "changed_paths_truncated": self.changed_paths_truncated,
            "diff_sha256": self.diff_sha256,
            "captured_at": self.captured_at,
            "push_ready": self.push_ready,
            "push_blocker": self.push_blocker,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EnvironmentSnapshot:
        """Parse only the current exact schema; future shapes fail closed."""
        if not isinstance(payload, Mapping):
            raise ValueError("environment snapshot must be an object")
        expected = {
            "schema_version",
            "provider_id",
            "repository_root",
            "worktree_root",
            "branch",
            "detached",
            "head",
            "base_identity",
            "upstream",
            "ahead",
            "behind",
            "remote",
            "staged_count",
            "unstaged_count",
            "untracked_count",
            "additions",
            "deletions",
            "changed_paths",
            "changed_paths_truncated",
            "diff_sha256",
            "captured_at",
            "push_ready",
            "push_blocker",
        }
        if set(payload) != expected:
            raise ValueError("environment snapshot fields are invalid")
        paths = payload["changed_paths"]
        if not isinstance(paths, list) or any(
            not isinstance(item, str) for item in paths
        ):
            raise ValueError("environment changed_paths must be a string list")
        return cls(**{**payload, "changed_paths": tuple(paths)})


class EnvironmentProvider(Protocol):
    """Read-only provider contract for one local or hosted environment family."""

    @property
    def descriptor(self) -> EnvironmentProviderDescriptor: ...

    def snapshot(self, workspace: str | Path) -> EnvironmentSnapshot: ...


@dataclass(frozen=True)
class EnvironmentProviderPlugin:
    """Discoverable provider descriptor and lazy implementation factory."""

    descriptor: EnvironmentProviderDescriptor
    factory: Callable[[], EnvironmentProvider]

    def __post_init__(self) -> None:
        if not isinstance(self.descriptor, EnvironmentProviderDescriptor):
            raise ValueError("environment provider descriptor is invalid")
        if not callable(self.factory):
            raise ValueError("environment provider factory must be callable")


class EnvironmentProviderRegistry:
    """Discover environment providers through the neutral v1 registry kernel."""

    def __init__(self) -> None:
        self._kernel = VersionedRegistryKernel[EnvironmentProviderPlugin](
            ENVIRONMENT_PROVIDER_ENTRY_POINTS
        )
        self.discovery_errors: list[str] = []

    @classmethod
    def with_builtins(cls) -> EnvironmentProviderRegistry:
        """Create a registry containing the local Git provider."""
        registry = cls()
        registry._register(
            git_environment_provider_plugin(),
            identity=_implementation_identity(git_environment_provider_plugin),
            source="built-in:git_environment_provider_plugin",
        )
        return registry

    def register(self, plugin: EnvironmentProviderPlugin) -> RegistrationOutcome:
        """Register one runtime provider."""
        return self._register(
            plugin,
            identity=_plugin_identity(plugin),
            source=f"runtime:{plugin.descriptor.id}",
        )

    def _register(
        self,
        plugin: EnvironmentProviderPlugin,
        *,
        identity: str,
        source: str,
        allow_equivalent_duplicate: bool = False,
    ) -> RegistrationOutcome:
        if not isinstance(plugin, EnvironmentProviderPlugin):
            raise TypeError("environment entry point must return a provider plugin")
        return self._kernel.register(
            item_id=plugin.descriptor.id,
            item=plugin,
            identity=identity,
            source=source,
            allow_equivalent_duplicate=allow_equivalent_duplicate,
        )

    def list(self) -> tuple[EnvironmentProviderDescriptor, ...]:
        """Return provider declarations in deterministic order."""
        return tuple(
            plugin.descriptor
            for plugin in sorted(
                self._kernel.values(), key=lambda item: item.descriptor.id
            )
        )

    def create_provider(self, provider_id: str) -> EnvironmentProvider:
        """Create one provider and verify its declared identity."""
        plugin = self._kernel.get(provider_id)
        if plugin is None:
            raise KeyError(provider_id)
        provider = plugin.factory()
        descriptor = getattr(provider, "descriptor", None)
        snapshot = getattr(provider, "snapshot", None)
        if descriptor != plugin.descriptor or not callable(snapshot):
            raise TypeError("environment provider factory returned an invalid provider")
        return provider

    def load_entry_points(self) -> None:
        """Load third-party providers with bounded redaction-safe failures."""
        try:
            all_entry_points = entry_points()
        except Exception as exc:  # pragma: no cover - defensive importlib path
            self._record_discovery_error(
                "Environment provider discovery failed: "
                f"{type(exc).__name__} (details omitted)."
            )
            return
        selected = sorted(
            _select_entry_points(
                all_entry_points, ENVIRONMENT_PROVIDER_ENTRY_POINTS.primary_group
            ),
            key=_entry_point_sort_key,
        )
        for entry_point in selected:
            entry_name = str(getattr(entry_point, "name", "<unnamed>"))
            source = (
                f"entry-point:{ENVIRONMENT_PROVIDER_ENTRY_POINTS.primary_group}:"
                f"{entry_name}"
            )
            try:
                loaded = entry_point.load()
                plugin = _load_entry_point_plugin(loaded)
                self._register(
                    plugin,
                    identity=_entry_point_identity(entry_point, loaded, plugin),
                    source=source,
                    allow_equivalent_duplicate=True,
                )
            except RegistryCollisionError as exc:
                self._record_discovery_error(
                    "Environment provider id collision for "
                    f"{exc.item_id!r}: keeping {exc.existing_source}; "
                    f"rejected {exc.incoming_source}."
                )
            except Exception as exc:  # pragma: no cover - plugin failure path
                self._record_discovery_error(
                    f"{source}: {type(exc).__name__} (details omitted)."
                )

    def _record_discovery_error(self, message: str) -> None:
        if len(self.discovery_errors) >= MAX_DISCOVERY_ERRORS:
            return
        safe = str(redact_secrets(message))
        self.discovery_errors.append(safe[:MAX_DISCOVERY_ERROR_CHARS])


GIT_ENVIRONMENT_DESCRIPTOR = EnvironmentProviderDescriptor(
    id="git",
    display_name="Git",
    capabilities=("local_snapshot",),
)


class GitEnvironmentProvider:
    """Capture bounded, read-only local Git snapshots without retaining content."""

    descriptor = GIT_ENVIRONMENT_DESCRIPTOR

    def __init__(
        self,
        *,
        git_executable: str | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        executable = git_executable or shutil.which("git")
        if executable is None:
            raise EnvironmentCaptureError("git_unavailable", "Git is unavailable.")
        resolved = Path(executable).expanduser().resolve()
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            raise EnvironmentCaptureError(
                "git_unavailable", "Git executable is unavailable."
            )
        self._git = str(resolved)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def snapshot(self, workspace: str | Path) -> EnvironmentSnapshot:
        """Capture one exact bounded snapshot of a local Git worktree."""
        requested = Path(workspace).expanduser().resolve()
        if not requested.is_dir():
            raise EnvironmentCaptureError(
                "workspace_unavailable", "Workspace is not a directory."
            )
        worktree_root = self._required_text(requested, "rev-parse", "--show-toplevel")
        worktree_path = Path(worktree_root).resolve()
        common_git_dir = self._required_text(
            worktree_path, "rev-parse", "--path-format=absolute", "--git-common-dir"
        )
        common_path = Path(common_git_dir).resolve()
        repository_path = (
            common_path.parent if common_path.name == ".git" else worktree_path
        )

        status_result = self._run(
            worktree_path,
            "status",
            "--porcelain=v2",
            "--branch",
            "-z",
            "--untracked-files=all",
            "--",
            ".",
            ":(exclude)local",
            ":(exclude)local/**",
        )
        status = _parse_status(status_result.stdout)
        safe_paths = tuple(
            sorted(path for path in status.paths if _is_safe_summary_path(path))
        )
        if len(safe_paths) > MAX_CAPTURED_PATHS:
            raise EnvironmentCaptureError(
                "path_limit", "Git environment contains too many changed paths."
            )

        head = status.head
        upstream = status.upstream
        base_identity = head
        if head is not None and upstream is not None:
            base = self._optional_text(worktree_path, "merge-base", "HEAD", upstream)
            if base is not None and _HEX_SHA_RE.fullmatch(base):
                base_identity = base
        remote = self._remote_name(worktree_path, status.branch, upstream)
        additions, deletions = self._numstat(worktree_path, head, safe_paths)
        diff_sha256 = self._diff_hash(
            worktree_path,
            head,
            safe_paths,
            tuple(
                path for path in status.untracked_paths if _is_safe_summary_path(path)
            ),
            status_result.stdout,
        )
        summary = safe_paths[:MAX_CHANGED_PATHS]
        push_blocker = _push_blocker(
            branch=status.branch,
            detached=status.detached,
            head=head,
            remote=remote,
        )
        captured_at = (
            self._clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        )
        return EnvironmentSnapshot(
            provider_id=self.descriptor.id,
            repository_root=str(repository_path),
            worktree_root=str(worktree_path),
            branch=status.branch,
            detached=status.detached,
            head=head,
            base_identity=base_identity,
            upstream=upstream,
            ahead=status.ahead,
            behind=status.behind,
            remote=remote,
            staged_count=status.staged_count,
            unstaged_count=status.unstaged_count,
            untracked_count=status.untracked_count,
            additions=additions,
            deletions=deletions,
            changed_paths=summary,
            changed_paths_truncated=len(safe_paths) > len(summary),
            diff_sha256=diff_sha256,
            captured_at=captured_at,
            push_ready=push_blocker is None,
            push_blocker=push_blocker,
        )

    def _remote_name(
        self,
        root: Path,
        branch: str | None,
        upstream: str | None,
    ) -> str | None:
        remote = None
        if branch is not None:
            remote = self._optional_text(
                root, "config", "--get", f"branch.{branch}.remote"
            )
        if remote in {None, "."} and upstream and "/" in upstream:
            remote = upstream.split("/", 1)[0]
        if remote in {None, "."}:
            remotes = self._optional_text(root, "remote")
            values = tuple(item for item in (remotes or "").splitlines() if item)
            remote = values[0] if len(values) == 1 else None
        if remote is not None and not _is_safe_ref_text(remote):
            return None
        return remote

    def _numstat(
        self, root: Path, head: str | None, paths: tuple[str, ...]
    ) -> tuple[int, int]:
        if head is None or not paths:
            return 0, 0
        result = self._run(
            root,
            "diff",
            "--numstat",
            "--no-renames",
            "-z",
            "HEAD",
            "--",
            *paths,
        )
        additions = 0
        deletions = 0
        for record in result.stdout.split(b"\0"):
            if not record:
                continue
            fields = record.split(b"\t", 2)
            if len(fields) != 3:
                raise EnvironmentCaptureError(
                    "git_output_invalid", "Git numstat output is invalid."
                )
            if fields[0].isdigit():
                additions += int(fields[0])
            if fields[1].isdigit():
                deletions += int(fields[1])
        return additions, deletions

    def _diff_hash(
        self,
        root: Path,
        head: str | None,
        paths: tuple[str, ...],
        untracked_paths: tuple[str, ...],
        status_bytes: bytes,
    ) -> str:
        digest = hashlib.sha256()
        digest.update(b"environment-diff-v1\0")
        digest.update(status_bytes)
        _hash_untracked_files(root, untracked_paths, digest)
        if head is None or not paths:
            return digest.hexdigest()
        command = (
            self._git,
            "--no-optional-locks",
            "-C",
            str(root),
            "diff",
            "--binary",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            "HEAD",
            "--",
            *paths,
        )
        return _hash_command_output(
            command,
            digest=digest,
            timeout=GIT_TIMEOUT_SECONDS,
            max_bytes=MAX_DIFF_HASH_BYTES,
        )

    def _required_text(self, root: Path, *args: str) -> str:
        value = self._optional_text(root, *args)
        if value is None:
            raise EnvironmentCaptureError(
                "not_git_repository", "Workspace is not a supported Git worktree."
            )
        return value

    def _optional_text(self, root: Path, *args: str) -> str | None:
        result = self._run(root, *args, allowed_returncodes=(0, 1, 128))
        if result.returncode != 0:
            return None
        value = result.stdout.decode("utf-8", "replace").strip()
        return value or None

    def _run(
        self,
        root: Path,
        *args: str,
        allowed_returncodes: tuple[int, ...] = (0,),
    ) -> _CommandResult:
        command = (
            self._git,
            "--no-optional-locks",
            "-C",
            str(root),
            *args,
        )
        result = _run_bounded_command(
            command,
            timeout=GIT_TIMEOUT_SECONDS,
            max_output_bytes=MAX_COMMAND_OUTPUT_BYTES,
        )
        if result.returncode not in allowed_returncodes:
            raise EnvironmentCaptureError(
                "git_failed", "Git environment inspection failed."
            )
        return result


def git_environment_provider_plugin() -> EnvironmentProviderPlugin:
    """Return the built-in provider plugin exposed through package metadata."""
    return EnvironmentProviderPlugin(
        descriptor=GIT_ENVIRONMENT_DESCRIPTOR,
        factory=GitEnvironmentProvider,
    )


@dataclass(frozen=True)
class _StatusSnapshot:
    branch: str | None
    detached: bool
    head: str | None
    upstream: str | None
    ahead: int
    behind: int
    staged_count: int
    unstaged_count: int
    untracked_count: int
    paths: tuple[str, ...]
    untracked_paths: tuple[str, ...]


@dataclass(frozen=True)
class _CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


def _parse_status(payload: bytes) -> _StatusSnapshot:
    branch = None
    detached = False
    head = None
    upstream = None
    ahead = 0
    behind = 0
    staged = 0
    unstaged = 0
    untracked = 0
    paths: list[str] = []
    untracked_paths: list[str] = []
    records = payload.split(b"\0")
    index = 0
    while index < len(records):
        raw = records[index]
        index += 1
        if not raw:
            continue
        record = raw.decode("utf-8", "replace")
        if record.startswith("# branch.oid "):
            value = record.removeprefix("# branch.oid ")
            head = value if _HEX_SHA_RE.fullmatch(value) else None
            continue
        if record.startswith("# branch.head "):
            value = record.removeprefix("# branch.head ")
            detached = value == "(detached)"
            branch = None if detached or value == "(initial)" else value
            continue
        if record.startswith("# branch.upstream "):
            upstream = record.removeprefix("# branch.upstream ") or None
            continue
        if record.startswith("# branch.ab "):
            match = re.fullmatch(r"# branch\.ab \+(\d+) -(\d+)", record)
            if match is None:
                raise EnvironmentCaptureError(
                    "git_output_invalid", "Git branch status output is invalid."
                )
            ahead, behind = (int(match.group(1)), int(match.group(2)))
            continue
        if record.startswith(("1 ", "2 ", "u ")):
            fields = record.split(" ")
            xy = fields[1] if len(fields) > 1 else ""
            path_index = (
                8 if record.startswith("1 ") else 9 if record.startswith("2 ") else 10
            )
            if len(xy) != 2 or len(fields) <= path_index:
                raise EnvironmentCaptureError(
                    "git_output_invalid", "Git worktree status output is invalid."
                )
            staged += xy[0] != "."
            unstaged += xy[1] != "."
            paths.append(" ".join(fields[path_index:]))
            if record.startswith("2 "):
                index += 1  # discard the rename source path; destination is canonical
            continue
        if record.startswith("? "):
            untracked += 1
            paths.append(record[2:])
            untracked_paths.append(record[2:])
            continue
        raise EnvironmentCaptureError(
            "git_output_invalid", "Git status output is invalid."
        )
    return _StatusSnapshot(
        branch=branch,
        detached=detached,
        head=head,
        upstream=upstream,
        ahead=ahead,
        behind=behind,
        staged_count=staged,
        unstaged_count=unstaged,
        untracked_count=untracked,
        paths=tuple(paths),
        untracked_paths=tuple(untracked_paths),
    )


def _is_safe_summary_path(value: str) -> bool:
    if not value or len(value) > MAX_PATH_CHARS or "\x00" in value:
        return False
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return False
    lowered = tuple(part.casefold() for part in path.parts)
    if lowered and lowered[0] == "local":
        return False
    for part in lowered:
        if part == ".env" or part.startswith(".env."):
            return False
        if part in _SECRET_FILENAMES or "secret" in part:
            return False
        if part.endswith(_SECRET_SUFFIXES):
            return False
    return not any(ord(character) < 32 or ord(character) == 127 for character in value)


def _push_blocker(
    *, branch: str | None, detached: bool, head: str | None, remote: str | None
) -> str | None:
    if head is None:
        return "unborn_head"
    if detached or branch is None:
        return "detached_head"
    if remote is None:
        return "remote_unavailable"
    return None


def _hash_untracked_files(root: Path, paths: tuple[str, ...], digest: Any) -> None:
    total_bytes = 0
    resolved_root = root.resolve()
    for relative in sorted(paths):
        candidate = root.joinpath(*PurePosixPath(relative).parts)
        try:
            parent = candidate.parent.resolve(strict=True)
            metadata = candidate.lstat()
        except OSError as exc:
            raise EnvironmentCaptureError(
                "snapshot_stale", "Untracked Git state changed during inspection."
            ) from exc
        if not parent.is_relative_to(resolved_root):
            raise EnvironmentCaptureError(
                "path_unsafe", "Untracked Git path leaves the worktree."
            )
        digest.update(b"untracked\0")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        if stat.S_ISLNK(metadata.st_mode):
            try:
                payload = os.fsencode(os.readlink(candidate))
            except OSError as exc:
                raise EnvironmentCaptureError(
                    "snapshot_stale", "Untracked Git state changed during inspection."
                ) from exc
            total_bytes += len(payload)
            if total_bytes > MAX_DIFF_HASH_BYTES:
                raise EnvironmentCaptureError(
                    "diff_limit", "Untracked Git content exceeds the hash limit."
                )
            digest.update(payload)
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise EnvironmentCaptureError(
                "path_unsafe", "Untracked Git path has an unsupported file type."
            )
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(candidate, flags)
        except OSError as exc:
            raise EnvironmentCaptureError(
                "snapshot_stale", "Untracked Git state changed during inspection."
            ) from exc
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
                raise EnvironmentCaptureError(
                    "snapshot_stale", "Untracked Git state changed during inspection."
                )
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_DIFF_HASH_BYTES:
                    raise EnvironmentCaptureError(
                        "diff_limit", "Untracked Git content exceeds the hash limit."
                    )
                digest.update(chunk)
            completed = os.fstat(stream.fileno())
        if (
            completed.st_size != opened.st_size
            or completed.st_mtime_ns != opened.st_mtime_ns
        ):
            raise EnvironmentCaptureError(
                "snapshot_stale", "Untracked Git state changed during inspection."
            )


def _run_bounded_command(
    command: tuple[str, ...], *, timeout: float, max_output_bytes: int
) -> _CommandResult:
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_git_environment(),
    )
    stdout = bytearray()
    stderr = bytearray()
    overflow = threading.Event()

    def drain(stream, target: bytearray) -> None:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                return
            remaining = max_output_bytes + 1 - len(target)
            if remaining > 0:
                target.extend(chunk[:remaining])
            if len(target) > max_output_bytes or len(chunk) > remaining:
                overflow.set()

    threads = (
        threading.Thread(target=drain, args=(process.stdout, stdout), daemon=True),
        threading.Thread(target=drain, args=(process.stderr, stderr), daemon=True),
    )
    for thread in threads:
        thread.start()
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        raise EnvironmentCaptureError(
            "git_timeout", "Git environment inspection timed out."
        ) from exc
    finally:
        for thread in threads:
            thread.join(timeout=1)
    if overflow.is_set():
        raise EnvironmentCaptureError(
            "output_limit", "Git environment inspection exceeded its output limit."
        )
    return _CommandResult(returncode, bytes(stdout), bytes(stderr))


def _hash_command_output(
    command: tuple[str, ...],
    *,
    digest: Any,
    timeout: float,
    max_bytes: int,
) -> str:
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_git_environment(),
    )
    state: dict[str, Any] = {"bytes": 0, "overflow": False}
    stderr = bytearray()

    def hash_stdout() -> None:
        while True:
            chunk = process.stdout.read(65536)
            if not chunk:
                return
            state["bytes"] += len(chunk)
            if state["bytes"] <= max_bytes:
                digest.update(chunk)
            else:
                state["overflow"] = True

    def drain_stderr() -> None:
        while True:
            chunk = process.stderr.read(65536)
            if not chunk:
                return
            remaining = MAX_COMMAND_OUTPUT_BYTES + 1 - len(stderr)
            if remaining > 0:
                stderr.extend(chunk[:remaining])

    threads = (
        threading.Thread(target=hash_stdout, daemon=True),
        threading.Thread(target=drain_stderr, daemon=True),
    )
    for thread in threads:
        thread.start()
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        raise EnvironmentCaptureError(
            "git_timeout", "Git diff hashing timed out."
        ) from exc
    finally:
        for thread in threads:
            thread.join(timeout=1)
    if state["overflow"]:
        raise EnvironmentCaptureError("diff_limit", "Git diff exceeds the hash limit.")
    if returncode != 0:
        raise EnvironmentCaptureError("git_failed", "Git diff hashing failed.")
    return digest.hexdigest()


def _git_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(
        {
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return environment


def _is_safe_ref_text(value: str) -> bool:
    try:
        _validate_bounded_text(value, "ref")
    except ValueError:
        return False
    return True


def _parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("environment captured_at is invalid")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ValueError("environment captured_at is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("environment captured_at is invalid")
    return parsed


def _plugin_identity(plugin: EnvironmentProviderPlugin) -> str:
    payload = {
        "descriptor": {
            "id": plugin.descriptor.id,
            "display_name": plugin.descriptor.display_name,
            "capabilities": plugin.descriptor.capabilities,
            "schema_version": plugin.descriptor.schema_version,
        },
        "factory": _implementation_identity(plugin.factory),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _select_entry_points(all_entry_points: Any, group: str):
    if hasattr(all_entry_points, "select"):
        return all_entry_points.select(group=group)
    return all_entry_points.get(group, ())


def _entry_point_sort_key(entry_point: Any) -> tuple[str, str]:
    return (
        str(getattr(entry_point, "name", "")),
        str(getattr(entry_point, "value", "")),
    )


def _entry_point_identity(
    entry_point: Any, loaded: Any, plugin: EnvironmentProviderPlugin
) -> str:
    value = getattr(entry_point, "value", None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return f"{_implementation_identity(loaded)}:{_plugin_identity(plugin)}"


def _implementation_identity(implementation: Any) -> str:
    module = getattr(implementation, "__module__", type(implementation).__module__)
    qualname = getattr(
        implementation, "__qualname__", type(implementation).__qualname__
    )
    return f"{module}:{qualname}"


def _load_entry_point_plugin(loaded: Any) -> EnvironmentProviderPlugin:
    value = loaded() if callable(loaded) else loaded
    if not isinstance(value, EnvironmentProviderPlugin):
        raise TypeError("environment entry point did not create a provider plugin")
    return value
