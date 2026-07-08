"""Attachment limits, path validation, and deny-list helpers."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
import subprocess
from typing import Any

from gpt2giga.harness.project import DEFAULT_ATTACHMENT_IGNORE

DEFAULT_MAX_FILE_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES_PER_RUN = 100 * 1024 * 1024
SECRET_ATTACHMENT_PATTERNS = (
    ".env",
    ".env.*",
    "**/.env",
    "**/.env.*",
    ".git/**",
    "**/.git/**",
    ".ssh/**",
    "**/.ssh/**",
    "*.cer",
    "*.crt",
    "*.der",
    "*.key",
    "*.p12",
    "*.pem",
    "*.pfx",
    "*credentials*.json",
    "*private-key*",
    "*service-account*.json",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
)


class AttachmentValidationError(ValueError):
    """Raised when an attachment violates safety or size policy."""


@dataclass(frozen=True)
class AttachmentLimits:
    """Configurable safety limits for attachment ingestion."""

    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    max_total_bytes_per_run: int = DEFAULT_MAX_TOTAL_BYTES_PER_RUN
    allow_images: bool = True
    allow_documents: bool = True
    allow_binary: bool = False
    respect_gitignore: bool = True
    ignore: tuple[str, ...] = DEFAULT_ATTACHMENT_IGNORE


def limits_from_project_settings(settings: Any) -> AttachmentLimits:
    """Build byte-based limits from a project attachment settings object."""
    return AttachmentLimits(
        max_file_bytes=_mb_to_bytes(getattr(settings, "max_file_mb", 25)),
        max_total_bytes_per_run=_mb_to_bytes(
            getattr(settings, "max_total_mb_per_run", 100)
        ),
        allow_images=bool(getattr(settings, "allow_images", True)),
        allow_documents=bool(getattr(settings, "allow_documents", True)),
        allow_binary=bool(getattr(settings, "allow_binary", False)),
        respect_gitignore=bool(getattr(settings, "respect_gitignore", True)),
        ignore=tuple(str(item) for item in getattr(settings, "ignore", ())),
    )


def safe_upload_filename(filename: str, limits: AttachmentLimits) -> str:
    """Return a safe basename for a browser-uploaded file."""
    normalized = filename.replace("\\", "/")
    name = PurePosixPath(normalized).name.strip()
    if not name or name in {".", ".."}:
        raise AttachmentValidationError("Attachment filename is empty")
    validate_denied_path(name, limits)
    return name


def normalize_workspace_file(
    workspace_root: str | Path,
    requested_path: str | Path,
    limits: AttachmentLimits,
) -> tuple[Path, str]:
    """Resolve a workspace file reference and return absolute/relative paths."""
    root = Path(workspace_root).expanduser().resolve()
    raw_path = Path(requested_path).expanduser()
    absolute = raw_path if raw_path.is_absolute() else root / raw_path
    resolved = absolute.resolve()
    if not _is_relative_to(resolved, root):
        raise AttachmentValidationError("Workspace attachment path escapes workspace")
    if not resolved.exists():
        raise AttachmentValidationError("Workspace attachment does not exist")
    if not resolved.is_file():
        raise AttachmentValidationError("Workspace attachment is not a file")
    relative = resolved.relative_to(root).as_posix()
    validate_denied_path(relative, limits)
    if limits.respect_gitignore and is_git_ignored(root, relative):
        raise AttachmentValidationError("Workspace attachment is ignored by git")
    return resolved, relative


def validate_denied_path(path: str, limits: AttachmentLimits) -> None:
    """Reject obvious secrets and ignored attachment paths."""
    if is_denied_path(path, limits):
        raise AttachmentValidationError("Attachment path is denied by safety policy")


def is_denied_path(path: str, limits: AttachmentLimits) -> bool:
    """Return whether a path matches configured or mandatory deny patterns."""
    normalized = path.replace("\\", "/").strip().lstrip("/")
    if not normalized:
        return True
    lower = normalized.lower()
    basename = PurePosixPath(lower).name
    for pattern in _deny_patterns(limits):
        candidate = pattern.replace("\\", "/").lower()
        if fnmatch(lower, candidate) or fnmatch(basename, candidate):
            return True
    return False


def validate_size(
    size_bytes: int,
    *,
    current_total_bytes: int,
    limits: AttachmentLimits,
) -> None:
    """Reject files or staged totals that exceed attachment limits."""
    if size_bytes < 0:
        raise AttachmentValidationError("Attachment size is invalid")
    if size_bytes > limits.max_file_bytes:
        raise AttachmentValidationError("Attachment exceeds max file size")
    if current_total_bytes + size_bytes > limits.max_total_bytes_per_run:
        raise AttachmentValidationError("Attachments exceed max total size")


def is_git_ignored(workspace_root: Path, relative_path: str) -> bool:
    """Return whether git check-ignore marks a path as ignored."""
    try:
        result = subprocess.run(
            (
                "git",
                "-C",
                str(workspace_root),
                "check-ignore",
                "--quiet",
                "--",
                relative_path,
            ),
            check=False,
            capture_output=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _deny_patterns(limits: AttachmentLimits) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*limits.ignore, *SECRET_ATTACHMENT_PATTERNS)))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _mb_to_bytes(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 1
    return max(parsed, 1) * 1024 * 1024
