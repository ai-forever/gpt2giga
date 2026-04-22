"""Middleware for unified incoming request validation.

Centralizes body-size enforcement so that every endpoint benefits from the
limit without duplicating the check in individual handlers.
"""

from __future__ import annotations

from collections import deque

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from gpt2giga.core.constants import DEFAULT_MAX_REQUEST_BODY_BYTES

_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})


class _RequestTooLargeError(Exception):
    """Internal signal that the buffered request body exceeded the limit."""

    def __init__(self, actual_size: int):
        self.actual_size = actual_size
        super().__init__(actual_size)


class RequestValidationMiddleware:
    """Reject oversized request bodies before they reach route handlers.

    The middleware reads the ``Content-Length`` header *before* the body is
    consumed so that obviously oversized requests are rejected early (with a
    ``413 Request Entity Too Large`` response).

    For requests without a valid ``Content-Length`` (for example chunked
    transfer-encoding), the middleware buffers request-body frames up to the
    configured limit, rejects oversized payloads, and replays accepted frames
    to downstream handlers unchanged.
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

        method = str(scope.get("method", "")).upper()
        # Only enforce on methods that carry a body.
        if method not in _BODY_METHODS:
            await self.app(scope, receive, send)
            return

        headers = Headers(raw=scope.get("headers") or [])
        content_length = self._parse_content_length(headers.get("content-length"))
        if content_length is not None:
            if content_length > self.max_body_bytes:
                await self._too_large_response(content_length)(scope, receive, send)
                return
            await self.app(scope, receive, send)
            return

        try:
            buffered_messages = await self._buffer_request_messages(receive)
        except _RequestTooLargeError as exc:
            await self._too_large_response(exc.actual_size)(scope, receive, send)
            return

        await self.app(scope, self._build_replay_receive(buffered_messages), send)

    async def _buffer_request_messages(self, receive: Receive) -> list[Message]:
        buffered_messages: list[Message] = []
        actual_size = 0

        while True:
            message = await receive()
            buffered_messages.append(message)
            if message["type"] != "http.request":
                break

            actual_size += len(message.get("body", b""))
            if actual_size > self.max_body_bytes:
                raise _RequestTooLargeError(actual_size)
            if not message.get("more_body", False):
                break

        return buffered_messages

    def _build_replay_receive(self, buffered_messages: list[Message]) -> Receive:
        pending = deque(buffered_messages)

        async def replay_receive() -> Message:
            if pending:
                return pending.popleft()
            return {"type": "http.request", "body": b"", "more_body": False}

        return replay_receive

    @staticmethod
    def _parse_content_length(value: str | None) -> int | None:
        if value is None:
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None

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
