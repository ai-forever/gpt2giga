"""Filesystem paths and JSON helpers for control-plane persistence."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gpt2giga.core.config.settings import ProxyConfig, ProxySettings

CONTROL_PLANE_VERSION = 1
CONTROL_PLANE_DIR_ENV = "GPT2GIGA_CONTROL_PLANE_DIR"
_DISABLE_PERSIST_ENV_NAMES = ("GPT2GIGA_DISABLE_PERSIST", "DISABLE_PERSIST")
_CONTROL_FILE_NAME = "control-plane.json"
_CONTROL_KEY_FILE_NAME = "control-plane.key"
_BOOTSTRAP_TOKEN_FILE_NAME = "bootstrap-token"
_BOOTSTRAP_STATE_FILE_NAME = "bootstrap-state.json"
_REVISIONS_DIR_NAME = "revisions"


def utc_now() -> str:
    """Return an RFC3339-like timestamp."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _env_flag_enabled(name: str) -> bool | None:
    value = os.getenv(name)
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes", "on"}


def is_control_plane_persistence_enabled(
    config: ProxyConfig | ProxySettings | None = None,
) -> bool:
    """Return whether disk-backed control-plane persistence is enabled."""
    proxy_settings = getattr(config, "proxy_settings", config)
    if proxy_settings is not None:
        return not bool(getattr(proxy_settings, "disable_persist", False))

    for env_name in _DISABLE_PERSIST_ENV_NAMES:
        raw_flag = _env_flag_enabled(env_name)
        if raw_flag is not None:
            return not raw_flag
    return True


def get_control_plane_dir() -> Path:
    """Resolve the directory used for persisted UI-managed settings."""
    configured = os.getenv(CONTROL_PLANE_DIR_ENV)
    if configured:
        return Path(configured).expanduser()

    xdg_data_home = os.getenv("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home).expanduser() / "gpt2giga"

    return Path.home() / ".local" / "share" / "gpt2giga"


def get_control_plane_file() -> Path:
    """Return the persisted control-plane JSON path."""
    return get_control_plane_dir() / _CONTROL_FILE_NAME


def get_control_plane_key_file() -> Path:
    """Return the local encryption-key path for persisted secrets."""
    return get_control_plane_dir() / _CONTROL_KEY_FILE_NAME


def get_control_plane_bootstrap_token_file() -> Path:
    """Return the bootstrap-token path used for first-run admin access."""
    return get_control_plane_dir() / _BOOTSTRAP_TOKEN_FILE_NAME


def get_control_plane_bootstrap_state_file() -> Path:
    """Return the bootstrap-state path used for first-run claim metadata."""
    return get_control_plane_dir() / _BOOTSTRAP_STATE_FILE_NAME


def get_control_plane_revisions_dir() -> Path:
    """Return the directory containing persisted control-plane revisions."""
    return get_control_plane_dir() / _REVISIONS_DIR_NAME


def has_persisted_control_plane(
    config: ProxyConfig | ProxySettings | None = None,
) -> bool:
    """Return whether a persisted control-plane payload exists."""
    if not is_control_plane_persistence_enabled(config):
        return False
    return get_control_plane_file().exists()


def ensure_control_plane_dir() -> Path:
    """Create the control-plane directory with private permissions."""
    directory = get_control_plane_dir()
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    return directory


def ensure_control_plane_revisions_dir() -> Path:
    """Create the control-plane revisions directory with private permissions."""
    directory = get_control_plane_revisions_dir()
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    return directory


def read_json(path: Path) -> dict[str, Any]:
    """Load a JSON object from disk."""
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError("control-plane payload must be a JSON object")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Persist a JSON object with private permissions."""
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
