"""Persistent control-plane configuration for the admin UI."""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from gpt2giga.core.config.settings import GigaChatCLI, ProxyConfig, ProxySettings

CONTROL_PLANE_VERSION = 1
CONTROL_PLANE_DIR_ENV = "GPT2GIGA_CONTROL_PLANE_DIR"
_CONTROL_FILE_NAME = "control-plane.json"
_CONTROL_KEY_FILE_NAME = "control-plane.key"
_BOOTSTRAP_TOKEN_FILE_NAME = "bootstrap-token"
_REVISIONS_DIR_NAME = "revisions"
_MAX_REVISIONS = 12
_PROXY_SECRET_FIELDS = {"api_key", "scoped_api_keys"}
_GIGACHAT_SECRET_FIELDS = {
    "access_token",
    "credentials",
    "password",
    "key_file_password",
}


def _utc_now() -> str:
    """Return an RFC3339-like timestamp."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def get_control_plane_revisions_dir() -> Path:
    """Return the directory containing persisted control-plane revisions."""
    return get_control_plane_dir() / _REVISIONS_DIR_NAME


def has_persisted_control_plane() -> bool:
    """Return whether a persisted control-plane payload exists."""
    return get_control_plane_file().exists()


def _ensure_control_plane_dir() -> Path:
    """Create the control-plane directory with private permissions."""
    directory = get_control_plane_dir()
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    return directory


def _ensure_control_plane_revisions_dir() -> Path:
    """Create the control-plane revisions directory with private permissions."""
    directory = get_control_plane_revisions_dir()
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    return directory


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError("control-plane payload must be a JSON object")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _normalize_secret_value(value: Any) -> Any:
    """Convert Pydantic secret wrappers into JSON-serializable values."""
    if hasattr(value, "get_secret_value"):
        return value.get_secret_value()
    if isinstance(value, dict):
        return {key: _normalize_secret_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_secret_value(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_secret_value(item) for item in value]
    return value


def _new_revision_id() -> str:
    """Return a sortable identifier for a persisted config snapshot."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{timestamp}-{secrets.token_hex(4)}"


def _load_fernet(*, create: bool) -> Fernet | None:
    key_file = get_control_plane_key_file()
    if key_file.exists():
        return Fernet(key_file.read_bytes())
    if not create:
        return None

    _ensure_control_plane_dir()
    key = Fernet.generate_key()
    key_file.write_bytes(key)
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    return Fernet(key)


def load_bootstrap_token(*, create: bool) -> str | None:
    """Load or lazily create the bootstrap token used for first-run admin access."""
    token_file = get_control_plane_bootstrap_token_file()
    if token_file.exists():
        token = token_file.read_text(encoding="utf-8").strip()
        return token or None
    if not create:
        return None

    _ensure_control_plane_dir()
    token = secrets.token_urlsafe(24)
    token_file.write_text(token + "\n", encoding="utf-8")
    try:
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


def _encrypt_secret_payload(fernet: Fernet, value: Any) -> str:
    """Encrypt a JSON-serializable secret payload."""
    encoded = json.dumps(
        _normalize_secret_value(value),
        ensure_ascii=False,
    ).encode("utf-8")
    return fernet.encrypt(encoded).decode("utf-8")


def _decrypt_secret_payload(fernet: Fernet, token: str) -> Any:
    """Decrypt a control-plane secret value."""
    decrypted = fernet.decrypt(token.encode("utf-8"))
    return json.loads(decrypted.decode("utf-8"))


def _decrypt_secret_map(
    encrypted: dict[str, Any] | None,
    *,
    secret_fields: set[str],
) -> dict[str, Any]:
    if not encrypted:
        return {}

    fernet = _load_fernet(create=False)
    if fernet is None:
        raise RuntimeError(
            "Persisted secrets exist but the control-plane key is missing"
        )

    values: dict[str, Any] = {}
    for field in secret_fields:
        token = encrypted.get(field)
        if not token:
            continue
        if not isinstance(token, str):
            raise ValueError(
                f"Encrypted control-plane field `{field}` must be a string"
            )
        try:
            values[field] = _decrypt_secret_payload(fernet, token)
        except InvalidToken as exc:
            raise RuntimeError(
                f"Failed to decrypt persisted control-plane field `{field}`"
            ) from exc
    return values


def load_control_plane_payload() -> dict[str, Any]:
    """Load the raw control-plane payload from disk."""
    path = get_control_plane_file()
    if not path.exists():
        return {
            "version": CONTROL_PLANE_VERSION,
            "proxy": {},
            "gigachat": {},
            "secrets": {"proxy": {}, "gigachat": {}},
            "change": {},
            "revision_id": None,
            "updated_at": None,
        }

    payload = _read_json(path)
    payload.setdefault("version", CONTROL_PLANE_VERSION)
    payload.setdefault("proxy", {})
    payload.setdefault("gigachat", {})
    payload.setdefault("secrets", {})
    payload["secrets"].setdefault("proxy", {})
    payload["secrets"].setdefault("gigachat", {})
    payload.setdefault("change", {})
    payload.setdefault("revision_id", None)
    payload.setdefault("updated_at", None)
    return payload


