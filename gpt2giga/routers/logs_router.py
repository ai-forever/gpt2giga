import asyncio
from pathlib import Path

import anyio
from fastapi import APIRouter, Query
from sse_starlette import EventSourceResponse
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse

from gpt2giga.common import exceptions_handler, verify_logs_ip_allowlist

logs_api_router = APIRouter(tags=["System logs"])

logs_router = APIRouter(tags=["HTML logs"])

_LOG_VIEWER_HTML: str | None = None


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
    filename = request.app.state.config.proxy_settings.log_filename

    try:
        content = await anyio.to_thread.run_sync(_read_last_lines, filename, lines)
        if content is None:
            return PlainTextResponse("Log file not found.", status_code=404)
        return PlainTextResponse(content)
    except Exception as e:
        request.app.state.logger.exception("Error reading log file")
        return PlainTextResponse(f"Error: {str(e)}", status_code=500)


@logs_api_router.get("/logs/stream")
@exceptions_handler
async def stream_logs(request: Request):
    """Stream live logs using Server-Sent Events (SSE)."""
    verify_logs_ip_allowlist(request)

    async def log_generator():
        filename = request.app.state.config.proxy_settings.log_filename

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
        html_path = Path(__file__).parent.parent / "templates" / "log_viewer.html"
        _LOG_VIEWER_HTML = await anyio.to_thread.run_sync(html_path.read_text)

    return HTMLResponse(_LOG_VIEWER_HTML)
