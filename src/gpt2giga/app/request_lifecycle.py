"""Bounded request draining for graceful gateway shutdown."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from starlette.responses import JSONResponse


class BridgeRequestLifecycle:
    """Track model requests and cancel only the remainder after a deadline."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[Any]] = set()
        self._accepting = True

    @property
    def accepting(self) -> bool:
        """Return whether new model requests may enter the gateway."""
        return self._accepting

    @property
    def active_requests(self) -> int:
        """Return the bounded count of currently tracked model requests."""
        return len(self._tasks)

    @asynccontextmanager
    async def track(self):
        """Track the complete ASGI lifetime of one admitted request."""
        if not self._accepting:
            raise GatewayShuttingDownError
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("A running task is required to track a request.")
        self._tasks.add(task)
        try:
            yield
        finally:
            self._tasks.discard(task)

    async def shutdown(self, *, timeout_seconds: float) -> None:
        """Stop admission, drain to the deadline, then cancel remaining work."""
        self._accepting = False
        tasks = set(self._tasks)
        if not tasks:
            return
        _, pending = await asyncio.wait(tasks, timeout=timeout_seconds)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


class GatewayShuttingDownError(RuntimeError):
    """Raised when a model request arrives after shutdown starts."""


class BridgeRequestLifecycleMiddleware:
    """Track model request streams through their final ASGI body frame."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or not _is_model_request(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        lifecycle = getattr(scope["app"].state, "bridge_request_lifecycle", None)
        if lifecycle is None:
            await self.app(scope, receive, send)
            return
        try:
            async with lifecycle.track():
                await self.app(scope, receive, send)
        except GatewayShuttingDownError:
            await JSONResponse(
                {
                    "schema_version": "gpt2giga.error.v1",
                    "error": {
                        "code": "gateway_not_ready",
                        "message": "Gateway routes are not ready.",
                        "details": [{"reason_id": "gateway_shutting_down"}],
                    },
                },
                status_code=503,
            )(scope, receive, send)


def _is_model_request(path: str) -> bool:
    normalized = path.rstrip("/")
    return normalized.endswith(
        (
            "/chat/completions",
            "/embeddings",
            "/messages",
            "/responses",
            ":generateContent",
            ":streamGenerateContent",
        )
    )
