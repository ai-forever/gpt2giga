"""Structured request observability middleware."""

from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter

from fastapi.routing import APIRoute
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from gpt2giga.api.tags import resolve_tag_provider
from gpt2giga.app.dependencies import get_config_from_state
from gpt2giga.app.observability import (
    RequestAuditEvent,
    get_request_audit_metadata,
    record_request_event,
    set_request_audit_error,
)
from gpt2giga.core.http import resolve_client_ip

_IGNORED_PREFIXES = (
    "/admin",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
)
UTC = timezone.utc


class ObservabilityMiddleware:
    """Record recent request and error events for admin observability."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        started_at = datetime.now(UTC).isoformat()
        started = perf_counter()
        stream_started: float | None = None
        response_status_code: int | None = None
        response_headers: Headers | None = None
        error_type: str | None = None
        recorded = False

        def is_streaming_response() -> bool:
            content_type = (
                response_headers.get("content-type", "")
                if response_headers is not None
                else ""
            )
            return content_type.startswith("text/event-stream")

        def record_once(final_error_type: str | None) -> None:
            nonlocal recorded
            if recorded or response_status_code is None:
                return
            recorded = True
            is_stream = is_streaming_response()
            now = perf_counter()
            self._record_event(
                request,
                response_status_code=response_status_code,
                started_at=started_at,
                duration_ms=round((now - started) * 1000, 3),
                stream_duration_ms=(
                    round((now - stream_started) * 1000, 3)
                    if is_stream and stream_started is not None
                    else None
                ),
                error_type=final_error_type,
                request_id=(
                    response_headers.get("x-request-id")
                    if response_headers is not None
                    else None
                ),
            )

        async def send_with_observability(message: Message) -> None:
            nonlocal response_headers, response_status_code, stream_started
            is_final_body = False
            if message["type"] == "http.response.start":
                response_status_code = int(message["status"])
                response_headers = Headers(raw=message.get("headers") or [])
                if is_streaming_response():
                    stream_started = perf_counter()
            elif message["type"] == "http.response.body" and not message.get(
                "more_body",
                False,
            ):
                is_final_body = True

            await send(message)
            if is_final_body:
                record_once(error_type)

        try:
            await self.app(scope, receive, send_with_observability)
        except Exception as exc:
            error_type = type(exc).__name__
            set_request_audit_error(request, error_type)
            record_once(error_type)
            raise
        finally:
            record_once(error_type)

    def _build_event(
        self,
        request: Request,
        *,
        response_status_code: int,
        started_at: str,
        duration_ms: float,
        stream_duration_ms: float | None,
        error_type: str | None,
        request_id: str | None,
    ) -> RequestAuditEvent | None:
        route = request.scope.get("route")
        endpoint = _resolve_endpoint(route, request)
        if endpoint.startswith(_IGNORED_PREFIXES):
            return None
        audit = get_request_audit_metadata(request)
        api_key_context = getattr(request.state, "api_key_context", None)
        resolved_error_type = audit.get("error_type") or error_type
        if resolved_error_type is None and response_status_code >= 400:
            resolved_error_type = f"HTTP_{response_status_code}"

        return {
            "created_at": started_at,
            "request_id": request_id,
            "provider": _resolve_provider(route),
            "endpoint": endpoint,
            "method": request.method,
            "path": request.scope.get("path", request.url.path),
            "status_code": response_status_code,
            "duration_ms": duration_ms,
            "stream_duration_ms": stream_duration_ms,
            "client_ip": _get_client_ip(request),
            "model": audit.get("model"),
            "token_usage": audit.get("token_usage"),
            "error_type": resolved_error_type,
            "api_key_name": getattr(api_key_context, "name", None),
            "api_key_source": getattr(api_key_context, "source", None),
            "input_value": audit.get("input_value"),
            "input_mime_type": audit.get("input_mime_type"),
            "output_value": audit.get("output_value"),
            "output_mime_type": audit.get("output_mime_type"),
            "input_messages": audit.get("input_messages"),
            "output_messages": audit.get("output_messages"),
            "session_id": audit.get("session_id"),
            "available_tools": audit.get("available_tools"),
            "invocation_parameters": audit.get("invocation_parameters"),
        }

    def _record_event(
        self,
        request: Request,
        *,
        response_status_code: int,
        started_at: str,
        duration_ms: float,
        stream_duration_ms: float | None,
        error_type: str | None,
        request_id: str | None,
    ) -> None:
        event = self._build_event(
            request,
            response_status_code=response_status_code,
            started_at=started_at,
            duration_ms=duration_ms,
            stream_duration_ms=stream_duration_ms,
            error_type=error_type,
            request_id=request_id or request.headers.get("x-request-id"),
        )
        if event is not None:
            record_request_event(request.app.state, event)


def _resolve_endpoint(route: object, request: Request) -> str:
    """Resolve a stable endpoint identifier from routing metadata."""
    if isinstance(route, APIRoute):
        return route.path
    return request.scope.get("path", request.url.path)


def _resolve_provider(route: object) -> str | None:
    """Resolve a provider name from route tags when available."""
    if not isinstance(route, APIRoute):
        return None
    for tag in route.tags or []:
        resolved = resolve_tag_provider(str(tag))
        if resolved is not None:
            return resolved
    return None


def _get_client_ip(request: Request) -> str | None:
    """Resolve the request client IP with the shared proxy-trust policy."""
    config = get_config_from_state(request.app.state)
    return resolve_client_ip(
        request,
        trusted_proxy_cidrs=config.proxy_settings.trusted_proxy_cidrs,
    )
