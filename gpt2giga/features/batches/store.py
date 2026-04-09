"""In-memory store helpers for the batches feature."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from gpt2giga.app.dependencies import get_runtime_stores


def get_batch_store_from_state(state: Any) -> dict:
    """Return the in-memory batches metadata store from app state."""
    return get_runtime_stores(state).batches


def get_batch_store(request: Request) -> dict:
    """Return the in-memory batches metadata store for a request."""
    return get_batch_store_from_state(request.app.state)


def find_batch_metadata_by_output_file_id(
    batch_store: dict,
    file_id: str,
) -> dict | None:
    """Return batch metadata for a known batch output file."""
    return next(
        (
            metadata
            for metadata in batch_store.values()
            if metadata.get("output_file_id") == file_id
        ),
        None,
    )
