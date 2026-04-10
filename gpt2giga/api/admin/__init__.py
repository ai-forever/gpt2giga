"""Admin UI and operator-focused HTTP endpoints."""

from gpt2giga.api.admin.logs import admin_logs_api_router, legacy_logs_router
from gpt2giga.api.admin.runtime import admin_runtime_api_router
from gpt2giga.api.admin.ui import admin_router

admin_api_router = admin_runtime_api_router
admin_api_router.include_router(admin_logs_api_router)

__all__ = [
    "admin_api_router",
    "admin_logs_api_router",
    "admin_router",
    "admin_runtime_api_router",
    "legacy_logs_router",
]
