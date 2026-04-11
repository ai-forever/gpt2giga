"""Observability helpers shared by middleware and admin endpoints."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypedDict

from gpt2giga.app.dependencies import get_runtime_observability, get_runtime_stores
from gpt2giga.app.governance import record_governance_event
from gpt2giga.app.runtime_backends import EventFeed


class RequestAuditUsage(TypedDict):
    """Normalized token-usage payload for audit events."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


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
    stream_duration_ms: float | None
    client_ip: str | None
    model: str | None
    token_usage: RequestAuditUsage | None
    error_type: str | None
    api_key_name: str | None
    api_key_source: str | None


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
    if int(event["status_code"]) >= 400 or event.get("error_type") is not None:
        get_recent_error_feed_from_state(state).append(event)
    _record_usage_accounting(state, event)
    record_governance_event(state, event)
    hub = get_runtime_observability(state).hub
    if hub is not None:
        hub.record_request_event(event)


def filter_request_events(
    events: list[RequestAuditEvent],
    *,
    provider: str | None = None,
    endpoint: str | None = None,
    method: str | None = None,
    status_code: int | None = None,
    model: str | None = None,
    error_type: str | None = None,
) -> list[RequestAuditEvent]:
    """Filter request events by normalized admin filter fields."""
    filtered = events
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
        provider=provider,
        endpoint=endpoint,
        method=method,
        status_code=status_code,
        model=model,
        error_type=error_type,
    )


def set_request_audit_model(request: Any, model: str | None) -> None:
    """Persist the requested or resolved model for the current request."""
    if isinstance(model, str) and model:
        _get_request_audit_context(request)["model"] = model


def set_request_audit_usage(
    request: Any, usage: Mapping[str, Any] | None
) -> RequestAuditUsage | None:
    """Persist normalized token usage for the current request."""
    normalized_usage = _normalize_usage_payload(usage)
    if normalized_usage is not None:
        _get_request_audit_context(request)["token_usage"] = normalized_usage
    return normalized_usage


def set_request_audit_error(request: Any, error_type: str | None) -> None:
    """Persist a best-effort error type for the current request."""
    if isinstance(error_type, str) and error_type:
        _get_request_audit_context(request)["error_type"] = error_type


def annotate_request_audit_from_payload(
    request: Any,
    payload: Mapping[str, Any] | None,
    *,
    fallback_model: str | None = None,
) -> None:
    """Extract model and token usage from a provider response payload."""
    if not isinstance(payload, Mapping):
        if fallback_model is not None:
            set_request_audit_model(request, fallback_model)
        return

    model = _extract_model_from_payload(payload) or fallback_model
    if model is not None:
        set_request_audit_model(request, model)
    set_request_audit_usage(request, _extract_usage_from_payload(payload))


def get_request_audit_metadata(request: Any) -> dict[str, Any]:
    """Return normalized request-scoped audit metadata."""
    context = _get_request_audit_context(request)
    return {
        "model": context.get("model"),
        "token_usage": context.get("token_usage"),
        "error_type": context.get("error_type"),
    }


def _record_usage_accounting(state: Any, event: RequestAuditEvent) -> None:
    """Update aggregated usage counters for provider and API-key views."""
    provider = event.get("provider")
    if provider in (None, "admin", "system"):
        return

    stores = get_runtime_stores(state)
    _update_usage_mapping(
        stores.usage_by_provider,
        str(provider),
        event,
        kind="provider",
        display_name=str(provider),
    )

    api_key_name = event.get("api_key_name")
    if api_key_name:
        _update_usage_mapping(
            stores.usage_by_api_key,
            str(api_key_name),
            event,
            kind="api_key",
            display_name=str(api_key_name),
        )


