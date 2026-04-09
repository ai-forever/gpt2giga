"""Helpers for request-scoped and application-scoped state."""

from fastapi import Request


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
    """Return the in-memory responses metadata store."""
    app_state = request.app.state
    if not hasattr(app_state, "response_metadata_store"):
        app_state.response_metadata_store = {}
    return app_state.response_metadata_store
