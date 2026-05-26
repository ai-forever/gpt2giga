"""Readiness helpers for control-plane bootstrap."""

from __future__ import annotations

from gpt2giga.core.config.settings import ProxyConfig

from .paths import has_persisted_control_plane, is_control_plane_persistence_enabled


def gigachat_auth_methods(config: ProxyConfig) -> list[str]:
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
    return bool(gigachat_auth_methods(config))


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
