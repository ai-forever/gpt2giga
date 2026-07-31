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

        await self._close_clients(clients_to_close)
        try:
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
            self._entries.clear()
        await self._close_clients(clients)

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
        for client in clients:
            try:
                await client.aclose()
            except Exception:  # pragma: no cover - best-effort cleanup
                if self.logger is not None:
                    self.logger.warning("Failed to close pooled GigaChat client")
