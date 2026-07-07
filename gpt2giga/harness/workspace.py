"""Workspace helpers for external agent harnesses."""

from __future__ import annotations

from pathlib import Path


def resolve_workspace(value: str | None) -> str | None:
    """Resolve an optional workspace path for subprocess cwd."""
    if value is None:
        return None
    return str(Path(value).expanduser().resolve())
