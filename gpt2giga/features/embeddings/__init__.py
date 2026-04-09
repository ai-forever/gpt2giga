"""Embeddings capability."""

from gpt2giga.features.embeddings.service import (
    EmbeddingsService,
    get_embeddings_service_from_state,
)

__all__ = ["EmbeddingsService", "get_embeddings_service_from_state"]
