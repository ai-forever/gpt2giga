"""CLI-driven application configuration loading."""

import argparse
import os
from collections.abc import Iterator
from contextlib import contextmanager

from dotenv import dotenv_values, find_dotenv

from gpt2giga.core.app_meta import warn_sensitive_cli_args
from gpt2giga.core.config.control_plane import apply_control_plane_overrides
from gpt2giga.core.config.settings import ProxyConfig


@contextmanager
def _temporary_dotenv(env_path: str) -> Iterator[None]:
    """Temporarily expose values from a dotenv file during config loading."""
    resolved_env_path = find_dotenv(env_path)
    if not resolved_env_path:
        yield
        return

    added_keys: list[str] = []
    for key, value in dotenv_values(resolved_env_path).items():
        if not key or value is None or key in os.environ:
            continue
        os.environ[key] = value
        added_keys.append(key)

    try:
        yield
    finally:
        for key in added_keys:
            os.environ.pop(key, None)


def load_config() -> ProxyConfig:
    """Load configuration from CLI arguments and environment variables."""
    warn_sensitive_cli_args()

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--env-path", type=str, default=None, help="Path to .env file")
    args, _ = parser.parse_known_args()

    requested_env = args.env_path if args.env_path else f"{os.getcwd()}/.env"
    with _temporary_dotenv(requested_env):
        config = ProxyConfig(env_path=requested_env)
    return apply_control_plane_overrides(config)
