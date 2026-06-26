"""Protected built-in UI routes."""

from __future__ import annotations

from fastapi import APIRouter
from starlette.responses import HTMLResponse, RedirectResponse, Response

from gpt2giga.ui.log_detail import render_log_detail_html
from gpt2giga.ui.logs import render_logs_html
from gpt2giga.ui.playground import (
    new_script_nonce,
    render_playground_html,
    security_headers,
)

router = APIRouter(prefix="/ui", include_in_schema=False)


def _html_response(content: str, *, script_nonce: str | None = None) -> HTMLResponse:
    return HTMLResponse(
        content,
        headers=security_headers(script_nonce, allow_connect_self=True),
    )


def _redirect_response(url: str) -> RedirectResponse:
    return RedirectResponse(url=url, headers=security_headers())


@router.get("", response_class=HTMLResponse)
async def ui_root() -> Response:
    """Redirect the UI root to the playground shell."""
    return _redirect_response("/ui/playground")


@router.get("/", response_class=HTMLResponse)
async def ui_root_slash() -> Response:
    """Redirect the UI root with a trailing slash to the playground shell."""
    return _redirect_response("/ui/playground")


@router.get("/playground", response_class=HTMLResponse)
async def playground() -> HTMLResponse:
    """Serve the built-in playground request builder."""
    script_nonce = new_script_nonce()
    return _html_response(
        render_playground_html(script_nonce),
        script_nonce=script_nonce,
    )


@router.get("/logs", response_class=HTMLResponse)
async def logs() -> HTMLResponse:
    """Serve the built-in traffic logs list."""
    script_nonce = new_script_nonce()
    return _html_response(
        render_logs_html(script_nonce),
        script_nonce=script_nonce,
    )


@router.get("/logs/{event_id}", response_class=HTMLResponse)
async def log_detail(event_id: str) -> HTMLResponse:
    """Serve the built-in traffic log detail page."""
    script_nonce = new_script_nonce()
    return _html_response(
        render_log_detail_html(script_nonce, event_id),
        script_nonce=script_nonce,
    )
