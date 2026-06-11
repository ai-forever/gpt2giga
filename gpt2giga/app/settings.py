"""Application settings helpers."""

from dataclasses import dataclass
from typing import Any

from gpt2giga.cli import load_config
from gpt2giga.logger import setup_logger
from gpt2giga.models.config import ProxyConfig


@dataclass(frozen=True)
class CorsSettings:
    """Represent effective CORS settings for the FastAPI app."""

    allow_origins: list[str]
    allow_methods: list[str]
    allow_headers: list[str]
    allow_credentials: bool


def load_app_config(config: ProxyConfig | None = None) -> ProxyConfig:
    """Return an explicit config or load it from CLI/env settings."""
    if config is not None:
        return config
    return load_config()


def is_prod_mode(config: ProxyConfig) -> bool:
    """Return whether the app is running in production mode."""
    return config.proxy_settings.mode == "PROD"


def is_auth_required(config: ProxyConfig) -> bool:
    """Return whether API-key auth must be enabled."""
    return config.proxy_settings.enable_api_key_auth or is_prod_mode(config)


def validate_app_config(config: ProxyConfig) -> None:
    """Validate application-level configuration constraints."""
    if is_auth_required(config) and not config.proxy_settings.api_key:
        raise RuntimeError(
            "API key must be configured when auth is enabled or MODE=PROD "
            "(set GPT2GIGA_API_KEY / --proxy.api-key)."
        )


def build_cors_settings(config: ProxyConfig) -> CorsSettings:
    """Build effective CORS settings from proxy configuration."""
    proxy_settings = config.proxy_settings
    allow_origins = proxy_settings.cors_allow_origins
    allow_methods = proxy_settings.cors_allow_methods
    allow_headers = proxy_settings.cors_allow_headers
    allow_credentials = True

    if is_prod_mode(config):
        # In PROD, deny wildcard CORS and disable credentials to reduce browser abuse.
        allow_origins = [origin for origin in allow_origins if origin != "*"]
        allow_methods = [method for method in allow_methods if method != "*"]
        allow_headers = [header for header in allow_headers if header != "*"]
        if not allow_methods:
            allow_methods = ["GET", "POST", "OPTIONS"]
        if not allow_headers:
            allow_headers = ["authorization", "content-type", "x-api-key"]
        allow_credentials = False

    return CorsSettings(
        allow_origins=allow_origins,
        allow_methods=allow_methods,
        allow_headers=allow_headers,
        allow_credentials=allow_credentials,
    )


def setup_app_logger(config: ProxyConfig) -> Any:
    """Configure and return the application logger."""
    proxy_settings = config.proxy_settings
    return setup_logger(
        log_level=proxy_settings.log_level,
        log_file=proxy_settings.log_filename,
        max_bytes=proxy_settings.log_max_size,
        enable_redaction=proxy_settings.log_redact_sensitive,
    )
