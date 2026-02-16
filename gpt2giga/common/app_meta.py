import socket
import sys
from importlib.metadata import PackageNotFoundError, version as pkg_version

from gpt2giga.constants import _SENSITIVE_CLI_ARGS
from gpt2giga.logger import rquid_context


def warn_sensitive_cli_args() -> None:
    """Emit a warning when secret values are passed as CLI arguments.

    CLI arguments are visible to all users on the same host via ``ps aux``.
    Secrets should be passed through environment variables or a ``.env`` file.
    """
    found = [arg for arg in sys.argv if arg.split("=")[0] in _SENSITIVE_CLI_ARGS]
    if found:
        message = (
            "Security warning: sensitive arguments detected in CLI: "
            f"{', '.join(found)}. "
            "CLI arguments are visible to all users via 'ps aux'. "
            "Use environment variables or .env file instead."
        )
        from loguru import logger

        rquid = rquid_context.get()
        logger.warning(f"[{rquid}] {message}")


def get_app_version() -> str:
    """Return package version for OpenAPI metadata."""
    try:
        return pkg_version("gpt2giga")
    except PackageNotFoundError:
        # Running from source without installed metadata.
        return "0.0.0"


def check_port_available(host: str, port: int) -> bool:
    """Check if a port is available for binding."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
        return True
    except OSError:
        return False
