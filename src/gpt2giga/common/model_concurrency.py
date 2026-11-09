import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Literal, Optional

from anyio import CancelScope


ProviderName = Literal["openai", "anthropic", "gemini", "internal"]
MODEL_CONCURRENCY_LIMIT_MESSAGE = "Concurrency limit reached for the requested model"
model_request_disconnected: ContextVar[asyncio.Event | None] = ContextVar(
    "model_request_disconnected", default=None
)


class ModelConcurrencyTimeoutError(Exception):
    """Signal that no per-model concurrency slot was acquired."""

    def __init__(
        self,
        model: str,
        limit: int,
        provider: ProviderName = "openai",
    ) -> None:
        self.model = model
        self.limit = limit
        self.provider = provider
        super().__init__(f"Concurrency limit reached for model {model}: {limit}")


class ModelConcurrencyLimiter:
    """Limit concurrent upstream GigaChat model calls independently per model."""

    def __init__(
        self,
        limits: Mapping[str, int],
        default_limit: Optional[int] = None,
        acquire_timeout: Optional[float] = None,
    ) -> None:
        self._limits = {
            model: self._validate_limit(limit) for model, limit in limits.items()
        }
        self._default_limit = (
            self._validate_limit(default_limit) if default_limit is not None else None
        )
        if acquire_timeout is not None and acquire_timeout < 0:
            msg = "acquire_timeout must be non-negative or None"
            raise ValueError(msg)
        self._acquire_timeout = acquire_timeout
        self._semaphores: dict[str, asyncio.BoundedSemaphore] = {}
        self._users: dict[str, int] = {}

    def limit_for(self, model: str) -> Optional[int]:
        """Return the configured concurrency limit for a model, if any."""
        return self._limits.get(model, self._default_limit)

    def is_enabled_for(self, model: str) -> bool:
        """Return true when this model has an explicit or default limit."""
        return self.limit_for(model) is not None

    @asynccontextmanager
    async def limit(
        self,
        model: str,
        *,
        provider: ProviderName = "openai",
    ) -> AsyncIterator[None]:
        """Acquire a model slot for the duration of the upstream call."""
        limit = self.limit_for(model)
        disconnected = model_request_disconnected.get()
        if disconnected is not None and disconnected.is_set():
            raise asyncio.CancelledError
        if limit is None:
            yield
            return

        semaphore = self._semaphore_for(model, limit)
        self._users[model] = self._users.get(model, 0) + 1
        acquired = False
        try:
            await self._acquire_connected(
                semaphore, model, limit, provider, disconnected
            )
            acquired = True
            yield
        finally:
            if acquired:
                semaphore.release()
            self._users[model] -= 1
            if self._users[model] == 0:
                del self._users[model]
                if model not in self._limits:
                    del self._semaphores[model]

    @staticmethod
    def _validate_limit(limit: int) -> int:
        if limit <= 0:
            msg = "model concurrency limits must be positive integers"
            raise ValueError(msg)
        return int(limit)

    async def _acquire_connected(self, semaphore, model, limit, provider, disconnected):
        if disconnected is None:
            await self._acquire(semaphore, model, limit, provider)
            return
        slot = asyncio.create_task(self._acquire(semaphore, model, limit, provider))
        gone = asyncio.create_task(disconnected.wait())
        try:
            await asyncio.wait((slot, gone), return_when=asyncio.FIRST_COMPLETED)
            if disconnected.is_set():
                raise asyncio.CancelledError
            await slot
            gone.cancel()
            with CancelScope(shield=True):
                await asyncio.gather(gone, return_exceptions=True)
            if disconnected.is_set():
                raise asyncio.CancelledError
        except BaseException:
            slot.cancel()
            gone.cancel()
            try:
                with CancelScope(shield=True):
                    await asyncio.gather(slot, gone, return_exceptions=True)
            finally:
                if slot.done() and not slot.cancelled() and slot.exception() is None:
                    semaphore.release()
            raise

    def _semaphore_for(self, model: str, limit: int) -> asyncio.BoundedSemaphore:
        semaphore = self._semaphores.get(model)
        if semaphore is None:
            semaphore = asyncio.BoundedSemaphore(limit)
            self._semaphores[model] = semaphore
        return semaphore

    async def _acquire(
        self,
        semaphore: asyncio.BoundedSemaphore,
        model: str,
        limit: int,
        provider: ProviderName,
    ) -> None:
        if self._acquire_timeout is None:
            await semaphore.acquire()
            return

        if self._acquire_timeout == 0:
            if semaphore.locked():
                raise ModelConcurrencyTimeoutError(model, limit, provider)
            await semaphore.acquire()
            return

        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=self._acquire_timeout)
        except asyncio.TimeoutError as exc:
            raise ModelConcurrencyTimeoutError(model, limit, provider) from exc
