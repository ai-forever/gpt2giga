import asyncio
import os
from pathlib import Path

from fastapi import APIRouter, Query
from sse_starlette import EventSourceResponse
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse

from gpt2giga.common import exceptions_handler, verify_logs_ip_allowlist

logs_api_router = APIRouter(tags=["System logs"])

logs_router = APIRouter(tags=["HTML logs"])


@logs_api_router.get("/logs", response_class=PlainTextResponse)
@exceptions_handler
async def get_logs(request: Request, lines: int = Query(100, ge=1, le=5000)):
    """
    Return the last N lines from the log file.
    """
    verify_logs_ip_allowlist(request)
    filename = request.app.state.config.proxy_settings.log_filename
    if not os.path.exists(filename):
        return PlainTextResponse("Log file not found.", status_code=404)

    try:
        with open(filename, "r", encoding="utf-8", errors="ignore") as f:
            content = f.readlines()[-lines:]
        return PlainTextResponse("".join(content))
    except Exception as e:
        request.app.state.logger.exception("Error reading log file")
        return PlainTextResponse(f"Error: {str(e)}", status_code=500)


@logs_api_router.get("/logs/stream")
@exceptions_handler
async def stream_logs(request: Request):
    """
    Stream live logs using Server-Sent Events (SSE).
    """
    verify_logs_ip_allowlist(request)

    async def log_generator():
        filename = request.app.state.config.proxy_settings.log_filename
        if not os.path.exists(filename):
            yield {"event": "error", "data": "Log file not found."}
            return

        # Track file position to continue reading from where we left off
        file_position = 0

        # Set initial position to end of file
        try:
            with open(filename, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(0, os.SEEK_END)
                file_position = f.tell()
        except OSError:
            yield {"event": "error", "data": "Error accessing log file."}
            return

        while True:
            if await request.is_disconnected():
                break
            try:
                with open(filename, "r", encoding="utf-8", errors="ignore") as f:
                    f.seek(file_position)
                    line = f.readline()
                    if line:
                        file_position = f.tell()
                        yield {"event": "message", "data": line.strip()}
                    else:
                        await asyncio.sleep(0.5)  # wait briefly for new lines
            except asyncio.CancelledError:
                # Let cancellation propagate so server shutdown is not blocked.
                raise
            except OSError:
                # If file becomes inaccessible, just wait and retry
                await asyncio.sleep(0.5)

    return EventSourceResponse(log_generator())


@logs_router.get("/logs/html", response_class=HTMLResponse)
async def root(request: Request):
    """Serve the simple log viewer."""
    verify_logs_ip_allowlist(request)
    html_path = Path(__file__).parent.parent / "templates" / "log_viewer.html"
    return HTMLResponse(html_path.read_text())
