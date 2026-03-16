"""Shared router state access helpers."""

from fastapi import Request


def get_gigachat_client(request: Request):
    """Return the request-scoped GigaChat client when present."""
    state = request.app.state
    return getattr(request.state, "gigachat_client", state.gigachat_client)


def get_batch_store(request: Request) -> dict:
    """Return the in-memory batch metadata store."""
    state = request.app.state
    if not hasattr(state, "batch_metadata_store"):
        state.batch_metadata_store = {}
    return state.batch_metadata_store


def get_file_store(request: Request) -> dict:
    """Return the in-memory file metadata store."""
    state = request.app.state
    if not hasattr(state, "file_metadata_store"):
        state.file_metadata_store = {}
    return state.file_metadata_store
