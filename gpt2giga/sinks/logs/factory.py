"""Factory and safe helpers for traffic log sinks."""

from __future__ import annotations

from typing import Any

from gpt2giga.core.interfaces import TrafficLogSink
from gpt2giga.models.config import ProxySettings
from gpt2giga.sinks.logs.jsonl import JsonlTrafficLogSink
from gpt2giga.sinks.logs.noop import NoopTrafficLogSink


def create_traffic_log_sink(
    settings: ProxySettings,
    *,
    logger: Any | None = None,
) -> TrafficLogSink:
    """Create the configured traffic log sink."""
    if not settings.traffic_log_enabled or settings.traffic_log_sink == "noop":
        return NoopTrafficLogSink()

    if settings.traffic_log_sink == "jsonl":
        return JsonlTrafficLogSink(settings.traffic_log_jsonl_path)

    if logger is not None:
        logger.warning(
            "Unknown traffic log sink configured; using noop",
            sink=settings.traffic_log_sink,
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
