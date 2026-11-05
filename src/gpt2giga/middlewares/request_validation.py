"""Middleware for unified incoming request validation.

Centralises body-size enforcement so that every endpoint benefits from the
limit without duplicating the check in individual handlers.
"""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from gpt2giga.models.security import DEFAULT_MAX_REQUEST_BODY_BYTES


class RequestValidationMiddleware:
    """Bound the received body before passing it to request handlers.

    The middleware reads the ``Content-Length`` header *before* the body is
    consumed so that obviously oversized requests are rejected early (with a
    ``413 Request Entity Too Large`` response). Actual bytes are also counted,
    including chunked bodies and bodies with an understated Content-Length.
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

            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                size = len(body) + len(chunk)
                if size > self.max_body_bytes:
                    await self._too_large_response(size)(scope, receive, send)
                    return
                body.extend(chunk)
                if not message.get("more_body", False):
                    break

            buffered_body: bytes | None = bytes(body)
            del body, message, chunk

            async def receive_buffered():
                nonlocal buffered_body
                if buffered_body is not None:
                    content = buffered_body
                    buffered_body = None
                    return {"type": "http.request", "body": content, "more_body": False}
                return await receive()

            await self.app(scope, receive_buffered, send)
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
