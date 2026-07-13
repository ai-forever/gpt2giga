"""Middleware for unified incoming request validation.

Centralises body-size enforcement so that every endpoint benefits from the
limit without duplicating the check in individual handlers.
"""

from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from gpt2giga.models.security import DEFAULT_MAX_REQUEST_BODY_BYTES


class RequestValidationMiddleware(BaseHTTPMiddleware):
    """Reject requests whose Content-Length exceeds the configured limit.

    The middleware reads the ``Content-Length`` header *before* the body is
    consumed so that obviously oversized requests are rejected early (with a
    ``413 Request Entity Too Large`` response).

    For requests without ``Content-Length`` (e.g. chunked transfer-encoding),
    the body is streamed and the limit is enforced on the actual bytes read.
    """

    def __init__(self, app, max_body_bytes: int = DEFAULT_MAX_REQUEST_BODY_BYTES):
        super().__init__(app)
        self.max_body_bytes = max_body_bytes

    async def dispatch(self, request: Request, call_next: Callable):
        # Only enforce on methods that carry a body.
        if request.method in {"POST", "PUT", "PATCH"}:
            content_length = request.headers.get("content-length")
            if content_length is not None:
                try:
                    length = int(content_length)
                except (TypeError, ValueError):
                    length = 0
                if length > self.max_body_bytes:
                    return self._too_large_response(length)

        return await call_next(request)

    def _too_large_response(self, actual_size: int) -> JSONResponse:
        return JSONResponse(
            status_code=413,
            content={
                "error": {
                    "message": (
                        f"Request body too large: {actual_size} bytes "
                        f"exceeds limit of {self.max_body_bytes} bytes."
                    ),
                    "type": "invalid_request_error",
                    "param": None,
                    "code": "request_entity_too_large",
                }
            },
        )
