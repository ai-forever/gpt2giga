"""Structured request observability middleware."""

from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import Callable

from fastapi.routing import APIRoute
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from gpt2giga.app.observability import RequestAuditEvent, record_request_event

_IGNORED_PREFIXES = (
    "/admin",
    "/logs",
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
            return response
        except Exception as exc:
            error_type = type(exc).__name__
            raise
        finally:
            event = self._build_event(
                request,
                response_status_code=(response.status_code if response else 500),
                started_at=started_at,
                duration_ms=round((perf_counter() - started) * 1000, 3),
                error_type=error_type,
                request_id=(
                    response.headers.get("x-request-id")
                    if response is not None
                    else request.headers.get("x-request-id")
                ),
            )
            if event is not None:
                record_request_event(request.app.state, event)

    def _build_event(
        self,
        request: Request,
        *,
        response_status_code: int,
        started_at: str,
        duration_ms: float,
        error_type: str | None,
        request_id: str | None,
    ) -> RequestAuditEvent | None:
        route = request.scope.get("route")
        endpoint = _resolve_endpoint(route, request)
        if endpoint.startswith(_IGNORED_PREFIXES):
            return None

        return {
            "created_at": started_at,
            "request_id": request_id,
            "provider": _resolve_provider(route),
            "endpoint": endpoint,
            "method": request.method,
            "path": request.scope.get("path", request.url.path),
            "status_code": response_status_code,
            "duration_ms": duration_ms,
            "client_ip": _get_client_ip(request),
            "error_type": error_type,
        }


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
