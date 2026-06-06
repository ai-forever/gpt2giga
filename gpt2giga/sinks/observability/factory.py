"""Factory and safe helpers for observability sinks."""

from __future__ import annotations

from typing import Any

from gpt2giga.core.interfaces import ObservabilitySink
from gpt2giga.models.config import ProxySettings
from gpt2giga.sinks.observability.noop import NoopObservabilitySink


def create_observability_sink(
    settings: ProxySettings,
    *,
    logger: Any | None = None,
) -> ObservabilitySink:
    """Create the configured observability sink."""
    if settings.observability_enabled and logger is not None:
        logger.info("Observability enabled with noop sink")
    return NoopObservabilitySink()


async def emit_observability_event(
    sink: ObservabilitySink,
    name: str,
    attributes: dict[str, Any] | None = None,
    *,
    logger: Any | None = None,
) -> None:
    """Emit an observability event without allowing sink errors to break requests."""
    try:
        await sink.emit(name, attributes)
    except Exception as exc:  # pragma: no cover - log branch covered by no-raise tests
        if logger is not None:
            logger.warning("Observability sink emit failed: {}", exc)


async def flush_observability_sink(
    sink: ObservabilitySink | None,
    *,
    logger: Any | None = None,
) -> None:
    """Flush an observability sink without allowing shutdown to crash."""
    if sink is None:
        return
    try:
        await sink.flush()
    except Exception as exc:  # pragma: no cover - log branch covered by no-raise tests
        if logger is not None:
            logger.warning("Observability sink flush failed: {}", exc)
