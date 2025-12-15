import argparse
import os
from typing import Any, get_origin, Literal, get_args

from dotenv import find_dotenv, load_dotenv
from gigachat.settings import Settings as GigachatSettings
from pydantic.fields import FieldInfo

from gpt2giga.config import ProxyConfig, ProxySettings, GigaChatCLI


def _unwrap_optional(annotation: Any) -> Any:
    origin = get_origin(annotation)
    if origin is None:
        return annotation
    if origin is list or origin is dict or origin is tuple:
        return str
    if origin is Literal:
        return annotation
    union_origin = getattr(__import__("typing"), "Union")
    if origin is union_origin:
        args = tuple(a for a in get_args(annotation) if a is not type(None))  # noqa: E721
        return args[0] if args else str
    return str


def _add_settings_args(
    parser: argparse.ArgumentParser,
    prefix: str,
    model_fields: dict[str, FieldInfo],
    skip: set[str] | None = None,
) -> None:
    for field_name, field in model_fields.items():
        if skip and field_name in skip:
            continue

        arg_name = f"--{prefix}-{field_name.replace('_', '-')}"
        help_text = field.description or field_name
        annotation = _unwrap_optional(field.annotation)

        if annotation is bool:
            parser.add_argument(
                arg_name, action="store_true", default=None, help=help_text
            )
        elif get_origin(annotation) is Literal:
            allowed_values = list(map(str, get_args(annotation)))
            parser.add_argument(
                arg_name,
                type=str,
                choices=allowed_values,
                default=None,
                help=help_text,
            )
        else:
            arg_type = annotation if annotation in (str, int, float) else str
            parser.add_argument(arg_name, type=arg_type, default=None, help=help_text)


def load_config() -> ProxyConfig:
    """Загружает конфигурацию из аргументов командной строки и переменных окружения"""
    parser = argparse.ArgumentParser(
        description="Gpt2Giga converter proxy. Use GigaChat instead of OpenAI GPT models"
    )

    # Аргументы для ProxySettings (кроме env_path, она обрабатывается отдельно)
    _add_settings_args(
        parser,
        prefix="proxy",
        model_fields=ProxySettings.model_fields,
        skip={"env_path"},
    )
    # Аргументы для GigachatSettings
    _add_settings_args(
        parser, prefix="gigachat", model_fields=GigachatSettings.model_fields
    )

    parser.add_argument("--env-path", type=str, default=None, help="Path to .env file")

    args, _ = parser.parse_known_args()

    # Загружаем переменные окружения
    requested_env = args.env_path if args.env_path else f"{os.getcwd()}/.env"
    env_path = find_dotenv(requested_env)
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
            GigaChatCLI(**gigachat_settings_dict)
            if gigachat_settings_dict
            else GigaChatCLI()
        ),
    )
    return config
