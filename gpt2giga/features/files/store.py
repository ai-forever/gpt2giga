"""In-memory store helpers for the files feature."""

from __future__ import annotations

from typing import Any

from fastapi import Request


def get_file_store_from_state(state: Any) -> dict:
    """Return the in-memory files metadata store from app state."""
    if not hasattr(state, "file_metadata_store"):
        state.file_metadata_store = {}
    return state.file_metadata_store


def get_file_store(request: Request) -> dict:
    """Return the in-memory files metadata store for a request."""
    return get_file_store_from_state(request.app.state)
