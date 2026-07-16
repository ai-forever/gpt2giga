"""Middleware for unified incoming request validation.

Centralises body-size enforcement so that every endpoint benefits from the
limit without duplicating the check in individual handlers.
"""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from gpt2giga.models.security import DEFAULT_MAX_REQUEST_BODY_BYTES


class RequestValidationMiddleware:
    """Reject requests whose Content-Length exceeds the configured limit.

    The middleware reads the ``Content-Length`` header *before* the body is
    consumed so that obviously oversized requests are rejected early (with a
    ``413 Request Entity Too Large`` response).

    Requests without ``Content-Length`` remain subject to endpoint-level limits.
    """

    def __init__(
        self, app: ASGIApp, max_body_bytes: int = DEFAULT_MAX_REQUEST_BODY_BYTES
    ):
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Only enforce on methods that carry a body.
        if scope["method"] in {"POST", "PUT", "PATCH"}:
            content_length = _header(scope, b"content-length")
            if content_length is not None:
                try:
                    length = int(content_length)
                except (TypeError, ValueError):
                    length = 0
                if length > self.max_body_bytes:
                    response = self._too_large_response(length)
                    await response(scope, receive, send)
                    return

        await self.app(scope, receive, send)

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


def _header(scope: Scope, name: bytes) -> str | None:
    for header_name, value in scope.get("headers", ()):
        if header_name.lower() == name:
            return value.decode("latin-1")
    return None
