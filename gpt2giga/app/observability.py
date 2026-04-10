"""Observability helpers shared by middleware and admin endpoints."""

from __future__ import annotations

from typing import Any, TypedDict

from gpt2giga.app.dependencies import get_runtime_stores
from gpt2giga.app.runtime_backends import EventFeed


class RequestAuditEvent(TypedDict, total=False):
    """Structured audit event for a handled HTTP request."""

    created_at: str
    request_id: str | None
    provider: str | None
    endpoint: str
    method: str
    path: str
    status_code: int
    duration_ms: float
    client_ip: str | None
    error_type: str | None


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


def record_request_event(state: Any, event: RequestAuditEvent) -> None:
    """Append an audit event to recent requests and errors feeds."""
    get_recent_request_feed_from_state(state).append(event)
    if int(event["status_code"]) >= 400:
        get_recent_error_feed_from_state(state).append(event)


def filter_request_events(
    events: list[RequestAuditEvent],
    *,
    provider: str | None = None,
    endpoint: str | None = None,
) -> list[RequestAuditEvent]:
    """Filter request events by provider and endpoint."""
    filtered = events
    if provider is not None:
        filtered = [item for item in filtered if item.get("provider") == provider]
    if endpoint is not None:
        filtered = [item for item in filtered if item.get("endpoint") == endpoint]
    return filtered
