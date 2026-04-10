"""Store helpers for the responses feature."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from gpt2giga.app.dependencies import get_runtime_stores
from gpt2giga.features.responses.contracts import ResponsesMetadataStore


def get_response_store_from_state(state: Any) -> ResponsesMetadataStore:
    """Return the responses metadata store from app state."""
    return get_runtime_stores(state).responses


def get_response_store(request: Request) -> ResponsesMetadataStore:
    """Return the responses metadata store for a request."""
    return get_response_store_from_state(request.app.state)
