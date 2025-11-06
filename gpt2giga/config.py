from typing import Optional, Literal

from gigachat.pydantic_v1 import BaseSettings
from gigachat.settings import Settings as GigachatSettings
from pydantic.v1 import Field


class ProxySettings(BaseSettings):
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
    enable_images: bool = Field(
        default=True, description="Включить загрузку изображений"
    )

    log_level: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = Field(
        default="INFO", description="log verbosity level"
    )
    log_filename: str = Field(default="gpt2giga.log", description="Имя лог файла")
    log_max_size: int = Field(
        default=10 * 1024 * 1024, description="максимальный размер файла в байтах"
    )
    enable_api_key_auth: bool = Field(
        default=False,
        description="Нужно ли закрыть доступ к эндпоинтам (требовать API-ключ)",
    )
    api_key: Optional[str] = Field(
        default=None,
        description="API ключ для защиты эндпоинтов (если enable_api_key_auth=True)",
    )
    env_path: Optional[str] = Field(None, description="Путь к .env файлу")

    class Config:
        env_prefix = "gpt2giga_"
        case_sensitive = False


class ProxyConfig(BaseSettings):
    """Конфигурация прокси-сервера"""

    proxy_settings: ProxySettings = Field(default_factory=ProxySettings)
    gigachat_settings: GigachatSettings = Field(default_factory=GigachatSettings)
