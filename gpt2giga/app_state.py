"""Helpers for request-scoped and application-scoped state."""

from fastapi import Request

from gpt2giga.features.responses.store import get_response_store as _get_response_store


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


def get_response_store(request: Request) -> dict:
    """Compatibility wrapper for the responses metadata store."""
    return _get_response_store(request)
