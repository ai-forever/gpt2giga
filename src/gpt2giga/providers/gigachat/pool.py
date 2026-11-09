"""Bounded reusable GigaChat clients for pass-through credentials."""

from __future__ import annotations

import asyncio
import hashlib
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable

from gpt2giga.providers.gigachat.auth import create_gigachat_client_for_request


@dataclass
class _PoolEntry:
    client: Any
    active_requests: int = 0


class GigaChatClientPool:
    """Reuse a bounded set of credential-specific SDK clients."""

    _CLOSE_TIMEOUT_SECONDS = 5.0

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

    @asynccontextmanager
    async def acquire(self, token: str) -> AsyncIterator[Any]:
        """Lease a client for one request without evicting it mid-stream."""
        clients_to_close: list[Any]
        async with self._lock:
            if self._closed:
                raise RuntimeError("GigaChat client pool is closed")
            key = hashlib.sha256(token.encode("utf-8")).hexdigest()
            entry = self._entries.get(key)
            if entry is None:
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
            self._failed_cleanup.clear()
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
            evicted.append(self._entries.pop(idle_key).client)
        return evicted

    async def _close_clients(self, clients: list[Any]) -> None:
        # Register ownership before awaiting: cancellation of a lease must not
        # orphan an evicted client or interrupt its bounded close operation.
        tasks = [asyncio.create_task(self._close_client(client)) for client in clients]
        for task in tasks:
            self._cleanup_tasks.add(task)
            task.add_done_callback(self._cleanup_tasks.discard)
        if tasks:
            await asyncio.shield(asyncio.gather(*tasks))

    async def _close_client(self, client: Any) -> None:
        try:
            await asyncio.wait_for(client.aclose(), self._CLOSE_TIMEOUT_SECONDS)
        except Exception:
            self._failed_cleanup[id(client)] = client
            if self.logger is not None:
                self.logger.warning("Failed to close pooled GigaChat client")
