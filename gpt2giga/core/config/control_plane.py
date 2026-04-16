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
_DISABLE_PERSIST_ENV_NAMES = ("GPT2GIGA_DISABLE_PERSIST", "DISABLE_PERSIST")
_CONTROL_FILE_NAME = "control-plane.json"
_CONTROL_KEY_FILE_NAME = "control-plane.key"
_BOOTSTRAP_TOKEN_FILE_NAME = "bootstrap-token"
_BOOTSTRAP_STATE_FILE_NAME = "bootstrap-state.json"
_REVISIONS_DIR_NAME = "revisions"
_MAX_REVISIONS = 12
_PROXY_SECRET_FIELDS = {"api_key", "scoped_api_keys"}
_GIGACHAT_SECRET_FIELDS = {
    "access_token",
    "credentials",
    "password",
    "key_file_password",
}
_PROXY_FIELDS = set(ProxySettings.model_fields)
_GIGACHAT_FIELDS = set(GigaChatCLI.model_fields)


def _utc_now() -> str:
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

    payload = _read_json(path)
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

    _ensure_control_plane_dir()
    payload = {
        "claimed_at": _utc_now(),
        "operator_label": operator_label or None,
        "claimed_via": claimed_via or None,
        "claimed_from": claimed_from or None,
    }
    _write_json(get_control_plane_bootstrap_state_file(), payload)
    return payload


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


