"""Readiness and status helpers for control-plane bootstrap."""

from __future__ import annotations

from typing import Any

from gpt2giga.core.config.settings import ProxyConfig

from .bootstrap import load_bootstrap_state, load_bootstrap_token
from .paths import (
    get_control_plane_bootstrap_token_file,
    get_control_plane_file,
    get_control_plane_key_file,
    has_persisted_control_plane,
    is_control_plane_persistence_enabled,
)


def _gigachat_auth_methods(config: ProxyConfig) -> list[str]:
    """Return the configured upstream GigaChat auth methods."""
    gigachat = config.gigachat_settings
    methods: list[str] = []
    if getattr(gigachat, "credentials", None):
        methods.append("credentials")
    if getattr(gigachat, "access_token", None):
        methods.append("access_token")
    if getattr(gigachat, "user", None) and getattr(gigachat, "password", None):
        methods.append("user_password")
    return methods


def is_gigachat_ready(config: ProxyConfig) -> bool:
    """Return whether upstream GigaChat auth is configured."""
    return bool(_gigachat_auth_methods(config))


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


def build_control_plane_status(config: ProxyConfig) -> dict[str, Any]:
    """Return a safe summary of the persisted-control-plane state."""
    from .payloads import load_control_plane_payload

    proxy = config.proxy_settings
    runtime_store = proxy.runtime_store
    persistence_enabled = is_control_plane_persistence_enabled(config)
    payload = load_control_plane_payload(config=config)
    bootstrap_state = load_bootstrap_state(config=config)
    persisted = has_persisted_control_plane(config)
    gigachat_auth_methods = _gigachat_auth_methods(config)
    gigachat_ready = bool(gigachat_auth_methods)
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
        "gigachat_auth_methods": gigachat_auth_methods,
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
