"""Non-blocking queue wrapper for observability sinks."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from gpt2giga.core.context import RequestContext


@dataclass(frozen=True)
class _ObservabilityEvent:
    name: str
    attributes: Mapping[str, Any] | None
    context: RequestContext | None
    events: Sequence[Mapping[str, Any]] | None


class QueuedObservabilitySink:
    """Export spans in a background task instead of the request path."""

    def __init__(
        self,
        sink: Any,
        *,
        queue_size: int = 10_000,
        drop_on_backpressure: bool = True,
        logger: Any | None = None,
    ) -> None:
        self.sink = sink
        self.drop_on_backpressure = drop_on_backpressure
        self.logger = logger
        self.dropped_events = 0
        self.emitted_events = 0
        self._queue: asyncio.Queue[_ObservabilityEvent] = asyncio.Queue(
            maxsize=queue_size
        )
        self._worker_task: asyncio.Task[None] | None = None

    async def emit(
        self,
        name: str,
        attributes: Mapping[str, Any] | None = None,
        *,
        context: RequestContext | None = None,
        events: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        """Queue an event without waiting for the exporter."""
        self._ensure_worker()
        event = _ObservabilityEvent(name, attributes, context, events)
        if self.drop_on_backpressure:
            try:
                self._queue.put_nowait(event)
            except asyncio.QueueFull:
                self.dropped_events += 1
                if self.logger is not None:
                    self.logger.warning("Observability queue is full; dropping event")
            return
        await self._queue.put(event)

    async def flush(self) -> None:
        """Drain the queue, flush the exporter, and stop the worker."""
        try:
            if self._worker_task is not None:
                await self._queue.join()
            await self.sink.flush()
        finally:
            await self._stop_worker()

    def _ensure_worker(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())

    async def _worker(self) -> None:
        while True:
            try:
                event = await self._queue.get()
            except asyncio.CancelledError:
                break
            try:
                await self.sink.emit(
                    event.name,
                    event.attributes,
                    context=event.context,
                    events=event.events,
                )
                self.emitted_events += 1
            except Exception as exc:  # pragma: no cover - best-effort exporter
                if self.logger is not None:
                    self.logger.warning("Observability queue worker failed: {}", exc)
            finally:
                self._queue.task_done()

    async def _stop_worker(self) -> None:
        if self._worker_task is None:
            return
        if not self._worker_task.done():
            self._worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._worker_task
        self._worker_task = None
