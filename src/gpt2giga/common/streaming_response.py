"""Streaming response lifecycle for pre-acquired model concurrency slots."""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from anyio import CancelScope
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send


@asynccontextmanager
async def closing_stream(stream: AsyncIterator[Any]):
    """Close a delegated iterator in the same task that consumed it."""
    unwinding = False
    try:
        yield stream
    except BaseException:
        unwinding = True
        raise
    finally:
        close = getattr(stream, "aclose", None)
        if close is not None:
            try:
                with CancelScope(shield=True):
                    await close()
            except Exception:
                # Preserve disconnects, cancellations, and GeneratorExit while
                # still surfacing cleanup failures on ordinary completion.
                if not unwinding:
                    raise


class ModelLimitedStreamingResponse(StreamingResponse):
    """Release a pre-acquired slot even if sending response headers fails."""

    def __init__(
        self,
        content: Any,
        *,
        acquired_model_limit: AsyncExitStack,
        **kwargs: Any,
    ) -> None:
        super().__init__(content, **kwargs)
        self._acquired_model_limit = acquired_model_limit

    async def stream_response(self, send: Send) -> None:
        async with closing_stream(self.body_iterator):
            await super().stream_response(send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self._acquired_model_limit.aclose()
