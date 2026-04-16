"""Feed access and query helpers for request audit events."""

from __future__ import annotations

from typing import Any

from gpt2giga.app.dependencies import get_runtime_stores
from gpt2giga.app.runtime_backends import EventFeed

from .models import RequestAuditEvent


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
) -> list[RequestAuditEvent]:
    """Filter request events by normalized admin filter fields."""
    filtered = events
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
    query = getattr(feed, "query", None)
    if callable(query):
        return list(query(limit=limit, filters=filters))

    return filter_request_events(
        feed.recent(limit=limit),
        request_id=request_id,
        provider=provider,
        endpoint=endpoint,
        method=method,
        status_code=status_code,
        model=model,
        error_type=error_type,
    )
