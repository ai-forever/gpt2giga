"""Compatibility helpers for request-scoped and application-scoped state."""

from fastapi import Request

from gpt2giga.features.batches.store import get_batch_store as _get_batch_store
from gpt2giga.features.files.store import get_file_store as _get_file_store
from gpt2giga.features.responses.store import get_response_store as _get_response_store


def get_batch_store(request: Request) -> dict:
    """Compatibility wrapper for the batches metadata store."""
    return _get_batch_store(request)


def get_file_store(request: Request) -> dict:
    """Compatibility wrapper for the files metadata store."""
    return _get_file_store(request)


def get_response_store(request: Request) -> dict:
    """Compatibility wrapper for the responses metadata store."""
    return _get_response_store(request)
