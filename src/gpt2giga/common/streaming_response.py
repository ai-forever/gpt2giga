"""Streaming response lifecycle for pre-acquired model concurrency slots."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from anyio import CancelScope
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from gpt2giga.common.model_concurrency import model_request_disconnected


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
        acquired_model_limit: AsyncExitStack | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(content, **kwargs)
        self._acquired_model_limit = acquired_model_limit

    async def stream_response(self, send: Send) -> None:
        disconnected = model_request_disconnected.get()
        # The middleware owns ASGI receive. ASGI 2.4's StreamingResponse only
        # notices disconnect on send, which never runs while awaiting an idle
        # upstream. Watch the existing event without adding a receive consumer.
        with CancelScope() as consumer_scope:

            async def watch_disconnect() -> None:
                await disconnected.wait()
                consumer_scope.cancel()

            watcher = (
                asyncio.create_task(watch_disconnect())
                if disconnected is not None
                else None
            )
            try:
                async with closing_stream(self.body_iterator):
                    await super().stream_response(send)
            finally:
                if watcher is not None:
                    watcher.cancel()
                    with CancelScope(shield=True):
                        await asyncio.gather(watcher, return_exceptions=True)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            if self._acquired_model_limit is not None:
                await self._acquired_model_limit.aclose()
