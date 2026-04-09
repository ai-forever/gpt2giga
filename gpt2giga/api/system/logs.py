import asyncio
from pathlib import Path

import anyio
from fastapi import APIRouter, Query
from sse_starlette import EventSourceResponse
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse
from starlette.status import HTTP_403_FORBIDDEN

from gpt2giga.app.dependencies import get_config_from_state, get_logger_from_state
from gpt2giga.core.errors import exceptions_handler

logs_api_router = APIRouter(tags=["System logs"])

logs_router = APIRouter(tags=["HTML logs"])

_LOG_VIEWER_HTML: str | None = None


def _get_client_ip(request: Request) -> str:
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
    client_ip = _get_client_ip(request)
    if client_ip not in allowlist:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Access denied: IP not in logs allowlist",
        )


def _read_last_lines(filename: str, lines: int) -> str | None:
    """Read the last *lines* from *filename* synchronously.

    Returns the text or ``None`` when the file does not exist.
    """
    if not Path(filename).exists():
        return None
    with open(filename, "r", encoding="utf-8", errors="ignore") as f:
        content = f.readlines()[-lines:]
    return "".join(content)


def _seek_to_end(filename: str) -> int | None:
    """Return file size (byte offset of EOF) or ``None`` if missing.

    Returns ``-1`` when the file exists but cannot be opened.
    """
    if not Path(filename).exists():
        return None
    try:
        with open(filename, "r", encoding="utf-8", errors="ignore") as f:
            f.seek(0, 2)
            return f.tell()
    except OSError:
        return -1


def _read_line_at(filename: str, position: int) -> tuple[str | None, int]:
    """Read one line starting at *position*. Returns (line, new_position)."""
    with open(filename, "r", encoding="utf-8", errors="ignore") as f:
        f.seek(position)
        line = f.readline()
        return (line if line else None, f.tell())


@logs_api_router.get("/logs", response_class=PlainTextResponse)
@exceptions_handler
async def get_logs(request: Request, lines: int = Query(100, ge=1, le=5000)):
    """Return the last N lines from the log file."""
    verify_logs_ip_allowlist(request)
    filename = get_config_from_state(request.app.state).proxy_settings.log_filename

    try:
        content = await anyio.to_thread.run_sync(_read_last_lines, filename, lines)
        if content is None:
            return PlainTextResponse("Log file not found.", status_code=404)
        return PlainTextResponse(content)
    except Exception as e:
        logger = get_logger_from_state(request.app.state)
        if logger is not None:
            logger.exception("Error reading log file")
        return PlainTextResponse(f"Error: {str(e)}", status_code=500)


@logs_api_router.get("/logs/stream")
@exceptions_handler
async def stream_logs(request: Request):
    """Stream live logs using Server-Sent Events (SSE)."""
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
                    _read_line_at, filename, file_position
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


@logs_router.get("/logs/html", response_class=HTMLResponse)
async def root(request: Request):
    """Serve the simple log viewer."""
    verify_logs_ip_allowlist(request)

    global _LOG_VIEWER_HTML  # noqa: PLW0603
    if _LOG_VIEWER_HTML is None:
        html_path = (
            Path(__file__).resolve().parents[2] / "templates" / "log_viewer.html"
        )
        _LOG_VIEWER_HTML = await anyio.to_thread.run_sync(html_path.read_text)

    return HTMLResponse(_LOG_VIEWER_HTML)
