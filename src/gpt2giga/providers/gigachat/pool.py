"""Bounded reusable GigaChat clients for pass-through credentials."""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable

from gpt2giga.providers.gigachat.auth import create_gigachat_client_for_request


class GigaChatPoolCapacityError(RuntimeError):
    """Reject new credentials while the pool owns its full client budget."""

    def __init__(self) -> None:
        super().__init__("GigaChat client pool is temporarily at capacity")


@dataclass
class _PoolEntry:
    client: Any
    active_requests: int = 0


class GigaChatClientPool:
    """Reuse a bounded set of credential-specific SDK clients."""

    _CLOSE_TIMEOUT_SECONDS = 5.0
    _RETRY_BASE_SECONDS = 0.1
    _RETRY_MAX_SECONDS = 30.0
    _RETRY_BATCH_SIZE = 4
    _clock = staticmethod(time.monotonic)

    def __init__(
        self,
        settings: Any,
        *,
        max_size: int = 32,
        logger: Any | None = None,
        client_factory: Callable[[Any, str], Any] = create_gigachat_client_for_request,
    ) -> None:
        self.settings = settings
        self.max_size = max_size
        self.logger = logger
        self.client_factory = client_factory
        self._entries: OrderedDict[str, _PoolEntry] = OrderedDict()
        self._lock = asyncio.Lock()
        self._closed = False
        self._cleanup_tasks: set[asyncio.Task[None]] = set()
        self._failed_cleanup: dict[int, Any] = {}
        self._closing: dict[int, asyncio.Task[None]] = {}
        self._retired: dict[int, Any] = {}
        self._retry_at: dict[int, float] = {}
        self._retry_attempts: dict[int, int] = {}

    @asynccontextmanager
    async def acquire(self, token: str) -> AsyncIterator[Any]:
        """Lease a client for one request without evicting it mid-stream."""
        await self._retry_cleanup()
        clients_to_close: list[Any]
        async with self._lock:
            if self._closed:
                raise RuntimeError("GigaChat client pool is closed")
            key = hashlib.sha256(token.encode("utf-8")).hexdigest()
            entry = self._entries.get(key)
            if entry is None:
                # Count cached, active and closing clients before allocation.
                # Retaining failed closes must never create an unbounded ledger.
                if len(self._entries) + len(self._retired) >= 2 * self.max_size:
                    raise GigaChatPoolCapacityError
                entry = _PoolEntry(self.client_factory(self.settings, token))
                self._entries[key] = entry
            entry.active_requests += 1
            self._entries.move_to_end(key)
            clients_to_close = self._evict_idle_locked()

        try:
            await self._close_clients(clients_to_close)
            yield entry.client
        finally:
            async with self._lock:
                entry.active_requests -= 1
                clients_to_close = self._evict_idle_locked()
            await self._close_clients(clients_to_close)

    async def aclose(self) -> None:
        """Close every cached client and reject future leases."""
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            clients = [entry.client for entry in self._entries.values()]
            clients.extend(self._failed_cleanup.values())
            self._entries.clear()
        await self._close_clients(clients)
        if self._cleanup_tasks:
            await asyncio.shield(asyncio.gather(*self._cleanup_tasks))

    def _evict_idle_locked(self) -> list[Any]:
        evicted: list[Any] = []
        while len(self._entries) > self.max_size:
            idle_key = next(
                (
                    key
                    for key, entry in self._entries.items()
                    if entry.active_requests == 0
                ),
                None,
            )
            if idle_key is None:
                break
            client = self._entries.pop(idle_key).client
            self._retired[id(client)] = client
            evicted.append(client)
        return evicted

    async def _retry_cleanup(self) -> None:
        # Retry on demand, without a permanent worker or per-request spin loop.
        now = self._clock()
        clients = [
            client
            for key, client in self._failed_cleanup.items()
            if key not in self._closing and self._retry_at[key] <= now
        ][: self._RETRY_BATCH_SIZE]
        await self._close_clients(clients)

    async def _close_clients(self, clients: list[Any]) -> None:
        # Register ownership before awaiting: cancellation of a lease must not
        # orphan an evicted client or interrupt its bounded close operation.
        tasks = []
        for client in clients:
            key = id(client)
            task = self._closing.get(key)
            if task is None:
                self._retired[key] = client
                task = asyncio.create_task(self._close_client(client))
                self._closing[key] = task
                self._cleanup_tasks.add(task)
                task.add_done_callback(self._cleanup_tasks.discard)
            tasks.append(task)
        if tasks:
            await asyncio.shield(asyncio.gather(*tasks))

    async def _close_client(self, client: Any) -> None:
        key = id(client)
        try:
            await asyncio.wait_for(client.aclose(), self._CLOSE_TIMEOUT_SECONDS)
        except (Exception, asyncio.CancelledError):
            self._failed_cleanup[key] = client
            attempts = min(self._retry_attempts.get(key, 0) + 1, 16)
            self._retry_attempts[key] = attempts
            self._retry_at[key] = self._clock() + min(
                self._RETRY_BASE_SECONDS * 2 ** (attempts - 1),
                self._RETRY_MAX_SECONDS,
            )
            if self.logger is not None:
                self.logger.warning("Failed to close pooled GigaChat client")
        else:
            self._failed_cleanup.pop(key, None)
            self._retired.pop(key, None)
            self._retry_attempts.pop(key, None)
            self._retry_at.pop(key, None)
        finally:
            self._closing.pop(key, None)
