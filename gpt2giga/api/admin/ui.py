"""Admin console HTML endpoints."""

from __future__ import annotations

import anyio
from fastapi import APIRouter, HTTPException
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from gpt2giga.api.admin.access import verify_admin_ip_allowlist
from gpt2giga.app.admin_ui import (
    get_admin_setup_path,
    get_admin_ui_resources,
    is_admin_ui_enabled,
)
from gpt2giga.app.dependencies import get_config_from_state
from gpt2giga.core.config.control_plane import requires_admin_bootstrap
from gpt2giga.core.errors import exceptions_handler

admin_router = APIRouter(include_in_schema=False)

_CONSOLE_HTML: str | None = None
_CONSOLE_PAGES = (
    "/admin",
    "/admin/overview",
    "/admin/setup",
    "/admin/setup-claim",
    "/admin/setup-application",
    "/admin/setup-gigachat",
    "/admin/setup-security",
    "/admin/settings",
    "/admin/settings-application",
    "/admin/settings-observability",
    "/admin/settings-gigachat",
    "/admin/settings-security",
    "/admin/settings-history",
    "/admin/keys",
    "/admin/logs",
    "/admin/playground",
    "/admin/traffic",
    "/admin/traffic-requests",
    "/admin/traffic-errors",
    "/admin/traffic-usage",
    "/admin/providers",
    "/admin/files-batches",
    "/admin/files",
    "/admin/batches",
    "/admin/system",
)


async def _get_console_html() -> str:
    global _CONSOLE_HTML  # noqa: PLW0603
    if _CONSOLE_HTML is None:
        resources = get_admin_ui_resources()
        if resources is None:
            raise HTTPException(status_code=404, detail="Admin UI is not installed.")
        _CONSOLE_HTML = await anyio.to_thread.run_sync(
            lambda: resources.console_html_path.read_text(encoding="utf-8"),
        )
    return _CONSOLE_HTML


async def _serve_console(request: Request) -> Response:
    verify_admin_ip_allowlist(request)
    config = get_config_from_state(request.app.state)
    if not is_admin_ui_enabled(config):
        raise HTTPException(status_code=404, detail="Admin UI is disabled.")
    setup_path = get_admin_setup_path(config)
    if requires_admin_bootstrap(config) and request.url.path != setup_path:
        return RedirectResponse(url=setup_path)
    return HTMLResponse(await _get_console_html())


def _register_console_route(path: str) -> None:
    @admin_router.get(path, response_class=HTMLResponse)
    @exceptions_handler
    async def _render_console(request: Request) -> Response:
        """Serve the multi-page operator console shell."""
        return await _serve_console(request)


for _route in _CONSOLE_PAGES:
    _register_console_route(_route)
