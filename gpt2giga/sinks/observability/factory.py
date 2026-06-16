"""Factory and safe helpers for observability sinks."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

from gpt2giga.core.context import RequestContext
from gpt2giga.core.interfaces import ObservabilitySink
from gpt2giga.models.config import ProxySettings
from gpt2giga.sinks.observability.noop import NoopObservabilitySink
from gpt2giga.sinks.observability.phoenix import create_phoenix_observability_sink

DEFAULT_OBSERVABILITY_TIMEOUT_SECONDS = 5.0


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
    sink: ObservabilitySink | None,
    name: str,
    attributes: dict[str, Any] | None = None,
    *,
    context: RequestContext | None = None,
    events: Sequence[Mapping[str, Any]] | None = None,
    logger: Any | None = None,
) -> bool:
    """Emit an observability event and return whether the sink accepted it."""
    if sink is None:
        return False
    try:
        emit_coro = (
            sink.emit(name, attributes, context=context)
            if events is None
            else sink.emit(name, attributes, context=context, events=events)
        )
        await asyncio.wait_for(
            emit_coro,
            timeout=DEFAULT_OBSERVABILITY_TIMEOUT_SECONDS,
        )
        return True
    except asyncio.TimeoutError:
        if logger is not None:
            logger.warning(
                "Observability sink emit timed out after {}s",
                DEFAULT_OBSERVABILITY_TIMEOUT_SECONDS,
            )
        return False
    except Exception as exc:  # pragma: no cover - log branch covered by no-raise tests
        if logger is not None:
            logger.warning("Observability sink emit failed: {}", exc)
        return False


async def flush_observability_sink(
    sink: ObservabilitySink | None,
    *,
    logger: Any | None = None,
) -> None:
    """Flush an observability sink without allowing shutdown to crash."""
    if sink is None:
        return
    try:
        await asyncio.wait_for(
            sink.flush(),
            timeout=DEFAULT_OBSERVABILITY_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        if logger is not None:
            logger.warning(
                "Observability sink flush timed out after {}s",
                DEFAULT_OBSERVABILITY_TIMEOUT_SECONDS,
            )
    except Exception as exc:  # pragma: no cover - log branch covered by no-raise tests
        if logger is not None:
            logger.warning("Observability sink flush failed: {}", exc)
