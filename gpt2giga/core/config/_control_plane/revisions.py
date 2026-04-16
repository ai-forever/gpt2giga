"""Revision persistence helpers for control-plane snapshots."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from gpt2giga.core.config.settings import ProxyConfig, ProxySettings

from .paths import (
    ensure_control_plane_revisions_dir,
    get_control_plane_revisions_dir,
    is_control_plane_persistence_enabled,
    read_json,
    write_json,
)

MAX_CONTROL_PLANE_REVISIONS = 12


def new_revision_id() -> str:
    """Return a sortable identifier for a persisted config snapshot."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{timestamp}-{secrets.token_hex(4)}"


def write_control_plane_revision(payload: dict[str, Any]) -> None:
    """Persist a revision snapshot alongside the active control-plane payload."""
    revision_id = payload.get("revision_id")
    if not revision_id:
        return

    revisions_dir = ensure_control_plane_revisions_dir()
    write_json(revisions_dir / f"{revision_id}.json", payload)

    revision_files = sorted(revisions_dir.glob("*.json"), reverse=True)
    for stale_file in revision_files[MAX_CONTROL_PLANE_REVISIONS:]:
        try:
            stale_file.unlink()
        except OSError:
            continue


def list_control_plane_revisions(
    limit: int = 10,
    *,
    config: ProxyConfig | ProxySettings | None = None,
) -> list[dict[str, Any]]:
    """Return recent persisted control-plane revisions."""
    if not is_control_plane_persistence_enabled(config):
        return []
    revisions_dir = get_control_plane_revisions_dir()
    if not revisions_dir.exists():
        return []

    payloads: list[dict[str, Any]] = []
    for path in sorted(revisions_dir.glob("*.json"), reverse=True):
        payload = read_json(path)
        payload.setdefault("revision_id", path.stem)
        payload.setdefault("managed", {"proxy": [], "gigachat": []})
        payload.setdefault("change", {})
        payload.setdefault("updated_at", None)
        payloads.append(payload)
        if len(payloads) >= limit:
            break
    return payloads


def load_control_plane_revision_payload(
    revision_id: str,
    *,
    config: ProxyConfig | ProxySettings | None = None,
) -> dict[str, Any]:
    """Load a specific persisted control-plane revision."""
    if not is_control_plane_persistence_enabled(config):
        raise FileNotFoundError(revision_id)
    path = get_control_plane_revisions_dir() / f"{revision_id}.json"
    if not path.exists():
        raise FileNotFoundError(revision_id)
    payload = read_json(path)
    payload.setdefault("revision_id", revision_id)
    payload.setdefault("managed", {"proxy": [], "gigachat": []})
    payload.setdefault("change", {})
    payload.setdefault("updated_at", None)
    return payload
