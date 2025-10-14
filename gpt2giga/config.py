from typing import Optional

from gigachat.pydantic_v1 import BaseSettings
from gigachat.settings import Settings as GigachatSettings
from pydantic.v1 import Field


class ProxySettings(BaseSettings):
    host: str = Field(default="localhost", description="Хост для запуска сервера")
    port: int = Field(default=8090, description="Порт для запуска сервера")
    pass_model: bool = Field(default=False, description="Передавать модель из запроса в API")
    pass_token: bool = Field(default=False, description="Передавать токен из запроса в API")
    embeddings: str = Field(default="EmbeddingsGigaR", description="Модель для эмбеддингов")
    verify_ssl_certs: bool = Field(default=False, description="Проверять SSL сертификаты")
    enable_images: bool = Field(default=False, description="Включить загрузку изображений")
    verbose: bool = Field(default=False, description="verbose of logs")
    env_path: Optional[str] = Field(None, description="Путь к .env файлу")

    class Config:
        env_prefix = "gpt2giga_"
        case_sensitive = False

class ProxyConfig(BaseSettings):
    """Конфигурация прокси-сервера"""
    proxy_settings: ProxySettings = Field(default_factory=ProxySettings)
    gigachat_settings: GigachatSettings = Field(default_factory=GigachatSettings)