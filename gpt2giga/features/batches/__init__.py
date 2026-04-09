"""Batches capability."""

from gpt2giga.features.batches.service import (
    BatchesService,
    get_batches_service_from_state,
)

__all__ = ["BatchesService", "get_batches_service_from_state"]
