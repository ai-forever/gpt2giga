"""Application-scoped Fusion request concurrency limiter."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class FusionRequestLimiter:
    """Limit concurrently running Fusion requests in one application process."""

    def __init__(self, max_concurrent_requests: int) -> None:
        if max_concurrent_requests < 1:
            raise ValueError("max_concurrent_requests must be positive")
        self.max_concurrent_requests = max_concurrent_requests
        self._semaphore = asyncio.BoundedSemaphore(max_concurrent_requests)

    @asynccontextmanager
    async def limit(self) -> AsyncIterator[None]:
        """Acquire one Fusion request slot."""
        await self._semaphore.acquire()
        try:
            yield
        finally:
            self._semaphore.release()
