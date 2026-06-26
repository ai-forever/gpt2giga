"""Admin and debug API namespace."""

from gpt2giga.api.admin.compat import router as compat_router
from gpt2giga.api.admin.logs import router as logs_router
from gpt2giga.api.admin.routes import router as debug_router

router = debug_router

__all__ = ["compat_router", "debug_router", "logs_router", "router"]
