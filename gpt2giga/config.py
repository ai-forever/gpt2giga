from typing import Optional, Literal

from gigachat.settings import Settings as GigachatSettings
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from gpt2giga.constants import (
    DEFAULT_MAX_AUDIO_FILE_SIZE_BYTES,
    DEFAULT_MAX_AUDIO_IMAGE_TOTAL_SIZE_BYTES,
    DEFAULT_MAX_IMAGE_FILE_SIZE_BYTES,
    DEFAULT_MAX_TEXT_FILE_SIZE_BYTES,
)


class ProxySettings(BaseSettings):
    mode: Literal["DEV", "PROD"] = Field(
        default="DEV", description="Режим запуска приложения: DEV или PROD"
    )
    host: str = Field(default="localhost", description="Хост для запуска сервера")
    port: int = Field(default=8090, description="Порт для запуска сервера")
    use_https: bool = Field(default=False, description="Использовать ли https")
    https_key_file: Optional[str] = Field(
        default=None, description="Путь до key файла для https"
    )
    https_cert_file: Optional[str] = Field(
        default=None, description="Путь до cert файла https"
    )
    pass_model: bool = Field(
        default=False, description="Передавать модель из запроса в API"
    )
    pass_token: bool = Field(
        default=False, description="Передавать токен из запроса в API"
    )
    embeddings: str = Field(
        default="EmbeddingsGigaR", description="Модель для эмбеддингов"
    )
    cors_allow_origins: list[str] = Field(
        default_factory=lambda: ["*"],
        description="Разрешенные CORS origins",
    )
    cors_allow_methods: list[str] = Field(
        default_factory=lambda: ["*"],
        description="Разрешенные CORS методы",
    )
    cors_allow_headers: list[str] = Field(
        default_factory=lambda: ["*"],
        description="Разрешенные CORS заголовки",
    )
    enable_images: bool = Field(
        default=True, description="Включить загрузку изображений"
    )
    max_audio_file_size_bytes: int = Field(
        default=DEFAULT_MAX_AUDIO_FILE_SIZE_BYTES,
        description="Максимальный размер одного аудиофайла в байтах",
    )
    max_image_file_size_bytes: int = Field(
        default=DEFAULT_MAX_IMAGE_FILE_SIZE_BYTES,
        description="Максимальный размер одного изображения в байтах",
    )
    max_text_file_size_bytes: int = Field(
        default=DEFAULT_MAX_TEXT_FILE_SIZE_BYTES,
        description="Максимальный размер одного текстового файла в байтах",
    )
    max_audio_image_total_size_bytes: int = Field(
        default=DEFAULT_MAX_AUDIO_IMAGE_TOTAL_SIZE_BYTES,
        description="Максимальный суммарный размер аудио и изображений в одном запросе, в байтах",
    )

    log_level: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = Field(
        default="INFO", description="log verbosity level"
    )
    log_filename: str = Field(default="gpt2giga.log", description="Имя лог файла")
    log_max_size: int = Field(
        default=10 * 1024 * 1024, description="максимальный размер файла в байтах"
    )
    log_redact_sensitive: bool = Field(
        default=True,
        description="Маскировать чувствительные поля (api_key, token, password и др.) в логах",
    )
    logs_ip_allowlist: list[str] = Field(
        default_factory=list,
        description="IP-адреса, которым разрешён доступ к /logs* (пусто = без ограничений)",
    )
    enable_api_key_auth: bool = Field(
        default=False,
        description="Нужно ли закрыть доступ к эндпоинтам (требовать API-ключ)",
    )
    api_key: Optional[str] = Field(
        default=None,
        description="API ключ для защиты эндпоинтов (если enable_api_key_auth=True)",
        repr=False,
    )

    @field_validator("mode", mode="before")
    @classmethod
    def normalize_mode(cls, value):
        if isinstance(value, str):
            return value.strip().upper()
        return value

    model_config = SettingsConfigDict(env_prefix="gpt2giga_", case_sensitive=False)


class GigaChatCLI(GigachatSettings):
    model_config = SettingsConfigDict(env_prefix="gigachat_", case_sensitive=False)


class ProxyConfig(BaseSettings):
    """Конфигурация прокси-сервера gpt2giga"""

    proxy_settings: ProxySettings = Field(default_factory=ProxySettings, alias="proxy")
    gigachat_settings: GigaChatCLI = Field(
        default_factory=GigaChatCLI, alias="gigachat"
    )
    env_path: Optional[str] = Field(None, description="Path to .env file")

    model_config = SettingsConfigDict(
        cli_parse_args=True,
        cli_prog_name="gpt2giga",
        cli_kebab_case=True,
        cli_ignore_unknown_args=True,
    )
