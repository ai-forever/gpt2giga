"""GigaChat client lifecycle and request access helpers."""

from typing import Any

from fastapi import FastAPI, Request
from gigachat import GigaChat

from gpt2giga.app.dependencies import get_runtime_providers, sync_runtime_aliases


def get_gigachat_client(request: Request) -> Any:
    """Return the request-scoped GigaChat client when present."""
    request_state = getattr(request, "state", None)
    request_client = getattr(request_state, "gigachat_client", None)
    if request_client is not None:
        return request_client
    return get_runtime_providers(request.app.state).gigachat_client


def _resolve_gigachat_factory(app: FastAPI):
    """Resolve the configured GigaChat client factory for this app instance."""
    providers = get_runtime_providers(app.state)
    factory_getter = providers.gigachat_factory_getter
    if callable(factory_getter):
        return factory_getter()
    return providers.gigachat_factory or GigaChat


def create_app_gigachat_client(app: FastAPI, *, settings) -> Any:
    """Create and store the app-scoped GigaChat client."""
    gigachat_factory = _resolve_gigachat_factory(app)
    gigachat_client = gigachat_factory(**settings.model_dump())
    providers = get_runtime_providers(app.state)
    providers.gigachat_client = gigachat_client
    sync_runtime_aliases(app.state)
    return gigachat_client


async def close_app_gigachat_client(app: FastAPI, *, logger) -> None:
    """Close the app-scoped GigaChat client when it supports async shutdown."""
    providers = get_runtime_providers(app.state)
    gigachat_client = providers.gigachat_client
    if gigachat_client is None:
        return

    try:
        await gigachat_client.aclose()
        logger.info("GigaChat client closed")
    except Exception as exc:
        logger.warning(f"Error closing GigaChat client: {exc}")
    finally:
        providers.gigachat_client = None
        app.state.gigachat_client = None
