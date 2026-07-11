"""Traffic log retention helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from gpt2giga.core.interfaces import TrafficLogQueryStore
from gpt2giga.models.config import ProxySettings
from gpt2giga.sinks.logs.query import TrafficLogQueryUnavailable

DEFAULT_RETENTION_BATCH_SIZE = 1_000


def traffic_log_retention_enabled(settings: ProxySettings) -> bool:
    """Return whether automatic traffic log retention should run."""
    configured_sinks = settings.traffic_log_sinks or [settings.traffic_log_sink]
    return (
        settings.traffic_log_enabled
        and bool(settings.traffic_log_postgres_dsn)
        and "postgres" in configured_sinks
    )


def retention_cutoff(
    retention_days: int,
    *,
    now: datetime | None = None,
) -> datetime:
    """Return the UTC cutoff for a retention window."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc) - timedelta(days=int(retention_days))


async def purge_expired_traffic_logs(
    store: TrafficLogQueryStore,
    *,
    cutoff: datetime,
    batch_size: int = DEFAULT_RETENTION_BATCH_SIZE,
    dry_run: bool = True,
    max_batches: int = 1,
) -> Mapping[str, Any]:
    """Run a retention purge command against a compatible query store."""
    purge = getattr(store, "purge_expired", None)
    if purge is None:
        raise TrafficLogQueryUnavailable(
            "Traffic log retention is available only for Postgres query stores"
        )
    return await purge(
        cutoff=cutoff,
        batch_size=batch_size,
        dry_run=dry_run,
        max_batches=max_batches,
    )


def start_traffic_log_retention_task(
    settings: ProxySettings,
    store: TrafficLogQueryStore,
    *,
    logger: Any | None = None,
) -> asyncio.Task[None] | None:
    """Start the best-effort traffic log retention loop when configured."""
    if not traffic_log_retention_enabled(settings):
        return None
    return asyncio.create_task(
        _retention_loop(settings, store, logger=logger),
        name="gpt2giga-traffic-log-retention",
    )


async def stop_traffic_log_retention_task(
    task: asyncio.Task[None] | None,
    *,
    logger: Any | None = None,
) -> None:
    """Cancel a retention background task without crashing shutdown."""
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return
    except Exception as exc:  # pragma: no cover - defensive shutdown guard
        if logger is not None:
            logger.warning("Traffic log retention task shutdown failed: {}", exc)


async def _retention_loop(
    settings: ProxySettings,
    store: TrafficLogQueryStore,
    *,
    logger: Any | None = None,
) -> None:
    while True:
        await _run_retention_once(settings, store, logger=logger)
        await asyncio.sleep(settings.traffic_log_purge_interval_seconds)


async def _run_retention_once(
    settings: ProxySettings,
    store: TrafficLogQueryStore,
    *,
    logger: Any | None = None,
) -> None:
    cutoff = retention_cutoff(settings.traffic_log_retention_days)
    try:
        await purge_expired_traffic_logs(
            store,
            cutoff=cutoff,
            batch_size=DEFAULT_RETENTION_BATCH_SIZE,
            dry_run=False,
            max_batches=1,
        )
    except TrafficLogQueryUnavailable as exc:
        if logger is not None:
            logger.warning("Traffic log retention skipped: {}", exc)
    except Exception as exc:  # pragma: no cover - best-effort background guard
        if logger is not None:
            logger.warning("Traffic log retention purge failed: {}", exc)
