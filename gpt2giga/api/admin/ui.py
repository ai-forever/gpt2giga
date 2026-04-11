"""Admin console HTML endpoints."""

from __future__ import annotations

from pathlib import Path

import anyio
from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import HTMLResponse

from gpt2giga.api.admin.logs import verify_logs_ip_allowlist
from gpt2giga.core.errors import exceptions_handler

admin_router = APIRouter(include_in_schema=False)

_CONSOLE_HTML: str | None = None
_CONSOLE_PAGES = (
    "/admin",
    "/admin/overview",
    "/admin/settings",
    "/admin/keys",
    "/admin/logs",
    "/admin/playground",
    "/admin/traffic",
    "/admin/providers",
    "/admin/system",
)


async def _get_console_html() -> str:
    global _CONSOLE_HTML  # noqa: PLW0603
    if _CONSOLE_HTML is None:
        html_path = Path(__file__).resolve().parents[2] / "templates" / "console.html"
        _CONSOLE_HTML = await anyio.to_thread.run_sync(
            lambda: html_path.read_text(encoding="utf-8"),
        )
    return _CONSOLE_HTML


async def _serve_console(request: Request) -> HTMLResponse:
    verify_logs_ip_allowlist(request)
    return HTMLResponse(await _get_console_html())


def _register_console_route(path: str) -> None:
    @admin_router.get(path, response_class=HTMLResponse)
    @exceptions_handler
    async def _render_console(request: Request) -> HTMLResponse:
        """Serve the multi-page operator console shell."""
        return await _serve_console(request)


for _route in _CONSOLE_PAGES:
    _register_console_route(_route)
