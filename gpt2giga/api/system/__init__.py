"""System and operational HTTP endpoints."""

from gpt2giga.api.system.health import system_router
from gpt2giga.api.system.logs import logs_api_router, logs_router

__all__ = ["logs_api_router", "logs_router", "system_router"]
