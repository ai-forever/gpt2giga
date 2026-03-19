"""Helpers for request-scoped and application-scoped state."""

from fastapi import Request


def get_gigachat_client(request: Request):
    """Return the request-scoped GigaChat client when present."""
    app_state = request.app.state
    return getattr(request.state, "gigachat_client", app_state.gigachat_client)


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


def get_tool_call_store(request: Request) -> dict:
    """Return the in-memory tool-call session store."""
    app_state = request.app.state
    if not hasattr(app_state, "tool_call_session_store"):
        app_state.tool_call_session_store = {}
    return app_state.tool_call_session_store
