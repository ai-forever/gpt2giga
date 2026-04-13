"""Admin log endpoints and legacy compatibility shims."""

from __future__ import annotations

import asyncio
from pathlib import Path

import anyio
from fastapi import APIRouter, Query
from sse_starlette import EventSourceResponse
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse
from starlette.status import HTTP_403_FORBIDDEN, HTTP_307_TEMPORARY_REDIRECT

from gpt2giga.app.dependencies import get_config_from_state, get_logger_from_state
from gpt2giga.core.errors import exceptions_handler

admin_logs_api_router = APIRouter(tags=["Admin"])
legacy_logs_router = APIRouter(include_in_schema=False)


def get_client_ip(request: Request) -> str:
    """Extract client IP from X-Forwarded-For or request.client."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return ""


def verify_logs_ip_allowlist(request: Request) -> None:
    """Deny access if client IP is not in the configured allowlist."""
    config = get_config_from_state(request.app.state)
    allowlist = getattr(config.proxy_settings, "logs_ip_allowlist", None)
    if not allowlist:
        return

    client_ip = get_client_ip(request)
    if client_ip not in allowlist:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Access denied: IP not in logs allowlist",
        )


def _legacy_headers(alternate_path: str = "/admin?tab=logs") -> dict[str, str]:
    """Expose a soft-deprecation hint for legacy log endpoints."""
    return {
        "Deprecation": "true",
        "Link": f'<{alternate_path}>; rel="alternate"',
    }


def _read_last_lines(filename: str, lines: int) -> str | None:
    """Read the last *lines* from *filename* synchronously."""
    if not Path(filename).exists():
        return None
    with open(filename, "r", encoding="utf-8", errors="ignore") as file:
        content = file.readlines()[-lines:]
    return "".join(content)


def _seek_to_end(filename: str) -> int | None:
    """Return the EOF byte offset or ``None`` when the file is missing."""
    if not Path(filename).exists():
        return None
    try:
        with open(filename, "r", encoding="utf-8", errors="ignore") as file:
            file.seek(0, 2)
            return file.tell()
    except OSError:
        return -1


def _read_line_at(filename: str, position: int) -> tuple[str | None, int]:
    """Read one line starting at *position* and return the new cursor."""
    with open(filename, "r", encoding="utf-8", errors="ignore") as file:
        file.seek(position)
        line = file.readline()
        return (line if line else None, file.tell())


async def _get_logs_response(
    request: Request,
    *,
    lines: int,
    headers: dict[str, str] | None = None,
) -> PlainTextResponse:
    """Return the last N lines from the configured log file."""
    verify_logs_ip_allowlist(request)
    filename = get_config_from_state(request.app.state).proxy_settings.log_filename

    try:
        content = await anyio.to_thread.run_sync(_read_last_lines, filename, lines)
        if content is None:
            return PlainTextResponse(
                "Log file not found.",
                status_code=404,
                headers=headers,
            )
        return PlainTextResponse(content, headers=headers)
    except Exception as exc:  # pragma: no cover - exercised in tests
        logger = get_logger_from_state(request.app.state)
        if logger is not None:
            logger.exception("Error reading log file")
        return PlainTextResponse(
            f"Error: {str(exc)}",
            status_code=500,
            headers=headers,
        )


async def _stream_logs_response(
    request: Request,
    *,
    headers: dict[str, str] | None = None,
) -> EventSourceResponse:
    """Stream live logs using Server-Sent Events."""
    verify_logs_ip_allowlist(request)

    async def log_generator():
        filename = get_config_from_state(request.app.state).proxy_settings.log_filename

        file_position = await anyio.to_thread.run_sync(_seek_to_end, filename)
        if file_position is None:
            yield {"event": "error", "data": "Log file not found."}
            return
        if file_position == -1:
            yield {"event": "error", "data": "Error accessing log file."}
            return

        while True:
            if await request.is_disconnected():
                break
            try:
                line, new_pos = await anyio.to_thread.run_sync(
                    _read_line_at,
                    filename,
                    file_position,
                )
                if line:
                    file_position = new_pos
                    yield {"event": "message", "data": line.strip()}
                else:
                    await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                raise
            except OSError:
                await asyncio.sleep(0.5)

    return EventSourceResponse(log_generator(), headers=headers)


@admin_logs_api_router.get(
    "/admin/api/logs",
    response_class=PlainTextResponse,
)
@exceptions_handler
async def get_admin_logs(request: Request, lines: int = Query(100, ge=1, le=5000)):
    """Return the last N lines from the log file for admin tooling."""
    return await _get_logs_response(request, lines=lines)


@admin_logs_api_router.get("/admin/api/logs/stream")
@exceptions_handler
async def stream_admin_logs(request: Request):
    """Stream live logs for admin tooling."""
    return await _stream_logs_response(request)


@legacy_logs_router.get(
    "/logs",
    response_class=PlainTextResponse,
    deprecated=True,
)
@exceptions_handler
async def get_legacy_logs(request: Request, lines: int = Query(100, ge=1, le=5000)):
    """Keep the legacy raw logs endpoint for a transition period."""
    return await _get_logs_response(request, lines=lines, headers=_legacy_headers())


@legacy_logs_router.get("/logs/stream", deprecated=True)
@exceptions_handler
async def stream_legacy_logs(request: Request):
    """Keep the legacy log SSE endpoint for a transition period."""
    return await _stream_logs_response(request, headers=_legacy_headers())


@legacy_logs_router.get("/logs/html", deprecated=True)
@exceptions_handler
async def redirect_legacy_logs_html(request: Request):
    """Redirect the legacy standalone log viewer into the admin UI."""
    verify_logs_ip_allowlist(request)
    return RedirectResponse(
        url="/admin?tab=logs",
        status_code=HTTP_307_TEMPORARY_REDIRECT,
        headers=_legacy_headers(),
    )
