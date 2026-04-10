"""Admin HTML UI endpoints."""

from __future__ import annotations

from pathlib import Path

import anyio
from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import HTMLResponse

from gpt2giga.api.admin.logs import verify_logs_ip_allowlist
from gpt2giga.core.errors import exceptions_handler

admin_router = APIRouter(include_in_schema=False)

_ADMIN_HTML: str | None = None


@admin_router.get("/admin", response_class=HTMLResponse)
@exceptions_handler
async def get_admin_ui(request: Request):
    """Serve the admin UI shell."""
    verify_logs_ip_allowlist(request)

    global _ADMIN_HTML  # noqa: PLW0603
    if _ADMIN_HTML is None:
        html_path = Path(__file__).resolve().parents[2] / "templates" / "admin.html"
        _ADMIN_HTML = await anyio.to_thread.run_sync(
            lambda: html_path.read_text(encoding="utf-8"),
        )

    return HTMLResponse(_ADMIN_HTML)
