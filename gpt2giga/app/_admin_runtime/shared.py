"""Shared helpers for admin runtime payload builders."""

from __future__ import annotations

from collections.abc import Mapping


def _coerce_int_metric(value: object) -> int:
    """Safely coerce loosely-typed usage metrics into integers."""
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return 0
        try:
            return int(normalized)
        except ValueError:
            return 0
    return 0


def _mapping_keys(value: object) -> list[str]:
    """Return normalized string keys from a mapping-like value."""
    if not isinstance(value, Mapping):
        return []
    return [str(key) for key in value.keys()]


def _normalize_optional_text(value: str | None) -> str | None:
    """Normalize empty query-string values into ``None``."""
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _collect_event_filter_options(
    events: list[dict[str, object]],
) -> dict[str, list[object]]:
    """Collect available filter values from recent event payloads."""
    options: dict[str, list[object]] = {}
    for key in ("provider", "endpoint", "method", "status_code", "model", "error_type"):
        values = {
            event.get(key) for event in events if event.get(key) not in (None, "")
        }
        options[key] = sorted(values, key=lambda item: str(item))
    return options


def _sorted_usage_entries(entries: list[dict[str, object]]) -> list[dict[str, object]]:
    """Sort usage entries by tokens and request volume."""
    return sorted(
        entries,
        key=lambda entry: (
            -_coerce_int_metric(entry.get("total_tokens")),
            -_coerce_int_metric(entry.get("request_count")),
            str(entry.get("name") or entry.get("provider") or entry.get("kind") or ""),
        ),
    )


def _collect_usage_filter_options(
    entries: list[dict[str, object]],
) -> dict[str, list[str]]:
    """Collect available filter values from aggregated usage entries."""
    models = sorted(
        {model for entry in entries for model in _mapping_keys(entry.get("models"))}
    )
    providers = sorted(
        {
            provider
            for entry in entries
            for provider in _mapping_keys(entry.get("providers"))
        }
    )
    api_keys = sorted(
        {
            api_key
            for entry in entries
            for api_key in _mapping_keys(entry.get("api_keys"))
        }
    )
    sources = sorted(
        {
            str(source)
            for source in (entry.get("source") for entry in entries)
            if isinstance(source, str) and source
        }
    )
    return {
        "provider": providers,
        "model": models,
        "api_key_name": api_keys,
        "source": sources,
    }


def _usage_summary(entries: list[dict[str, object]]) -> dict[str, int]:
    """Build a compact total summary for aggregated usage entries."""
    return {
        "request_count": sum(
            _coerce_int_metric(entry.get("request_count")) for entry in entries
        ),
        "success_count": sum(
            _coerce_int_metric(entry.get("success_count")) for entry in entries
        ),
        "error_count": sum(
            _coerce_int_metric(entry.get("error_count")) for entry in entries
        ),
        "prompt_tokens": sum(
            _coerce_int_metric(entry.get("prompt_tokens")) for entry in entries
        ),
        "completion_tokens": sum(
            _coerce_int_metric(entry.get("completion_tokens")) for entry in entries
        ),
        "total_tokens": sum(
            _coerce_int_metric(entry.get("total_tokens")) for entry in entries
        ),
    }


def _matches_usage_filters(
    entry: Mapping[str, object],
    *,
    provider: str | None = None,
    model: str | None = None,
    api_key_name: str | None = None,
    source: str | None = None,
) -> bool:
    """Return whether an aggregated usage entry matches the admin filters."""
    if source is not None and entry.get("source") != source:
        return False
    if provider is not None:
        if entry.get("provider") != provider:
            providers = entry.get("providers")
            if not isinstance(providers, Mapping) or provider not in providers:
                return False
    if model is not None:
        models = entry.get("models")
        if not isinstance(models, Mapping) or model not in models:
            return False
    if api_key_name is not None:
        if entry.get("name") != api_key_name:
            api_keys = entry.get("api_keys")
            if not isinstance(api_keys, Mapping) or api_key_name not in api_keys:
                return False
    return True
