"""Canonical path resolution for operator roots and bounded child paths."""

from __future__ import annotations

import os
from pathlib import Path


class PathBoundaryError(ValueError):
    """Raised when a child path escapes its selected root."""


def resolve_operator_path(value: str | Path) -> Path:
    """Canonicalize a path explicitly selected by the local operator."""
    normalized = os.path.realpath(os.path.expanduser(os.fspath(value)))
    drive, _ = os.path.splitdrive(normalized)
    anchor = f"{drive}{os.sep}"
    if not normalized.startswith(anchor):
        raise PathBoundaryError("Operator path must resolve to an absolute path")
    return Path(normalized)


def resolve_path_within(root: str | Path, value: str | Path) -> Path:
    """Resolve a path and require it to remain below a canonical root."""
    resolved_root = resolve_operator_path(root)
    raw_value = os.path.expanduser(os.fspath(value))
    candidate = (
        raw_value
        if os.path.isabs(raw_value)
        else os.path.join(os.fspath(resolved_root), raw_value)
    )
    normalized = os.path.realpath(candidate)
    root_text = os.fspath(resolved_root)
    if normalized == root_text:
        return resolved_root
    root_prefix = root_text if root_text.endswith(os.sep) else root_text + os.sep
    if not normalized.startswith(root_prefix):
        raise PathBoundaryError("Path escapes its allowed root")
    return Path(normalized)
