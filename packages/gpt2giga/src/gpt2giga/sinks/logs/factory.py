"""Factory and safe helpers for traffic log sinks."""

from __future__ import annotations

from typing import Any

from gpt2giga.core.interfaces import TrafficLogSink
from gpt2giga.models.config import ProxySettings
from gpt2giga.sinks.logs.composite import CompositeTrafficLogSink
from gpt2giga.sinks.logs.jsonl import JsonlTrafficLogSink
from gpt2giga.sinks.logs.noop import NoopTrafficLogSink
from gpt2giga.sinks.logs.opensearch import OpenSearchTrafficLogSink
from gpt2giga.sinks.logs.postgres import PostgresTrafficLogSink
from gpt2giga.sinks.logs.queue import QueuedTrafficLogSink


def create_traffic_log_sink(
    settings: ProxySettings,
    *,
    logger: Any | None = None,
) -> TrafficLogSink:
    """Create the configured traffic log sink."""
    if not settings.traffic_log_enabled:
        return NoopTrafficLogSink()

    sinks = [
        _create_one_traffic_log_sink(sink_name, settings, logger=logger)
        for sink_name in _configured_sink_names(settings)
        if sink_name != "noop"
    ]
    sinks = [sink for sink in sinks if not isinstance(sink, NoopTrafficLogSink)]
    if not sinks:
        return NoopTrafficLogSink()
    if len(sinks) == 1:
        return sinks[0]
    return CompositeTrafficLogSink(sinks, logger=logger)


def _configured_sink_names(settings: ProxySettings) -> list[str]:
    if settings.traffic_log_sinks:
        return list(dict.fromkeys(settings.traffic_log_sinks))
    return [settings.traffic_log_sink]


def _create_one_traffic_log_sink(
    sink_name: str,
    settings: ProxySettings,
    *,
    logger: Any | None = None,
) -> TrafficLogSink:
    if sink_name == "jsonl":
        return JsonlTrafficLogSink(settings.traffic_log_jsonl_path)

    if sink_name == "postgres":
        if not settings.traffic_log_postgres_dsn:
            if logger is not None:
                logger.warning(
                    "Postgres traffic log sink requested without DSN; using noop"
                )
            return NoopTrafficLogSink()
        return QueuedTrafficLogSink(
            PostgresTrafficLogSink(settings.traffic_log_postgres_dsn, logger=logger),
            queue_size=settings.traffic_log_queue_size,
            batch_size=settings.traffic_log_batch_size,
            flush_interval_ms=settings.traffic_log_flush_interval_ms,
            drop_on_backpressure=settings.traffic_log_drop_on_backpressure,
            logger=logger,
        )

    if sink_name == "opensearch":
        return QueuedTrafficLogSink(
            OpenSearchTrafficLogSink(
                settings.opensearch_url,
                username=settings.opensearch_username,
                password=settings.opensearch_password,
                index=settings.opensearch_index,
                data_stream=settings.opensearch_data_stream,
                logger=logger,
            ),
            queue_size=settings.traffic_log_queue_size,
            batch_size=settings.opensearch_bulk_size,
            flush_interval_ms=settings.opensearch_flush_interval_ms,
            drop_on_backpressure=settings.traffic_log_drop_on_backpressure,
            logger=logger,
        )

    if logger is not None:
        logger.warning(
            "Unknown traffic log sink configured; using noop",
            sink=sink_name,
        )
    return NoopTrafficLogSink()


async def emit_traffic_log(
    sink: TrafficLogSink,
    event: Any,
    *,
    logger: Any | None = None,
) -> None:
    """Emit a traffic event without allowing sink errors to break requests."""
    try:
        await sink.emit(event)
    except Exception as exc:  # pragma: no cover - log branch covered by no-raise tests
        if logger is not None:
            logger.warning("Traffic log sink emit failed: {}", exc)


async def flush_traffic_log_sink(
    sink: TrafficLogSink | None,
    *,
    logger: Any | None = None,
) -> None:
    """Flush a traffic sink without allowing shutdown to crash."""
    if sink is None:
        return
    try:
        await sink.flush()
    except Exception as exc:  # pragma: no cover - log branch covered by no-raise tests
        if logger is not None:
            logger.warning("Traffic log sink flush failed: {}", exc)
