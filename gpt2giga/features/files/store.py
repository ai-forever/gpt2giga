"""In-memory store helpers for the files feature."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from gpt2giga.app.dependencies import get_runtime_stores


def get_file_store_from_state(state: Any) -> dict:
    """Return the in-memory files metadata store from app state."""
    return get_runtime_stores(state).files


def get_file_store(request: Request) -> dict:
    """Return the in-memory files metadata store for a request."""
    return get_file_store_from_state(request.app.state)
