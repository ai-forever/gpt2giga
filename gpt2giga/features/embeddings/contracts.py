"""Internal contracts for the embeddings feature."""

from __future__ import annotations

from typing import Any, Protocol, TypeAlias, runtime_checkable

EmbeddingsRequestData: TypeAlias = dict[str, Any]
PreparedEmbeddingsRequest: TypeAlias = dict[str, Any]


@runtime_checkable
class EmbeddingsUpstreamClient(Protocol):
    """Minimal upstream client surface required by the embeddings feature."""

    async def aembeddings(self, texts: list[Any], model: str) -> Any:
        """Create embeddings for normalized input texts."""


@runtime_checkable
class EmbeddingsProviderMapper(Protocol):
    """Provider-specific embeddings request-mapping surface."""

    async def prepare_request(
        self,
        data: EmbeddingsRequestData,
        *,
        embeddings_model: str,
    ) -> PreparedEmbeddingsRequest:
        """Map the feature request into a provider-specific embeddings payload."""
