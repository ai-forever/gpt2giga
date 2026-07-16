"""Pure-ASGI request context and lifecycle instrumentation middleware."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from gpt2giga.core.context import build_request_context, request_context_var
from gpt2giga.logger import logger, rquid_context
from gpt2giga.sinks.logs.emission import (
    MAX_CAPTURED_RESPONSE_BODY_BYTES,
    capture_traffic_request_headers,
    decode_captured_response_body,
    emit_request_traffic_event,
    is_streaming_content_type,
)
from gpt2giga.sinks.metrics.emission import emit_request_metrics
from gpt2giga.sinks.observability.emission import emit_request_observability_event


class RquidMiddleware:
    """Assign request IDs and record lifecycle data without response wrappers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        request_id = str(uuid.uuid4())
        context = build_request_context(request, request_id=request_id)
        capture_traffic_request_headers(request, context)
        scope.setdefault("state", {})["request_context"] = context
        request_id_token = rquid_context.set(request_id)
        context_token = request_context_var.set(context)
        response = _ResponseLifecycle(
            request=request,
            context=context,
            request_id=request_id,
        )

        async def send_with_lifecycle(message: Message) -> None:
            if message["type"] == "http.response.start":
                response.started = True
                response.status_code = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
                response.is_streaming = is_streaming_content_type(
                    Headers(raw=message.get("headers", [])).get("content-type")
                )
            elif message["type"] == "http.response.body":
                response.capture_chunk(message.get("body", b""))

            if message["type"] == "http.response.body" and not message.get(
                "more_body", False
            ):
                await response.complete()

            await send(message)

        try:
            await self.app(scope, receive, send_with_lifecycle)
            if response.started and not response.completed:
                await response.complete()
        except asyncio.CancelledError:
            await response.fail(cancelled=True)
            raise
        except Exception as exc:
            logger.bind(
                request_id=context.request_id,
                trace_id=context.trace_id,
            ).exception("Unhandled exception during request")
            await response.fail(exc=exc)
            raise
        finally:
            rquid_context.reset(request_id_token)
            request_context_var.reset(context_token)


class _ResponseLifecycle:
    def __init__(self, *, request: Request, context: Any, request_id: str) -> None:
        self.request = request
        self.context = context
        self.request_id = request_id
        self.started = False
        self.completed = False
        self.status_code = 500
        self.is_streaming = False
        settings = getattr(
            getattr(request.app.state, "config", None), "proxy_settings", None
        )
        self.capture_content = getattr(settings, "traffic_log_capture_content", False)
        self.redact_sensitive = getattr(settings, "traffic_log_redact_sensitive", True)
        self.redact_extra_keys = getattr(
            settings, "traffic_log_redact_extra_keys", None
        )
        self._captured_chunks: list[bytes] = []
        self._captured_size = 0
        self._capture_truncated = False

    def capture_chunk(self, chunk: bytes) -> None:
        if (
            not self.capture_content
            or self.is_streaming
            or self._capture_truncated
            or not chunk
        ):
            return
        remaining = MAX_CAPTURED_RESPONSE_BODY_BYTES - self._captured_size
        if remaining > 0:
            self._captured_chunks.append(chunk[:remaining])
            self._captured_size += min(len(chunk), remaining)
        if len(chunk) > remaining:
            self._capture_truncated = True

    async def complete(self) -> None:
        if self.completed:
            return
        self.completed = True
        if self.capture_content and not self.is_streaming:
            self.context.response_body_redacted = decode_captured_response_body(
                b"".join(self._captured_chunks),
                truncated=self._capture_truncated,
                redact_sensitive=self.redact_sensitive,
                redact_extra_keys=self.redact_extra_keys,
            )
        await self._emit(
            status_code=self.status_code,
            lifecycle=(
                "streaming_completed" if self.is_streaming else "request_completed"
            ),
        )

    async def fail(
        self,
        *,
        exc: Exception | None = None,
        cancelled: bool = False,
    ) -> None:
        if self.completed:
            return
        self.completed = True
        lifecycle = (
            "streaming_aborted"
            if self.is_streaming
            else "request_aborted"
            if cancelled
            else "request_error"
        )
        status_code = (
            499 if cancelled else self.status_code if self.status_code >= 400 else 500
        )
        await self._emit(
            status_code=status_code,
            lifecycle=lifecycle,
            error_type=(
                "stream_cancelled"
                if cancelled and self.is_streaming
                else "request_cancelled"
                if cancelled
                else type(exc).__name__
                if exc is not None
                else None
            ),
            error_message=str(exc) if exc is not None else None,
        )

    async def _emit(
        self,
        *,
        status_code: int,
        lifecycle: str,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        state = self.request.app.state
        app_logger = getattr(state, "logger", None)
        await asyncio.gather(
            emit_request_traffic_event(
                getattr(state, "traffic_log_sink", None),
                self.context,
                status_code=status_code,
                lifecycle=lifecycle,
                logger=app_logger,
                error_type=error_type,
                error_message=error_message,
            ),
            emit_request_observability_event(
                getattr(state, "observability_sink", None),
                self.context,
                status_code=status_code,
                lifecycle=lifecycle,
                logger=app_logger,
                error_type=error_type,
                error_message=error_message,
                is_streaming=self.is_streaming,
            ),
            emit_request_metrics(
                getattr(state, "metrics_sink", None),
                self.context,
                status_code=status_code,
                lifecycle=lifecycle,
                logger=app_logger,
                error_type=error_type,
                error_message=error_message,
                is_streaming=self.is_streaming,
            ),
        )
