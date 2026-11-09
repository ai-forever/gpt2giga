"""Composite traffic log sink for mirror backends."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any


class CompositeTrafficLogSink:
    """Emit traffic events to multiple sinks with per-sink isolation."""

    def __init__(self, sinks: Sequence[Any], *, logger: Any | None = None):
        self.sinks = list(sinks)
        self.logger = logger

    async def emit(self, event: Any) -> None:
        """Emit one event to all configured sinks best effort."""
        for sink in self.sinks:
            try:
                await sink.emit(event)
            except Exception as exc:  # pragma: no cover - no-raise behavior tested
                if self.logger is not None:
                    self.logger.warning("Traffic log mirror sink emit failed: {}", exc)

    async def flush(self) -> None:
        """Flush all configured sinks best effort."""
        results = await asyncio.gather(
            *(sink.flush() for sink in self.sinks), return_exceptions=True
        )
        for result in results:
            if isinstance(result, BaseException) and self.logger is not None:
                self.logger.warning("Traffic log mirror sink flush failed: {}", result)

    async def aclose(self) -> None:
        """Close each backend independently, including after a failed drain."""
        results = await asyncio.gather(
            *(getattr(sink, "aclose", sink.flush)() for sink in self.sinks),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException) and self.logger is not None:
                self.logger.warning("Traffic log mirror sink close failed: {}", result)
