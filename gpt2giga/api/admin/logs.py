"""Admin log endpoints for the operator console."""

from __future__ import annotations

import asyncio
from pathlib import Path

import anyio
from fastapi import APIRouter, Query
from sse_starlette import EventSourceResponse
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from gpt2giga.api.admin.access import get_client_ip as get_client_ip
from gpt2giga.api.admin.access import verify_admin_ip_allowlist
from gpt2giga.app.dependencies import get_config_from_state, get_logger_from_state
from gpt2giga.core.errors import exceptions_handler

admin_logs_api_router = APIRouter(tags=["Admin"])

__all__ = (
    "admin_logs_api_router",
    "get_client_ip",
)


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
) -> PlainTextResponse:
    """Return the last N lines from the configured log file."""
    verify_admin_ip_allowlist(request)
    filename = get_config_from_state(request.app.state).proxy_settings.log_filename

    try:
        content = await anyio.to_thread.run_sync(_read_last_lines, filename, lines)
        if content is None:
            return PlainTextResponse(
                "Log file not found.",
                status_code=404,
            )
        return PlainTextResponse(content)
    except Exception as exc:  # pragma: no cover - exercised in tests
        logger = get_logger_from_state(request.app.state)
        if logger is not None:
            logger.exception("Error reading log file")
        return PlainTextResponse(
            f"Error: {str(exc)}",
            status_code=500,
        )


async def _stream_logs_response(
    request: Request,
) -> EventSourceResponse:
    """Stream live logs using Server-Sent Events."""
    verify_admin_ip_allowlist(request)

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

    return EventSourceResponse(log_generator())


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
