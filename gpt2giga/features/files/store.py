"""Store helpers for the files feature."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from gpt2giga.app.dependencies import get_runtime_stores
from gpt2giga.features.files.contracts import FilesMetadataStore


def get_file_store_from_state(state: Any) -> FilesMetadataStore:
    """Return the files metadata store from app state."""
    return get_runtime_stores(state).files


def get_file_store(request: Request) -> FilesMetadataStore:
    """Return the files metadata store for a request."""
    return get_file_store_from_state(request.app.state)