def load_control_plane_overrides_from_payload(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load decrypted proxy and GigaChat overrides from a raw payload."""
    proxy = dict(payload.get("proxy") or {})
    gigachat = dict(payload.get("gigachat") or {})
    secrets_section = payload.get("secrets") or {}
    proxy.update(
        _decrypt_secret_map(
            secrets_section.get("proxy"),
            secret_fields=_PROXY_SECRET_FIELDS,
        )
    )
    gigachat.update(
        _decrypt_secret_map(
            secrets_section.get("gigachat"),
            secret_fields=_GIGACHAT_SECRET_FIELDS,
        )
    )
    return proxy, gigachat


def load_control_plane_overrides() -> tuple[dict[str, Any], dict[str, Any]]:
    """Load decrypted proxy and GigaChat overrides from control-plane storage."""
    return load_control_plane_overrides_from_payload(load_control_plane_payload())


def build_proxy_config_from_control_plane_payload(
    payload: dict[str, Any],
    *,
    env_path: Path | None = None,
) -> ProxyConfig:
    """Build a validated runtime config from a persisted control-plane payload."""
    proxy_overrides, gigachat_overrides = load_control_plane_overrides_from_payload(
        payload
    )
    proxy = ProxySettings.model_validate(proxy_overrides)
    gigachat = GigaChatCLI.model_validate(gigachat_overrides)
    return ProxyConfig(
        proxy=proxy.model_dump(),
        gigachat=gigachat.model_dump(),
        env_path=env_path,
    )


def apply_control_plane_overrides(config: ProxyConfig) -> ProxyConfig:
    """Overlay persisted UI-managed settings onto the runtime config."""
    if not has_persisted_control_plane():
        return config

    persisted = build_proxy_config_from_control_plane_payload(
        load_control_plane_payload(),
        env_path=config.env_path,
    )
    proxy_payload = config.proxy_settings.model_dump()
    proxy_payload.update(persisted.proxy_settings.model_dump())
    gigachat_payload = config.gigachat_settings.model_dump()
    gigachat_payload.update(persisted.gigachat_settings.model_dump())

    return ProxyConfig(
        proxy=proxy_payload, gigachat=gigachat_payload, env_path=config.env_path
    )


def is_gigachat_ready(config: ProxyConfig) -> bool:
    """Return whether upstream GigaChat auth is configured."""
    gigachat = config.gigachat_settings
    return bool(
        getattr(gigachat, "credentials", None)
        or getattr(gigachat, "access_token", None)
    )


def is_security_ready(config: ProxyConfig) -> bool:
    """Return whether gateway auth is enabled and has at least one usable key."""
    proxy = config.proxy_settings
    return bool(proxy.enable_api_key_auth and (proxy.api_key or proxy.scoped_api_keys))


def is_control_plane_setup_complete(config: ProxyConfig) -> bool:
    """Return whether persisted config, upstream auth and gateway auth are all ready."""
    return (
        has_persisted_control_plane()
        and is_gigachat_ready(config)
        and is_security_ready(config)
    )


def requires_admin_bootstrap(config: ProxyConfig) -> bool:
    """Return whether PROD admin access must stay in bootstrap mode."""
    return config.proxy_settings.mode == "PROD" and not is_control_plane_setup_complete(
        config
    )


def _build_control_plane_payload(
    config: ProxyConfig,
    *,
    changed_fields: set[str] | None = None,
    restored_from_revision_id: str | None = None,
) -> dict[str, Any]:
    """Build the encrypted payload written to control-plane storage."""
    fernet = _load_fernet(create=True)
    assert fernet is not None

    proxy = config.proxy_settings.model_dump()
    gigachat = config.gigachat_settings.model_dump()

    proxy_secrets = {
        field: _encrypt_secret_payload(fernet, proxy.pop(field))
        for field in _PROXY_SECRET_FIELDS
        if proxy.get(field) not in (None, "", [])
    }
    gigachat_secrets = {
        field: _encrypt_secret_payload(fernet, gigachat.pop(field))
        for field in _GIGACHAT_SECRET_FIELDS
        if gigachat.get(field) not in (None, "", [])
    }

    change: dict[str, Any] = {}
    if changed_fields:
        change["changed_fields"] = sorted(changed_fields)
    if restored_from_revision_id:
        change["restored_from_revision_id"] = restored_from_revision_id

    return {
        "version": CONTROL_PLANE_VERSION,
        "revision_id": _new_revision_id(),
        "proxy": proxy,
        "gigachat": gigachat,
        "secrets": {
            "proxy": proxy_secrets,
            "gigachat": gigachat_secrets,
        },
        "change": change,
        "updated_at": _utc_now(),
    }


def _write_control_plane_revision(payload: dict[str, Any]) -> None:
    """Persist a revision snapshot alongside the active control-plane payload."""
    revision_id = payload.get("revision_id")
    if not revision_id:
        return

    revisions_dir = _ensure_control_plane_revisions_dir()
    _write_json(revisions_dir / f"{revision_id}.json", payload)

    revision_files = sorted(revisions_dir.glob("*.json"), reverse=True)
    for stale_file in revision_files[_MAX_REVISIONS:]:
        try:
            stale_file.unlink()
        except OSError:
            continue


def list_control_plane_revisions(limit: int = 10) -> list[dict[str, Any]]:
    """Return recent persisted control-plane revisions."""
    revisions_dir = get_control_plane_revisions_dir()
    if not revisions_dir.exists():
        return []

    payloads: list[dict[str, Any]] = []
    for path in sorted(revisions_dir.glob("*.json"), reverse=True):
        payload = _read_json(path)
        payload.setdefault("revision_id", path.stem)
        payload.setdefault("change", {})
        payload.setdefault("updated_at", None)
        payloads.append(payload)
        if len(payloads) >= limit:
            break
    return payloads


def load_control_plane_revision_payload(revision_id: str) -> dict[str, Any]:
    """Load a specific persisted control-plane revision."""
    path = get_control_plane_revisions_dir() / f"{revision_id}.json"
    if not path.exists():
        raise FileNotFoundError(revision_id)
    payload = _read_json(path)
    payload.setdefault("revision_id", revision_id)
    payload.setdefault("change", {})
    payload.setdefault("updated_at", None)
    return payload


def persist_control_plane_config(
    config: ProxyConfig,
    *,
    changed_fields: set[str] | None = None,
    restored_from_revision_id: str | None = None,
) -> Path:
    """Persist the current runtime config for future UI-managed startups."""
    _ensure_control_plane_dir()
    payload = _build_control_plane_payload(
        config,
        changed_fields=changed_fields,
        restored_from_revision_id=restored_from_revision_id,
    )
    path = get_control_plane_file()
    _write_json(path, payload)
    _write_control_plane_revision(payload)
    if is_control_plane_setup_complete(config):
        clear_bootstrap_token()
    return path


def build_control_plane_status(config: ProxyConfig) -> dict[str, Any]:
    """Return a safe summary of the persisted-control-plane state."""
    proxy = config.proxy_settings
    payload = load_control_plane_payload()
    persisted = has_persisted_control_plane()
    gigachat_ready = is_gigachat_ready(config)
    security_ready = is_security_ready(config)
    setup_complete = persisted and gigachat_ready and security_ready
    bootstrap_required = requires_admin_bootstrap(config)
    bootstrap_token = load_bootstrap_token(create=bootstrap_required)

    warnings: list[str] = []
    if not persisted:
        warnings.append(
            "Control-plane config is not persisted yet. Save setup values to survive restarts."
        )
    if not gigachat_ready:
        warnings.append(
            "GigaChat credentials are missing. Proxy calls will fail until auth is configured."
        )
    if not proxy.enable_api_key_auth:
        warnings.append(
            "Gateway API key auth is disabled. This is convenient for local bring-up but not hardened."
        )
    elif not security_ready:
        warnings.append(
            "Gateway API key auth is enabled, but no global or scoped gateway key is configured."
        )
    if "*" in proxy.cors_allow_origins:
        warnings.append("CORS allows all origins.")
    if proxy.runtime_store_backend == "memory":
        warnings.append(
            "Runtime store backend is memory. Stateful metadata and recent events are not durable."
        )
    if bootstrap_required:
        warnings.append(
            "PROD bootstrap mode is active. Admin setup is limited to localhost or the bootstrap token until setup is complete."
        )

    return {
        "persisted": persisted,
        "path": str(get_control_plane_file()),
        "key_path": str(get_control_plane_key_file()),
        "updated_at": payload.get("updated_at"),
        "gigachat_ready": gigachat_ready,
        "security_ready": security_ready,
        "global_api_key_configured": proxy.api_key is not None,
        "scoped_api_keys_configured": len(proxy.scoped_api_keys),
        "setup_complete": setup_complete,
        "bootstrap": {
            "required": bootstrap_required,
            "allow_localhost": bootstrap_required,
            "allow_token": bootstrap_required,
            "token_configured": bootstrap_token is not None,
            "token_path": (
                str(get_control_plane_bootstrap_token_file())
                if bootstrap_required
                else None
            ),
        },
        "wizard_steps": [
            {
                "id": "storage",
                "label": "Persist settings",
                "ready": persisted,
                "description": "Write control-plane config to disk for restart-safe bootstrap.",
            },
            {
                "id": "gigachat",
                "label": "Configure GigaChat",
                "ready": gigachat_ready,
                "description": "Provide credentials or access token for upstream model calls.",
            },
            {
                "id": "security",
                "label": "Bootstrap security",
                "ready": security_ready,
                "description": "Enable gateway auth and create at least one gateway key.",
            },
            {
                "id": "finish",
                "label": "Ready for operators",
                "ready": setup_complete,
                "description": "Persisted config, upstream auth and gateway auth are all in place.",
            },
        ],
        "warnings": warnings,
    }
