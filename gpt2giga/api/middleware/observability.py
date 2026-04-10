"""Structured request observability middleware."""

from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import AsyncIterator, Callable

from fastapi.routing import APIRoute
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from gpt2giga.app.observability import (
    RequestAuditEvent,
    get_request_audit_metadata,
    record_request_event,
    set_request_audit_error,
)

_IGNORED_PREFIXES = (
    "/admin",
    "/logs",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
)

_TAG_TO_PROVIDER = {
    "openai": "openai",
    "anthropic": "anthropic",
    "gemini": "gemini",
    "litellm": "openai",
    "system": "system",
    "admin": "admin",
}


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Record recent request and error events for admin observability."""

    async def dispatch(self, request: Request, call_next: Callable):
        started_at = datetime.now(UTC).isoformat()
        started = perf_counter()
        response = None
        error_type: str | None = None

        try:
            response = await call_next(request)
        except Exception as exc:
            error_type = type(exc).__name__
            set_request_audit_error(request, error_type)
            raise
        if response is None:
            return None

        content_type = response.headers.get("content-type", "")
        if content_type.startswith("text/event-stream"):
            self._wrap_streaming_response(
                request,
                response,
                started_at=started_at,
                started=started,
                error_type=error_type,
            )
            return response

        self._record_event(
            request,
            response_status_code=response.status_code,
            started_at=started_at,
            duration_ms=round((perf_counter() - started) * 1000, 3),
            stream_duration_ms=None,
            error_type=error_type,
            request_id=response.headers.get("x-request-id"),
        )
        return response

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

    def _wrap_streaming_response(
        self,
        request: Request,
        response,
        *,
        started_at: str,
        started: float,
        error_type: str | None,
    ) -> None:
        body_iterator = response.body_iterator
        stream_started = perf_counter()

        async def observed_body_iterator() -> AsyncIterator[bytes | str]:
            final_error_type = error_type
            try:
                async for chunk in body_iterator:
                    yield chunk
            except Exception as exc:
                final_error_type = type(exc).__name__
                set_request_audit_error(request, final_error_type)
                raise
            finally:
                self._record_event(
                    request,
                    response_status_code=response.status_code,
                    started_at=started_at,
                    duration_ms=round((perf_counter() - started) * 1000, 3),
                    stream_duration_ms=round(
                        (perf_counter() - stream_started) * 1000,
                        3,
                    ),
                    error_type=final_error_type,
                    request_id=response.headers.get("x-request-id"),
                )

        response.body_iterator = observed_body_iterator()


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
        resolved = _TAG_TO_PROVIDER.get(str(tag).lower())
        if resolved is not None:
            return resolved
    return None


def _get_client_ip(request: Request) -> str | None:
    """Resolve the request client IP with proxy awareness."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    client = request.client
    return None if client is None else client.host
