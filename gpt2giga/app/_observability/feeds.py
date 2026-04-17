"""Feed access and query helpers for request audit events."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from gpt2giga.app.dependencies import get_runtime_stores
from gpt2giga.app.runtime_backends import EventFeed

from .models import RequestAuditEvent

_OPERATOR_NOISE_PATHS = {
    "/",
    "/admin",
    "/docs",
    "/favicon.ico",
    "/logs",
    "/logs/html",
    "/logs/stream",
    "/openapi.json",
    "/redoc",
    "/robots.txt",
}
_OPERATOR_NOISE_PREFIXES = ("/admin/",)


def get_recent_request_feed_from_state(state: Any) -> EventFeed:
    """Return the recent requests feed from app state."""
    feed = get_runtime_stores(state).recent_requests
    if feed is None:
        raise RuntimeError("Recent requests feed is not configured.")
    return feed


def get_recent_error_feed_from_state(state: Any) -> EventFeed:
    """Return the recent errors feed from app state."""
    feed = get_runtime_stores(state).recent_errors
    if feed is None:
        raise RuntimeError("Recent errors feed is not configured.")
    return feed


def filter_request_events(
    events: list[RequestAuditEvent],
    *,
    request_id: str | None = None,
    provider: str | None = None,
    endpoint: str | None = None,
    method: str | None = None,
    status_code: int | None = None,
    model: str | None = None,
    error_type: str | None = None,
    exclude_noise: bool = False,
) -> list[RequestAuditEvent]:
    """Filter request events by normalized admin filter fields."""
    filtered = (
        [item for item in events if not is_operator_noise_event(item)]
        if exclude_noise
        else events
    )
    if request_id is not None:
        filtered = [item for item in filtered if item.get("request_id") == request_id]
    if provider is not None:
        filtered = [item for item in filtered if item.get("provider") == provider]
    if endpoint is not None:
        filtered = [item for item in filtered if item.get("endpoint") == endpoint]
    if method is not None:
        filtered = [item for item in filtered if item.get("method") == method]
    if status_code is not None:
        filtered = [item for item in filtered if item.get("status_code") == status_code]
    if model is not None:
        filtered = [item for item in filtered if item.get("model") == model]
    if error_type is not None:
        filtered = [item for item in filtered if item.get("error_type") == error_type]
    return filtered


def is_operator_noise_event(event: Mapping[str, object]) -> bool:
    """Return whether an event is admin/browser support noise for operator views."""
    path = str(event.get("path") or event.get("endpoint") or "")
    endpoint = str(event.get("endpoint") or path)
    return _is_operator_noise_path(path) or _is_operator_noise_path(endpoint)


def filter_operator_noise(
    events: Iterable[RequestAuditEvent],
) -> list[RequestAuditEvent]:
    """Remove admin/browser support requests from operator-focused event lists."""
    return [event for event in events if not is_operator_noise_event(event)]


def query_request_events(
    feed: EventFeed,
    *,
    limit: int | None = None,
    request_id: str | None = None,
    provider: str | None = None,
    endpoint: str | None = None,
    method: str | None = None,
    status_code: int | None = None,
    model: str | None = None,
    error_type: str | None = None,
    exclude_noise: bool = False,
) -> list[RequestAuditEvent]:
    """Query recent request events with a graceful fallback for legacy feeds."""
    filters = {
        key: value
        for key, value in {
            "request_id": request_id,
            "provider": provider,
            "endpoint": endpoint,
            "method": method,
            "status_code": status_code,
            "model": model,
            "error_type": error_type,
        }.items()
        if value is not None
    }
    if not exclude_noise:
        query = getattr(feed, "query", None)
        if callable(query):
            return list(query(limit=limit, filters=filters))

    filtered = filter_request_events(
        list(feed.recent(limit=None)),
        request_id=request_id,
        provider=provider,
        endpoint=endpoint,
        method=method,
        status_code=status_code,
        model=model,
        error_type=error_type,
        exclude_noise=exclude_noise,
    )
    if limit is None:
        return filtered
    return filtered[-limit:]


def _is_operator_noise_path(path: str) -> bool:
    """Return whether a route path is browser/admin support noise."""
    return path in _OPERATOR_NOISE_PATHS or path.startswith(_OPERATOR_NOISE_PREFIXES)
