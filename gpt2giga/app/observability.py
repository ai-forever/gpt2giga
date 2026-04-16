"""Observability helpers shared by middleware and admin endpoints."""

from __future__ import annotations

from gpt2giga.app._observability.context import (
    get_request_audit_metadata,
    set_request_audit_error,
    set_request_audit_model,
    set_request_audit_usage,
)
from gpt2giga.app._observability.feeds import (
    filter_request_events,
    get_recent_error_feed_from_state,
    get_recent_request_feed_from_state,
    query_request_events,
)
from gpt2giga.app._observability.models import (
    RequestAuditEvent,
    RequestAuditMessage,
    RequestAuditUsage,
)
from gpt2giga.app._observability.recording import (
    annotate_request_audit_from_payload,
    annotate_request_audit_request_payload,
    record_request_event,
)

__all__ = [
    "RequestAuditEvent",
    "RequestAuditMessage",
    "RequestAuditUsage",
    "annotate_request_audit_from_payload",
    "annotate_request_audit_request_payload",
    "filter_request_events",
    "get_recent_error_feed_from_state",
    "get_recent_request_feed_from_state",
    "get_request_audit_metadata",
    "query_request_events",
    "record_request_event",
    "set_request_audit_error",
    "set_request_audit_model",
    "set_request_audit_usage",
]
