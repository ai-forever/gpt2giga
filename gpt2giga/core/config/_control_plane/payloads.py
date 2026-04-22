"""Payload loading, override application, and persistence helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gpt2giga.core.config.settings import GigaChatCLI, ProxyConfig, ProxySettings

from .crypto import decrypt_secret_map, encrypt_secret_payload, load_fernet
from .paths import (
    CONTROL_PLANE_VERSION,
    ensure_control_plane_dir,
    get_control_plane_file,
    has_persisted_control_plane,
    is_control_plane_persistence_enabled,
    read_json,
    utc_now,
    write_json,
)
from .revisions import (
    MAX_CONTROL_PLANE_REVISIONS,
    list_control_plane_revisions,
    new_revision_id,
    write_control_plane_revision,
)
from .status import is_control_plane_setup_complete

_PROXY_SECRET_FIELDS = {"api_key", "scoped_api_keys"}
_GIGACHAT_SECRET_FIELDS = {
    "access_token",
    "credentials",
    "password",
    "key_file_password",
}
_PROXY_FIELDS = set(ProxySettings.model_fields)
_GIGACHAT_FIELDS = set(GigaChatCLI.model_fields)


def load_control_plane_payload(
    config: ProxyConfig | ProxySettings | None = None,
) -> dict[str, Any]:
    """Load the raw control-plane payload from disk."""
    empty_payload = {
        "version": CONTROL_PLANE_VERSION,
        "proxy": {},
        "gigachat": {},
        "secrets": {"proxy": {}, "gigachat": {}},
        "managed": {"proxy": [], "gigachat": []},
        "change": {},
        "revision_id": None,
        "updated_at": None,
    }
    if not is_control_plane_persistence_enabled(config):
        return empty_payload

    path = get_control_plane_file()
    if not path.exists():
        return empty_payload

    payload = read_json(path)
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
    for revision in list_control_plane_revisions(limit=MAX_CONTROL_PLANE_REVISIONS):
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
        decrypt_secret_map(
            secrets_section.get("proxy"),
            secret_fields=_PROXY_SECRET_FIELDS,
        )
    )
    gigachat.update(
        decrypt_secret_map(
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
    env_path: str | Path | None = None,
) -> ProxyConfig:
    """Build a validated runtime config from a persisted control-plane payload."""
    proxy_overrides, gigachat_overrides = load_control_plane_overrides_from_payload(
        payload
    )
    proxy = ProxySettings.model_validate(proxy_overrides)
    gigachat = GigaChatCLI.model_validate(gigachat_overrides)
    return ProxyConfig(
        proxy=proxy,
        gigachat=gigachat,
        env_path=str(env_path) if env_path is not None else None,
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
        proxy=ProxySettings.model_validate(proxy_payload),
        gigachat=GigaChatCLI.model_validate(gigachat_payload),
        env_path=config.env_path,
    )


def _build_control_plane_payload(
    config: ProxyConfig,
    *,
    changed_fields: set[str] | None = None,
    restored_from_revision_id: str | None = None,
) -> dict[str, Any]:
    """Build the encrypted payload written to control-plane storage."""
    fernet = load_fernet(create=True)
    assert fernet is not None

    proxy = config.proxy_settings.model_dump()
    gigachat = config.gigachat_settings.model_dump()

    proxy_secrets = {
        field: encrypt_secret_payload(fernet, proxy.pop(field))
        for field in _PROXY_SECRET_FIELDS
        if proxy.get(field) not in (None, "", [])
    }
    gigachat_secrets = {
        field: encrypt_secret_payload(fernet, gigachat.pop(field))
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
        "revision_id": new_revision_id(),
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
        "updated_at": utc_now(),
    }


def persist_control_plane_config(
    config: ProxyConfig,
    *,
    changed_fields: set[str] | None = None,
    restored_from_revision_id: str | None = None,
) -> Path:
    """Persist the current runtime config for future UI-managed startups."""
    if not is_control_plane_persistence_enabled(config):
        raise RuntimeError("Control-plane persistence is disabled")

    from .bootstrap import clear_bootstrap_token

    ensure_control_plane_dir()
    payload = _build_control_plane_payload(
        config,
        changed_fields=changed_fields,
        restored_from_revision_id=restored_from_revision_id,
    )
    path = get_control_plane_file()
    write_json(path, payload)
    write_control_plane_revision(payload)
    if is_control_plane_setup_complete(config):
        clear_bootstrap_token()
    return path
