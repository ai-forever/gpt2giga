"""Application settings helpers."""

from dataclasses import dataclass
import os
from typing import Any

from gpt2giga.cli import load_config
from gpt2giga.logger import setup_logger
from gpt2giga.models.config import ProxyConfig
from gpt2giga.protocols.normalized import BRIDGE_LOSS_MATRIX_V1
from gpt2giga.providers.profiles import (
    LoadedProviderProfileSet,
    ProviderModelAlias,
    ProviderPolicyCatalog,
    ProviderProfile,
    ProviderProfileConfig,
    ProviderRegistry,
    ProviderSupportStatus,
    load_provider_profiles,
    select_provider_config_path,
)


DEFAULT_PROVIDER_POLICIES = ProviderPolicyCatalog(
    network_policy_refs=frozenset(
        {
            "loopback-development",
            "public-anthropic",
            "public-gemini",
            "public-gigachat",
            "public-openai",
        }
    ),
    tls_policy_refs=frozenset({"system-default"}),
)


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


def build_provider_registry(
    config: ProxyConfig,
    *,
    environ: dict[str, str] | None = None,
    policies: ProviderPolicyCatalog = DEFAULT_PROVIDER_POLICIES,
) -> ProviderRegistry:
    """Build the one immutable provider registry before the app can serve."""
    environment = os.environ if environ is None else environ
    path = select_provider_config_path(
        config.provider_config_path,
        environ=environment,
    )
    if path is not None:
        if config.proxy_settings.legacy_responses:
            raise RuntimeError(
                "Legacy Responses mode cannot be combined with a provider config."
            )
        loaded = load_provider_profiles(path, environ=environment, policies=policies)
    else:
        loaded = _synthesized_gigachat_profiles(config)
    return ProviderRegistry(
        loaded,
        loss_matrix_revision=BRIDGE_LOSS_MATRIX_V1.revision,
    )


def _synthesized_gigachat_profiles(config: ProxyConfig) -> LoadedProviderProfileSet:
    """Preserve the config-free installation as one explicit GigaChat route."""
    upstream_model = config.gigachat_settings.model or "GigaChat"
    profile = ProviderProfile(
        profile_id="legacy-gigachat",
        provider_kind="gigachat",
        base_url=str(config.gigachat_settings.base_url),
        credential_env="GIGACHAT_CREDENTIALS",
        network_policy_ref="public-gigachat",
        tls_policy_ref="system-default",
        models=(
            ProviderModelAlias(
                public_alias=upstream_model,
                upstream_model=upstream_model,
                capability_profile="legacy-gigachat-v1",
                support_status=ProviderSupportStatus.STABLE,
            ),
        ),
    )
    return LoadedProviderProfileSet(
        config=ProviderProfileConfig(profiles=(profile,)),
        _credentials={},
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
            allow_headers = [
                "authorization",
                "content-type",
                "x-api-key",
                "x-goog-api-key",
            ]
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
