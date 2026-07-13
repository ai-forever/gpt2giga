"""Workspace helpers for external agent harnesses and project file references."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Any

from gpt2giga_harness.attachments.limits import (
    AttachmentLimits,
    AttachmentValidationError,
    is_denied_path,
    is_git_ignored,
    normalize_workspace_file,
    validate_size,
)
from gpt2giga_harness.attachments.mime import (
    detect_attachment_kind,
    detect_mime_type,
)
from gpt2giga_harness.safe_paths import resolve_operator_path


def resolve_workspace(value: str | None) -> str | None:
    """Resolve an optional workspace path for subprocess cwd."""
    if value is None:
        return None
    return str(resolve_operator_path(value))


def workspace_tree(
    workspace_root: str | Path,
    *,
    query: str | None = None,
    limits: AttachmentLimits = AttachmentLimits(),
    result_limit: int = 50,
) -> list[dict[str, Any]]:
    """Return safe workspace files matching a lightweight query."""
    root = Path(workspace_root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise AttachmentValidationError("Workspace is not a directory")
    normalized_query = (query or "").strip().lower().lstrip("@")
    results: list[dict[str, Any]] = []
    git_files = _git_workspace_files(root)
    if git_files is not None:
        for relative in git_files:
            if _skip_relative(root, relative, limits, check_gitignore=False):
                continue
            if normalized_query and normalized_query not in relative.lower():
                continue
            try:
                metadata = workspace_file_metadata(root, relative, limits=limits)
            except AttachmentValidationError:
                continue
            results.append(metadata)
            if len(results) >= result_limit:
                return results
        return results
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if not _skip_path(root, current / dirname, limits, is_dir=True)
        ]
        for filename in filenames:
            path = current / filename
            if _skip_path(root, path, limits, is_dir=False):
                continue
            relative = path.relative_to(root).as_posix()
            if normalized_query and normalized_query not in relative.lower():
                continue
            try:
                metadata = workspace_file_metadata(root, relative, limits=limits)
            except AttachmentValidationError:
                continue
            results.append(metadata)
            if len(results) >= result_limit:
                return results
    return results


def workspace_file_metadata(
    workspace_root: str | Path,
    path: str | Path,
    *,
    limits: AttachmentLimits = AttachmentLimits(),
) -> dict[str, Any]:
    """Return safe metadata for one workspace file without exposing contents."""
    resolved, relative = normalize_workspace_file(workspace_root, path, limits)
    size = resolved.stat().st_size
    validate_size(size, current_total_bytes=0, limits=limits)
    sample = _read_sample(resolved)
    mime_type = detect_mime_type(relative, None, sample)
    kind = detect_attachment_kind(relative, mime_type, sample)
    return {
        "path": relative,
        "name": Path(relative).name,
        "mime_type": mime_type,
        "kind": kind.value,
        "size_bytes": size,
    }


def _skip_path(
    root: Path,
    path: Path,
    limits: AttachmentLimits,
    *,
    is_dir: bool,
) -> bool:
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        return True
    denied_path = f"{relative}/" if is_dir else relative
    if is_denied_path(denied_path, limits):
        return True
    if not is_dir and limits.respect_gitignore and is_git_ignored(root, relative):
        return True
    return False


def _skip_relative(
    root: Path,
    relative: str,
    limits: AttachmentLimits,
    *,
    check_gitignore: bool,
) -> bool:
    if is_denied_path(relative, limits):
        return True
    path = (root / relative).resolve()
    if not path.is_file():
        return True
    if check_gitignore and limits.respect_gitignore and is_git_ignored(root, relative):
        return True
    return False


def _git_workspace_files(root: Path) -> tuple[str, ...] | None:
    try:
        result = subprocess.run(
            (
                "git",
                "-C",
                str(root),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


def _read_sample(path: Path, limit: int = 8192) -> bytes:
    with path.open("rb") as handle:
        return handle.read(limit)
