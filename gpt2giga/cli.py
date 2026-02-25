import argparse
import os

from dotenv import find_dotenv, load_dotenv

from gpt2giga.common.app_meta import warn_sensitive_cli_args
from gpt2giga.models.config import ProxyConfig


def load_config() -> ProxyConfig:
    """Загружает конфигурацию из аргументов командной строки и переменных окружения."""
    warn_sensitive_cli_args()

    # Сначала проверяем --env-path, чтобы загрузить переменные окружения
    # Используем argparse только для этого, игнорируя остальные аргументы
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--env-path", type=str, default=None, help="Path to .env file")
    args, _ = parser.parse_known_args()

    # Загружаем переменные окружения
    requested_env = args.env_path if args.env_path else f"{os.getcwd()}/.env"
    env_path = find_dotenv(requested_env)
    load_dotenv(env_path)

    # pydantic-settings автоматически распарсит аргументы командной строки
    # благодаря cli_parse_args=True в ProxyConfig
    return ProxyConfig()
