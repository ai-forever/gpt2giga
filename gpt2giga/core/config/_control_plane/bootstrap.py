"""Bootstrap token and claim-state helpers for control-plane setup."""

from __future__ import annotations

import secrets
from typing import Any

from gpt2giga.core.config.settings import ProxyConfig, ProxySettings

from .paths import (
    ensure_control_plane_dir,
    get_control_plane_bootstrap_state_file,
    get_control_plane_bootstrap_token_file,
    is_control_plane_persistence_enabled,
    read_json,
    utc_now,
    write_json,
)


def load_bootstrap_token(
    *,
    create: bool,
    config: ProxyConfig | ProxySettings | None = None,
) -> str | None:
    """Load or lazily create the bootstrap token used for first-run admin access."""
    if not is_control_plane_persistence_enabled(config):
        return None
    token_file = get_control_plane_bootstrap_token_file()
    if token_file.exists():
        token = token_file.read_text(encoding="utf-8").strip()
        return token or None
    if not create:
        return None

    ensure_control_plane_dir()
    token = secrets.token_urlsafe(24)
    token_file.write_text(token + "\n", encoding="utf-8")
    try:
        import os

        os.chmod(token_file, 0o600)
    except OSError:
        pass
    return token


def clear_bootstrap_token() -> None:
    """Remove the bootstrap token once first-run setup is complete."""
    try:
        get_control_plane_bootstrap_token_file().unlink(missing_ok=True)
    except OSError:
        pass


def load_bootstrap_state(
    config: ProxyConfig | ProxySettings | None = None,
) -> dict[str, Any]:
    """Load persisted first-run claim metadata."""
    if not is_control_plane_persistence_enabled(config):
        return {
            "claimed_at": None,
            "operator_label": None,
            "claimed_via": None,
            "claimed_from": None,
        }
    path = get_control_plane_bootstrap_state_file()
    if not path.exists():
        return {
            "claimed_at": None,
            "operator_label": None,
            "claimed_via": None,
            "claimed_from": None,
        }

    payload = read_json(path)
    return {
        "claimed_at": payload.get("claimed_at"),
        "operator_label": payload.get("operator_label"),
        "claimed_via": payload.get("claimed_via"),
        "claimed_from": payload.get("claimed_from"),
    }


def is_admin_instance_claimed(
    config: ProxyConfig | ProxySettings | None = None,
) -> bool:
    """Return whether the first-run admin bootstrap has been claimed."""
    return bool(load_bootstrap_state(config=config).get("claimed_at"))


def claim_admin_instance(
    *,
    operator_label: str | None = None,
    claimed_via: str | None = None,
    claimed_from: str | None = None,
    config: ProxyConfig | ProxySettings | None = None,
) -> dict[str, Any]:
    """Persist the first operator claim for the current instance."""
    if not is_control_plane_persistence_enabled(config):
        raise RuntimeError("Control-plane persistence is disabled")

    existing = load_bootstrap_state(config=config)
    if existing.get("claimed_at"):
        return existing

    ensure_control_plane_dir()
    payload = {
        "claimed_at": utc_now(),
        "operator_label": operator_label or None,
        "claimed_via": claimed_via or None,
        "claimed_from": claimed_from or None,
    }
    write_json(get_control_plane_bootstrap_state_file(), payload)
    return payload
