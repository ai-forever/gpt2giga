"""Traffic log query store factory and fallback implementations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from gpt2giga.core.interfaces import TrafficLogQueryStore
from gpt2giga.models.config import ProxySettings
from gpt2giga.sinks.logs.postgres import PostgresTrafficLogQueryStore


class TrafficLogQueryUnavailable(RuntimeError):
    """Raised when traffic log queries are requested without a query backend."""


class UnavailableTrafficLogQueryStore:
    """Query store placeholder used when durable logs are not configured."""

    def __init__(self, reason: str):
        self.reason = reason

    async def get(self, event_id: str) -> Any | None:
        """Raise because no query backend is configured."""
        raise TrafficLogQueryUnavailable(self.reason)

    async def get_by_request_id(self, request_id: str) -> Sequence[Any]:
        """Raise because no query backend is configured."""
        raise TrafficLogQueryUnavailable(self.reason)

    async def list(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        filters: Mapping[str, Any] | None = None,
    ) -> Sequence[Any]:
        """Raise because no query backend is configured."""
        raise TrafficLogQueryUnavailable(self.reason)

    async def purge_expired(
        self,
        *,
        cutoff: datetime,
        batch_size: int,
        dry_run: bool = True,
        max_batches: int = 1,
    ) -> Mapping[str, Any]:
        """Raise because no retention backend is configured."""
        raise TrafficLogQueryUnavailable(self.reason)

    async def redact_payloads(
        self,
        event_id: str,
        *,
        fields: Sequence[str],
        metadata: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any] | None:
        """Raise because no redaction backend is configured."""
        raise TrafficLogQueryUnavailable(self.reason)

    async def flush(self) -> None:
        """No-op close hook for lifecycle symmetry."""


def create_traffic_log_query_store(
    settings: ProxySettings,
    *,
    logger: Any | None = None,
) -> TrafficLogQueryStore:
    """Create the configured traffic log query store."""
    if settings.traffic_log_sink == "postgres" and settings.traffic_log_postgres_dsn:
        return PostgresTrafficLogQueryStore(
            settings.traffic_log_postgres_dsn,
            logger=logger,
        )
    return UnavailableTrafficLogQueryStore(
        "Postgres traffic log query store is not configured"
    )


async def close_traffic_log_query_store(
    store: TrafficLogQueryStore | None,
    *,
    logger: Any | None = None,
) -> None:
    """Close a traffic log query store without allowing shutdown to crash."""
    if store is None:
        return
    close = getattr(store, "flush", None) or getattr(store, "close", None)
    if close is None:
        return
    try:
        await close()
    except Exception as exc:  # pragma: no cover - best-effort shutdown guard
        if logger is not None:
            logger.warning("Traffic log query store close failed: {}", exc)
