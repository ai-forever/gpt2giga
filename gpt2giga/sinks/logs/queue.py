"""Non-blocking queue wrapper for traffic log sinks."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any


class QueuedTrafficLogSink:
    """Write traffic events through a background queue."""

    _FLUSH_INTERVAL_FLOOR_SECONDS = 0.001

    def __init__(
        self,
        sink: Any,
        *,
        queue_size: int = 10_000,
        batch_size: int = 500,
        flush_interval_ms: int = 2_000,
        drop_on_backpressure: bool = True,
        logger: Any | None = None,
    ):
        self.sink = sink
        self.queue_size = queue_size
        self.batch_size = batch_size
        self.flush_interval_ms = flush_interval_ms
        self.drop_on_backpressure = drop_on_backpressure
        self.logger = logger
        self.dropped_events = 0
        self.emitted_events = 0
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=queue_size)
        self._worker_task: asyncio.Task[None] | None = None

    async def emit(self, event: Any) -> None:
        """Queue one event without waiting for the storage backend."""
        self._ensure_worker()
        if self.drop_on_backpressure:
            try:
                self._queue.put_nowait(event)
            except asyncio.QueueFull:
                self.dropped_events += 1
                if self.logger is not None:
                    self.logger.warning("Traffic log queue is full; dropping event")
            return

        await self._queue.put(event)

    async def flush(self) -> None:
        """Drain queued events and flush the wrapped sink best effort."""
        if self._worker_task is not None:
            await self._queue.join()
        await self._flush_inner()
        await self._stop_worker()

    def _ensure_worker(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())

    async def _worker(self) -> None:
        while True:
            try:
                event = await asyncio.wait_for(
                    self._queue.get(), timeout=self._flush_interval_seconds
                )
            except asyncio.TimeoutError:
                await self._flush_inner()
                continue
            except asyncio.CancelledError:
                break

            batch = [event]
            while len(batch) < self.batch_size:
                try:
                    batch.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            await self._emit_batch(batch)
            for _ in batch:
                self._queue.task_done()

    async def _emit_batch(self, batch: list[Any]) -> None:
        try:
            emit_many = getattr(self.sink, "emit_many", None)
            if emit_many is not None:
                await emit_many(batch)
            else:
                for event in batch:
                    await self.sink.emit(event)
            self.emitted_events += len(batch)
        except Exception as exc:  # pragma: no cover - covered by no-raise behavior
            if self.logger is not None:
                self.logger.warning("Traffic log queue worker failed: {}", exc)

    async def _flush_inner(self) -> None:
        try:
            await self.sink.flush()
        except Exception as exc:  # pragma: no cover - covered by no-raise behavior
            if self.logger is not None:
                self.logger.warning("Traffic log sink flush failed: {}", exc)

    async def _stop_worker(self) -> None:
        if self._worker_task is None:
            return
        if not self._worker_task.done():
            self._worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._worker_task
        self._worker_task = None

    @property
    def _flush_interval_seconds(self) -> float:
        return max(
            self.flush_interval_ms / 1000,
            self._FLUSH_INTERVAL_FLOOR_SECONDS,
        )