def _update_usage_mapping(
    store: Any,
    key: str,
    event: RequestAuditEvent,
    *,
    kind: str,
    display_name: str,
) -> None:
    """Apply a normalized request event to an aggregated usage mapping."""
    current = store.get(key) if hasattr(store, "get") else None
    record = dict(current) if isinstance(current, Mapping) else {}
    usage = event.get("token_usage") or {}
    prompt_tokens = _safe_int(usage.get("prompt_tokens"))
    completion_tokens = _safe_int(usage.get("completion_tokens"))
    total_tokens = _safe_int(usage.get("total_tokens"))
    status_code = _safe_int(event.get("status_code"))
    is_error = status_code >= 400 or event.get("error_type") is not None
    provider = event.get("provider")
    endpoint = event.get("endpoint")
    model = event.get("model")
    created_at = event.get("created_at")
    api_key_name = event.get("api_key_name")
    api_key_source = event.get("api_key_source")

    record.setdefault("kind", kind)
    if kind == "api_key":
        record.setdefault("name", display_name)
        record.setdefault("source", api_key_source or "unknown")
    else:
        record.setdefault("provider", display_name)
    record.setdefault("request_count", 0)
    record.setdefault("success_count", 0)
    record.setdefault("error_count", 0)
    record.setdefault("prompt_tokens", 0)
    record.setdefault("completion_tokens", 0)
    record.setdefault("total_tokens", 0)
    record.setdefault("models", {})
    record.setdefault("endpoints", {})
    if kind == "api_key":
        record.setdefault("providers", {})
    else:
        record.setdefault("api_keys", {})
    record.setdefault("first_seen_at", created_at)
    record["last_seen_at"] = created_at

    record["request_count"] += 1
    if is_error:
        record["error_count"] += 1
    else:
        record["success_count"] += 1
    record["prompt_tokens"] += prompt_tokens
    record["completion_tokens"] += completion_tokens
    record["total_tokens"] += total_tokens

    if isinstance(model, str) and model:
        _update_usage_breakdown(
            record["models"],
            model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            is_error=is_error,
            created_at=created_at,
        )
    if isinstance(endpoint, str) and endpoint:
        _update_usage_breakdown(
            record["endpoints"],
            endpoint,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            is_error=is_error,
            created_at=created_at,
        )
    if kind == "api_key" and isinstance(provider, str) and provider:
        _update_usage_breakdown(
            record["providers"],
            provider,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            is_error=is_error,
            created_at=created_at,
        )
    if kind == "provider" and isinstance(api_key_name, str) and api_key_name:
        _update_usage_breakdown(
            record["api_keys"],
            api_key_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            is_error=is_error,
            created_at=created_at,
            extra={"source": api_key_source or "unknown"},
        )

    store[key] = record


def _update_usage_breakdown(
    breakdown: dict[str, Any],
    bucket_key: str,
    *,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    is_error: bool,
    created_at: str | None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """Update a nested usage bucket grouped by model/provider/endpoint/key."""
    item = dict(breakdown.get(bucket_key) or {})
    item.setdefault("request_count", 0)
    item.setdefault("success_count", 0)
    item.setdefault("error_count", 0)
    item.setdefault("prompt_tokens", 0)
    item.setdefault("completion_tokens", 0)
    item.setdefault("total_tokens", 0)
    item.setdefault("first_seen_at", created_at)
    item["last_seen_at"] = created_at
    item["request_count"] += 1
    if is_error:
        item["error_count"] += 1
    else:
        item["success_count"] += 1
    item["prompt_tokens"] += prompt_tokens
    item["completion_tokens"] += completion_tokens
    item["total_tokens"] += total_tokens
    if extra:
        for extra_key, extra_value in extra.items():
            item.setdefault(extra_key, extra_value)
    breakdown[bucket_key] = item


def _get_request_audit_context(request: Any) -> dict[str, Any]:
    state = getattr(request, "state", None)
    context = getattr(state, "_request_audit_context", None)
    if not isinstance(context, dict):
        context = {}
        if state is not None:
            state._request_audit_context = context
    return context


def _extract_model_from_payload(payload: Mapping[str, Any]) -> str | None:
    model = payload.get("model")
    if isinstance(model, str) and model:
        return model
    model_version = payload.get("modelVersion")
    if isinstance(model_version, str) and model_version:
        return model_version
    return None


def _extract_usage_from_payload(
    payload: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    if "usage" in payload and isinstance(payload.get("usage"), Mapping):
        return payload.get("usage")
    if "usageMetadata" in payload and isinstance(payload.get("usageMetadata"), Mapping):
        return payload.get("usageMetadata")
    return payload


def _normalize_usage_payload(
    usage: Mapping[str, Any] | None,
) -> RequestAuditUsage | None:
    if not isinstance(usage, Mapping):
        return None

    if "prompt_tokens" in usage or "completion_tokens" in usage:
        return {
            "prompt_tokens": _safe_int(usage.get("prompt_tokens")),
            "completion_tokens": _safe_int(usage.get("completion_tokens")),
            "total_tokens": _safe_int(usage.get("total_tokens")),
        }

    if "input_tokens" in usage or "output_tokens" in usage:
        return {
            "prompt_tokens": _safe_int(usage.get("input_tokens")),
            "completion_tokens": _safe_int(usage.get("output_tokens")),
            "total_tokens": _safe_int(usage.get("total_tokens")),
        }

    if "promptTokenCount" in usage or "candidatesTokenCount" in usage:
        return {
            "prompt_tokens": _safe_int(usage.get("promptTokenCount")),
            "completion_tokens": _safe_int(usage.get("candidatesTokenCount")),
            "total_tokens": _safe_int(usage.get("totalTokenCount")),
        }

    return None


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
