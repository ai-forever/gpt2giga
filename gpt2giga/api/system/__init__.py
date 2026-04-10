"""System health endpoints."""

from gpt2giga.api.system.health import system_router
from gpt2giga.api.system.metrics import metrics_router

__all__ = ["metrics_router", "system_router"]
