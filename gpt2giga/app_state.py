"""Helpers for request-scoped and application-scoped state."""

from fastapi import Request

from gpt2giga.common.model_concurrency import ModelConcurrencyLimiter


def get_gigachat_client(request: Request):
    """Return the request-scoped GigaChat client when present."""
    app_state = request.app.state
    request_state = getattr(request, "state", None)
    return getattr(request_state, "gigachat_client", app_state.gigachat_client)


def get_model_concurrency_limiter(request: Request) -> ModelConcurrencyLimiter:
    """Return the application-scoped per-model concurrency limiter."""
    app_state = request.app.state
    if not hasattr(app_state, "model_concurrency_limiter"):
        app_state.model_concurrency_limiter = ModelConcurrencyLimiter({})
    return app_state.model_concurrency_limiter


def get_batch_store(request: Request) -> dict:
    """Return the in-memory batch metadata store."""
    app_state = request.app.state
    if not hasattr(app_state, "batch_metadata_store"):
        app_state.batch_metadata_store = {}
    return app_state.batch_metadata_store


def get_file_store(request: Request) -> dict:
    """Return the in-memory file metadata store."""
    app_state = request.app.state
    if not hasattr(app_state, "file_metadata_store"):
        app_state.file_metadata_store = {}
    return app_state.file_metadata_store