def load_control_plane_payload(
    config: ProxyConfig | ProxySettings | None = None,
) -> dict[str, Any]:
    """Load the raw control-plane payload from disk."""
    if not is_control_plane_persistence_enabled(config):
        return {
            "version": CONTROL_PLANE_VERSION,
            "proxy": {},
            "gigachat": {},
            "secrets": {"proxy": {}, "gigachat": {}},
            "managed": {"proxy": [], "gigachat": []},
            "change": {},
            "revision_id": None,
            "updated_at": None,
        }

    path = get_control_plane_file()
    if not path.exists():
        return {
            "version": CONTROL_PLANE_VERSION,
            "proxy": {},
            "gigachat": {},
            "secrets": {"proxy": {}, "gigachat": {}},
            "managed": {"proxy": [], "gigachat": []},
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
    payload.setdefault("managed", {})
    payload["managed"].setdefault("proxy", [])
    payload["managed"].setdefault("gigachat", [])
    payload.setdefault("change", {})
    payload.setdefault("revision_id", None)
    payload.setdefault("updated_at", None)
    return payload


def _coerce_managed_fields(
    values: Any,
    *,
    allowed_fields: set[str],
) -> set[str]:
    """Normalize a stored managed-fields list into a validated field set."""
    if not isinstance(values, list):
        return set()
    return {
        str(value)
        for value in values
        if isinstance(value, str) and str(value) in allowed_fields
    }


def _split_section_fields(field_names: set[str]) -> tuple[set[str], set[str]]:
    """Split a flat field-name set into proxy and GigaChat sections."""
    return (
        {field for field in field_names if field in _PROXY_FIELDS},
        {field for field in field_names if field in _GIGACHAT_FIELDS},
    )


def _load_managed_fields_from_payload(
    payload: dict[str, Any],
    *,
    infer_legacy: bool,
) -> tuple[set[str], set[str]]:
    """Return the proxy/GigaChat fields that should override runtime env."""
    managed = payload.get("managed")
    if isinstance(managed, dict):
        proxy_fields = _coerce_managed_fields(
            managed.get("proxy"),
            allowed_fields=_PROXY_FIELDS,
        )
        gigachat_fields = _coerce_managed_fields(
            managed.get("gigachat"),
            allowed_fields=_GIGACHAT_FIELDS,
        )
        if proxy_fields or gigachat_fields:
            return proxy_fields, gigachat_fields

    if not infer_legacy:
        return set(), set()

    legacy_fields = set(payload.get("change", {}).get("changed_fields") or [])
    for revision in list_control_plane_revisions(limit=_MAX_REVISIONS):
        legacy_fields.update(revision.get("change", {}).get("changed_fields") or [])

    secrets_section = payload.get("secrets") or {}
    legacy_fields.update(
        field
        for field, token in (secrets_section.get("proxy") or {}).items()
        if token and field in _PROXY_SECRET_FIELDS
    )
    legacy_fields.update(
        field
        for field, token in (secrets_section.get("gigachat") or {}).items()
        if token and field in _GIGACHAT_SECRET_FIELDS
    )
    return _split_section_fields(legacy_fields)


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
    if not is_control_plane_persistence_enabled(config):
        return config
    if not has_persisted_control_plane(config):
        return config

    payload = load_control_plane_payload(config=config)
    proxy_managed_fields, gigachat_managed_fields = _load_managed_fields_from_payload(
        payload,
        infer_legacy=True,
    )
    proxy_overrides, gigachat_overrides = load_control_plane_overrides_from_payload(
        payload
    )
    proxy_payload = config.proxy_settings.model_dump()
    proxy_payload.update(
        {
            field: proxy_overrides[field]
            for field in proxy_managed_fields
            if field in proxy_overrides
        }
    )
    gigachat_payload = config.gigachat_settings.model_dump()
    gigachat_payload.update(
        {
            field: gigachat_overrides[field]
            for field in gigachat_managed_fields
            if field in gigachat_overrides
        }
    )

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
    persistence_enabled = is_control_plane_persistence_enabled(config)
    storage_ready = not persistence_enabled or has_persisted_control_plane(config)
    return storage_ready and is_gigachat_ready(config) and is_security_ready(config)


def requires_admin_bootstrap(config: ProxyConfig) -> bool:
    """Return whether PROD admin access must stay in bootstrap mode."""
    if not is_control_plane_persistence_enabled(config):
        return False
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

    previous_payload = (
        load_control_plane_payload(config=config)
        if has_persisted_control_plane(config)
        else {}
    )
    managed_proxy_fields, managed_gigachat_fields = _load_managed_fields_from_payload(
        previous_payload,
        infer_legacy=True,
    )
    if changed_fields is None:
        managed_proxy_fields = set(_PROXY_FIELDS)
        managed_gigachat_fields = set(_GIGACHAT_FIELDS)
    else:
        changed_proxy_fields, changed_gigachat_fields = _split_section_fields(
            set(changed_fields)
        )
        managed_proxy_fields.update(changed_proxy_fields)
        managed_gigachat_fields.update(changed_gigachat_fields)

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
        "managed": {
            "proxy": sorted(managed_proxy_fields),
            "gigachat": sorted(managed_gigachat_fields),
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
        payload = _read_json(path)
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
    payload = _read_json(path)
    payload.setdefault("revision_id", revision_id)
    payload.setdefault("managed", {"proxy": [], "gigachat": []})
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
    if not is_control_plane_persistence_enabled(config):
        raise RuntimeError("Control-plane persistence is disabled")

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
    runtime_store = proxy.runtime_store
    persistence_enabled = is_control_plane_persistence_enabled(config)
    payload = load_control_plane_payload(config=config)
    bootstrap_state = load_bootstrap_state(config=config)
    persisted = has_persisted_control_plane(config)
    gigachat_ready = is_gigachat_ready(config)
    security_ready = is_security_ready(config)
    storage_ready = not persistence_enabled or persisted
    setup_complete = storage_ready and gigachat_ready and security_ready
    bootstrap_required = requires_admin_bootstrap(config)
    bootstrap_token = load_bootstrap_token(create=bootstrap_required, config=config)
    claimed = bool(bootstrap_state.get("claimed_at"))
    claim_required = bootstrap_required
    claim_ready = claimed or not claim_required

    warnings: list[str] = []
    if not persistence_enabled:
        warnings.append(
            "Control-plane persistence is disabled. Runtime config loads only from .env "
            "and process environment variables; admin save and rollback actions are unavailable."
        )
    elif not persisted:
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
    if not runtime_store.durable:
        warnings.append(
            "Runtime store backend is memory. Stateful metadata and recent events are not durable."
        )
    if bootstrap_required:
        if not claimed:
            warnings.append(
                "Instance has not been claimed yet. The first operator should claim it before continuing setup."
            )
        warnings.append(
            "PROD bootstrap mode is active. Admin setup is limited to localhost or the bootstrap token until setup is complete."
        )

    return {
        "persistence_enabled": persistence_enabled,
        "disable_persist": not persistence_enabled,
        "persisted": persisted,
        "path": str(get_control_plane_file()) if persistence_enabled else None,
        "key_path": str(get_control_plane_key_file()) if persistence_enabled else None,
        "updated_at": payload.get("updated_at"),
        "gigachat_ready": gigachat_ready,
        "security_ready": security_ready,
        "global_api_key_configured": proxy.api_key is not None,
        "scoped_api_keys_configured": len(proxy.scoped_api_keys),
        "setup_complete": setup_complete,
        "claim": {
            "required": claim_required,
            "claimed": claimed,
            "claimed_at": bootstrap_state.get("claimed_at"),
            "operator_label": bootstrap_state.get("operator_label"),
            "claimed_via": bootstrap_state.get("claimed_via"),
            "claimed_from": bootstrap_state.get("claimed_from"),
        },
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
                "id": "claim",
                "label": "Claim instance",
                "ready": claim_ready,
                "description": (
                    "Record the first operator that is taking ownership of the bootstrap flow."
                    if claim_required
                    else "Claim flow is only required during PROD first-run bootstrap."
                ),
            },
            {
                "id": "storage",
                "label": "Persist settings",
                "ready": storage_ready,
                "description": (
                    "Write control-plane config to disk for restart-safe bootstrap."
                    if persistence_enabled
                    else "Persistence is disabled; runtime config is sourced only from .env and environment variables."
                ),
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
