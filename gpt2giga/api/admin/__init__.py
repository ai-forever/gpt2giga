"""Admin and debug API namespace."""

from gpt2giga.api.admin.logs import router as logs_router
from gpt2giga.api.admin.routes import router as debug_router

router = debug_router

__all__ = ["debug_router", "logs_router", "router"]
