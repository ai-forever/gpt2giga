"""GigaChat client lifecycle and request access helpers."""

from typing import Any

from fastapi import FastAPI, Request
from gigachat import GigaChat


def get_gigachat_client(request: Request) -> Any:
    """Return the request-scoped GigaChat client when present."""
    app_state = request.app.state
    request_state = getattr(request, "state", None)
    return getattr(request_state, "gigachat_client", app_state.gigachat_client)


def _resolve_gigachat_factory(app: FastAPI):
    """Resolve the configured GigaChat client factory for this app instance."""
    factory_getter = getattr(app.state, "gigachat_factory_getter", None)
    if callable(factory_getter):
        return factory_getter()
    return getattr(app.state, "gigachat_factory", GigaChat)


def create_app_gigachat_client(app: FastAPI, *, settings) -> Any:
    """Create and store the app-scoped GigaChat client."""
    gigachat_factory = _resolve_gigachat_factory(app)
    gigachat_client = gigachat_factory(**settings.model_dump())
    app.state.gigachat_client = gigachat_client
    return gigachat_client


async def close_app_gigachat_client(app: FastAPI, *, logger) -> None:
    """Close the app-scoped GigaChat client when it supports async shutdown."""
    gigachat_client = getattr(app.state, "gigachat_client", None)
    if gigachat_client is None:
        return

    try:
        await gigachat_client.aclose()
        logger.info("GigaChat client closed")
    except Exception as exc:
        logger.warning(f"Error closing GigaChat client: {exc}")
