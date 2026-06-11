"""Factory and safe helpers for metrics sinks."""

from __future__ import annotations

from typing import Any

from gpt2giga.core.interfaces import MetricsSink
from gpt2giga.models.config import ProxySettings
from gpt2giga.sinks.metrics.noop import NoopMetricsSink
from gpt2giga.sinks.metrics.prometheus import PrometheusMetricsSink


def create_metrics_sink(settings: ProxySettings) -> MetricsSink:
    """Create the configured metrics sink."""
    if not settings.metrics_enabled:
        return NoopMetricsSink()
    return PrometheusMetricsSink()


async def emit_metric_increment(
    sink: MetricsSink | None,
    name: str,
    value: int = 1,
    attributes: dict[str, Any] | None = None,
    *,
    logger: Any | None = None,
) -> None:
    """Increment a metric without allowing sink errors to break requests."""
    if sink is None:
        return
    try:
        await sink.increment(name, value, attributes)
    except Exception as exc:  # pragma: no cover - covered by no-raise tests
        if logger is not None:
            logger.warning("Metrics sink increment failed: {}", exc)


async def emit_metric_observation(
    sink: MetricsSink | None,
    name: str,
    value: float,
    attributes: dict[str, Any] | None = None,
    *,
    logger: Any | None = None,
) -> None:
    """Record a metric observation without propagating sink failures."""
    if sink is None:
        return
    try:
        await sink.observe(name, value, attributes)
    except Exception as exc:  # pragma: no cover - covered by no-raise tests
        if logger is not None:
            logger.warning("Metrics sink observation failed: {}", exc)


async def flush_metrics_sink(
    sink: MetricsSink | None,
    *,
    logger: Any | None = None,
) -> None:
    """Flush a metrics sink without allowing shutdown to crash."""
    if sink is None:
        return
    try:
        await sink.flush()
    except Exception as exc:  # pragma: no cover - covered by no-raise tests
        if logger is not None:
            logger.warning("Metrics sink flush failed: {}", exc)
