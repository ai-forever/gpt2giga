import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any, Literal, Optional


ProviderName = Literal["openai", "anthropic"]
DEFAULT_GIGACHAT_MODEL = "GigaChat"


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
        if limit is None:
            yield
            return

        semaphore = self._semaphore_for(model, limit)
        acquired = False
        try:
            await self._acquire(semaphore, model, limit, provider)
            acquired = True
            yield
        finally:
            if acquired:
                semaphore.release()

    @staticmethod
    def _validate_limit(limit: int) -> int:
        if limit <= 0:
            msg = "model concurrency limits must be positive integers"
            raise ValueError(msg)
        return int(limit)

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


def resolve_gigachat_model(chat_payload: Any, config: Any) -> str:
    """Resolve the effective upstream model from transformed GigaChat payload."""
    payload_model = getattr(chat_payload, "model", None)
    if payload_model:
        return str(payload_model)

    if isinstance(chat_payload, Mapping):
        payload_model = chat_payload.get("model")
        if payload_model:
            return str(payload_model)

    gigachat_settings = getattr(config, "gigachat_settings", None)
    configured_model = getattr(gigachat_settings, "model", None)
    if configured_model:
        return str(configured_model)

    return DEFAULT_GIGACHAT_MODEL
