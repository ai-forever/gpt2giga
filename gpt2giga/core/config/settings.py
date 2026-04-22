"""Primary runtime settings models."""

from typing import Optional

from gigachat.settings import Settings as GigachatSettings
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from gpt2giga.core.config._settings.access_control import (
    GovernanceLimitSettings,
    ScopedAPIKeySettings,
)
from gpt2giga.core.config._settings.common import (
    GigaChatAPIMode,
    GovernanceLimitScope,
    ProviderName,
)
from gpt2giga.core.config._settings.proxy_mixins import (
    ObservabilityProxySettingsMixin,
    ProviderProxySettingsMixin,
    RuntimeStoreProxySettingsMixin,
    SecurityProxySettingsMixin,
    ServerProxySettingsMixin,
)

__all__ = [
    "GigaChatAPIMode",
    "GigaChatCLI",
    "GovernanceLimitScope",
    "GovernanceLimitSettings",
    "ProviderName",
    "ProxyConfig",
    "ProxySettings",
    "ScopedAPIKeySettings",
]


class ProxySettings(
    ServerProxySettingsMixin,
    ProviderProxySettingsMixin,
    RuntimeStoreProxySettingsMixin,
    ObservabilityProxySettingsMixin,
    SecurityProxySettingsMixin,
    BaseSettings,
):
    """Proxy runtime settings."""

    model_config = SettingsConfigDict(env_prefix="gpt2giga_", case_sensitive=False)


class GigaChatCLI(GigachatSettings):
    """CLI-exposed GigaChat SDK settings."""

    model_config = SettingsConfigDict(env_prefix="gigachat_", case_sensitive=False)


class ProxyConfig(BaseSettings):
    """Конфигурация прокси-сервера gpt2giga."""

    proxy_settings: ProxySettings = Field(default_factory=ProxySettings, alias="proxy")
    gigachat_settings: GigaChatCLI = Field(
        default_factory=GigaChatCLI,
        alias="gigachat",
    )
    env_path: Optional[str] = Field(None, description="Path to .env file")

    model_config = SettingsConfigDict(
        cli_parse_args=True,
        cli_prog_name="gpt2giga",
        cli_kebab_case=True,
        cli_ignore_unknown_args=True,
    )
