"""In-memory store helpers for the responses feature."""

from __future__ import annotations

from typing import Any

from fastapi import Request


def get_response_store_from_state(state: Any) -> dict:
    """Return the in-memory responses metadata store from app state."""
    if not hasattr(state, "response_metadata_store"):
        state.response_metadata_store = {}
    return state.response_metadata_store


def get_response_store(request: Request) -> dict:
    """Return the in-memory responses metadata store for a request."""
    return get_response_store_from_state(request.app.state)
