"""Usage reporting service for the admin UI."""

from __future__ import annotations

from collections.abc import Mapping

from starlette.requests import Request

from gpt2giga.app.dependencies import get_runtime_stores
from gpt2giga.app._admin_runtime.shared import (
    _collect_usage_filter_options,
    _matches_usage_filters,
    _normalize_optional_text,
    _sorted_usage_entries,
    _usage_summary,
)


class AdminUsageReporter:
    """Build aggregated usage reporting payloads for admin endpoints."""

    def __init__(self, request: Request) -> None:
        self.request = request

    def build_payload(
        self,
        *,
        kind: str,
        limit: int,
        provider: str | None = None,
        model: str | None = None,
        api_key_name: str | None = None,
        source: str | None = None,
    ) -> dict[str, object]:
        """Build an admin payload for aggregated usage entries."""
        stores = get_runtime_stores(self.request.app.state)
        store = stores.usage_by_api_key if kind == "keys" else stores.usage_by_provider
        entries = [
            dict(value)
            for _, value in sorted(store.items(), key=lambda item: str(item[0]))
            if isinstance(value, Mapping)
        ]
        normalized_provider = _normalize_optional_text(provider)
        normalized_model = _normalize_optional_text(model)
        normalized_api_key_name = _normalize_optional_text(api_key_name)
        normalized_source = _normalize_optional_text(source)
        filtered_entries = _sorted_usage_entries(
            [
                entry
                for entry in entries
                if _matches_usage_filters(
                    entry,
                    provider=normalized_provider,
                    model=normalized_model,
                    api_key_name=normalized_api_key_name,
                    source=normalized_source,
                )
            ]
        )
        limited_entries = filtered_entries[:limit]
        return {
            "entries": limited_entries,
            "count": len(limited_entries),
            "kind": kind,
            "limit": limit,
            "filters": {
                "provider": normalized_provider,
                "model": normalized_model,
                "api_key_name": normalized_api_key_name,
                "source": normalized_source,
            },
            "available_filters": _collect_usage_filter_options(entries),
            "summary": _usage_summary(limited_entries),
        }
