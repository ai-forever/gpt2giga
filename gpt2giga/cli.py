import argparse
import os
from typing import get_origin, Literal, get_args

from dotenv import find_dotenv, load_dotenv
from gigachat.settings import Settings as GigachatSettings

from gpt2giga.config import ProxyConfig, ProxySettings


def load_config() -> ProxyConfig:
    """Загружает конфигурацию из аргументов командной строки и переменных окружения"""
    parser = argparse.ArgumentParser(
        description="Gpt2Giga converter proxy. Use GigaChat instead of OpenAI GPT models"
    )

    # Добавляем аргументы для proxy_settings
    for field_name, field in ProxySettings.__fields__.items():
        if field_name == "env_path":
            continue
        arg_name = f"--proxy-{field_name.replace('_', '-')}"
        help_text = field.field_info.description or field_name
        if field.type_ is bool:
            parser.add_argument(
                arg_name, action="store_true", default=None, help=help_text
            )
        elif get_origin(field.type_) is Literal:
            allowed_values = get_args(field.type_)
            parser.add_argument(
                arg_name,
                type=str,
                choices=allowed_values,
                default=None,
                help=f"{help_text} (choices: {', '.join(allowed_values)})",
            )
        else:
            parser.add_argument(
                arg_name, type=field.type_, default=None, help=help_text
            )

    # Добавляем аргументы для gigachat_settings
    for field_name, field in GigachatSettings.__fields__.items():
        arg_name = f"--gigachat-{field_name.replace('_', '-')}"
        help_text = field.field_info.description or field_name

        if field.type_ is bool:
            parser.add_argument(
                arg_name, action="store_true", default=None, help=help_text
            )
        else:
            parser.add_argument(
                arg_name, type=field.type_, default=None, help=help_text
            )

    parser.add_argument("--env-path", type=str, default=None, help="Path to .env file")

    args, _ = parser.parse_known_args()

    # Загружаем переменные окружения
    env_path = find_dotenv(args.env_path if args.env_path else f"{os.getcwd()}/.env")
    load_dotenv(env_path)

    # Собираем конфигурацию из CLI аргументов
    proxy_settings_dict = {}
    gigachat_settings_dict = {}

    for arg_name, arg_value in vars(args).items():
        if arg_value is not None:
            if arg_name.startswith("proxy_"):
                field_name = arg_name.replace("proxy_", "").replace("-", "_")
                proxy_settings_dict[field_name] = arg_value
            elif arg_name.startswith("gigachat_"):
                field_name = arg_name.replace("gigachat_", "").replace("-", "_")
                gigachat_settings_dict[field_name] = arg_value

    # Создаем конфиг
    config = ProxyConfig(
        proxy_settings=(
            ProxySettings(**proxy_settings_dict)
            if proxy_settings_dict
            else ProxySettings(env_path=env_path)
        ),
        gigachat_settings=(
            GigachatSettings(**gigachat_settings_dict)
            if gigachat_settings_dict
            else GigachatSettings()
        ),
    )
    return config
