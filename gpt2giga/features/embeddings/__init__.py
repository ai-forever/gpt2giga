"""Embeddings capability."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from gpt2giga.features.embeddings.service import (
        EmbeddingsService,
        get_embeddings_service_from_state,
    )

__all__ = ["EmbeddingsService", "get_embeddings_service_from_state"]


def __getattr__(name: str) -> Any:
    """Lazily expose the embeddings service surface."""
    if name == "EmbeddingsService":
        from gpt2giga.features.embeddings.service import EmbeddingsService

        return EmbeddingsService
    if name == "get_embeddings_service_from_state":
        from gpt2giga.features.embeddings.service import (
            get_embeddings_service_from_state,
        )

        return get_embeddings_service_from_state
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
