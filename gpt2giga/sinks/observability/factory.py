"""Factory and safe helpers for observability sinks."""

from __future__ import annotations

from typing import Any

from gpt2giga.core.context import RequestContext
from gpt2giga.core.interfaces import ObservabilitySink
from gpt2giga.models.config import ProxySettings
from gpt2giga.sinks.observability.noop import NoopObservabilitySink
from gpt2giga.sinks.observability.phoenix import create_phoenix_observability_sink


def create_observability_sink(
    settings: ProxySettings,
    *,
    logger: Any | None = None,
) -> ObservabilitySink:
    """Create the configured observability sink."""
    if not settings.observability_enabled or settings.observability_backend == "noop":
        return NoopObservabilitySink()
    if settings.observability_backend == "phoenix":
        try:
            return create_phoenix_observability_sink(settings)
        except Exception as exc:  # pragma: no cover - log branch covered by tests
            if logger is not None:
                logger.warning("Phoenix observability sink disabled: {}", exc)
    return NoopObservabilitySink()


async def emit_observability_event(
    sink: ObservabilitySink,
    name: str,
    attributes: dict[str, Any] | None = None,
    *,
    context: RequestContext | None = None,
    logger: Any | None = None,
) -> None:
    """Emit an observability event without allowing sink errors to break requests."""
    try:
        await sink.emit(name, attributes, context=context)
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
