"""Usage-accounting helpers for request audit events."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from gpt2giga.app.dependencies import get_runtime_stores

from .models import RequestAuditEvent, RequestAuditUsage


def normalize_usage_payload(
    usage: Mapping[str, Any] | None,
) -> RequestAuditUsage | None:
    """Normalize provider-specific usage payloads into a common token shape."""
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


def record_usage_accounting(state: Any, event: RequestAuditEvent) -> None:
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


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
