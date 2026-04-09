"""CLI-driven application configuration loading."""

import argparse
import os

from dotenv import find_dotenv, load_dotenv

from gpt2giga.core.app_meta import warn_sensitive_cli_args
from gpt2giga.core.config.settings import ProxyConfig


def load_config() -> ProxyConfig:
    """Load configuration from CLI arguments and environment variables."""
    warn_sensitive_cli_args()

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--env-path", type=str, default=None, help="Path to .env file")
    args, _ = parser.parse_known_args()

    requested_env = args.env_path if args.env_path else f"{os.getcwd()}/.env"
    env_path = find_dotenv(requested_env)
    load_dotenv(env_path)

    return ProxyConfig()
