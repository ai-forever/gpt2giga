from datetime import datetime, timezone

import pytest

from gpt2giga.models.config import ProxySettings
from gpt2giga.sinks.logs.postgres import PostgresTrafficLogQueryStore
from gpt2giga.sinks.logs.query import create_traffic_log_query_store
from gpt2giga.sinks.logs.retention import (
    purge_expired_traffic_logs,
    retention_cutoff,
    traffic_log_retention_enabled,
)


def test_traffic_log_retention_enabled_only_for_postgres_logging():
    assert not traffic_log_retention_enabled(ProxySettings())
    assert not traffic_log_retention_enabled(
        ProxySettings(
            traffic_log_enabled=True,
            traffic_log_sink="jsonl",
            traffic_log_postgres_dsn="postgresql://example",
        )
    )
    assert traffic_log_retention_enabled(
        ProxySettings(
            traffic_log_enabled=True,
            traffic_log_sink="postgres",
            traffic_log_postgres_dsn="postgresql://example",
        )
    )
    assert traffic_log_retention_enabled(
        ProxySettings(
            traffic_log_enabled=True,
            traffic_log_sinks=["postgres", "opensearch"],
            traffic_log_postgres_dsn="postgresql://example",
        )
    )


def test_traffic_log_query_store_uses_postgres_from_mirror_sinks():
    store = create_traffic_log_query_store(
        ProxySettings(
            traffic_log_enabled=True,
            traffic_log_sinks=["postgres", "opensearch"],
            traffic_log_postgres_dsn="postgresql://example",
        )
    )

    assert isinstance(store, PostgresTrafficLogQueryStore)


def test_retention_cutoff_uses_utc_window():
    cutoff = retention_cutoff(
        30,
        now=datetime(2026, 6, 7, 12, 30, tzinfo=timezone.utc),
    )

    assert cutoff == datetime(2026, 5, 8, 12, 30, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_purge_expired_traffic_logs_calls_store():
    calls = []

    class Store:
        async def purge_expired(
            self,
            *,
            cutoff,
            batch_size,
            dry_run=True,
            max_batches=1,
        ):
            calls.append(
                {
                    "cutoff": cutoff,
                    "batch_size": batch_size,
                    "dry_run": dry_run,
                    "max_batches": max_batches,
                }
            )
            return {"deleted": 2, "dry_run": dry_run}

    cutoff = datetime(2026, 6, 1, tzinfo=timezone.utc)

    result = await purge_expired_traffic_logs(
        Store(),
        cutoff=cutoff,
        batch_size=25,
        dry_run=False,
        max_batches=3,
    )

    assert result == {"deleted": 2, "dry_run": False}
    assert calls == [
        {
            "cutoff": cutoff,
            "batch_size": 25,
            "dry_run": False,
            "max_batches": 3,
        }
    ]
