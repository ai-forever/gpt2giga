"""Reusable delegating adapters for thin provider compatibility layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from gpt2giga.core.contracts import (
    NormalizedChatRequest,
    NormalizedEmbeddingsRequest,
    NormalizedResponsesRequest,
)
from gpt2giga.features.models.contracts import ModelDescriptor


class ChatRequestBuilder(Protocol):
    """Callable that builds a normalized chat request."""

    def __call__(
        self,
        payload: dict[str, Any],
        *,
        logger: Any = None,
    ) -> NormalizedChatRequest: ...


class TokenCountTextBuilder(Protocol):
    """Callable that extracts token-count texts from a provider payload."""

    def __call__(self, payload: dict[str, Any]) -> list[str]: ...


class ResponsesRequestBuilder(Protocol):
    """Callable that builds a normalized Responses request."""

    def __call__(
        self,
        payload: dict[str, Any],
        *,
        logger: Any = None,
    ) -> NormalizedResponsesRequest: ...


class EmbeddingsRequestBuilder(Protocol):
    """Callable that builds a normalized embeddings request."""

    def __call__(self, payload: dict[str, Any]) -> NormalizedEmbeddingsRequest: ...


class ModelSerializer(Protocol):
    """Callable that serializes a provider model payload."""

    def __call__(self, model: ModelDescriptor) -> Any: ...


class BatchPayloadBuilder(Protocol):
    """Callable that builds a provider-specific batch payload."""

    def __call__(
        self,
        payload: dict[str, Any],
        *,
        logger: Any = None,
    ) -> Any: ...


@dataclass(frozen=True, slots=True)
class DelegatingChatAdapter:
    """Delegate chat normalization to a request-builder callable."""

    request_builder: ChatRequestBuilder

    def build_normalized_request(
        self,
        payload: dict[str, Any],
        *,
        logger: Any = None,
    ) -> NormalizedChatRequest:
        """Build a canonical chat request from a provider payload."""
        return self.request_builder(payload, logger=logger)


@dataclass(frozen=True, slots=True)
class TokenCountingChatAdapter:
    """Delegate chat normalization and token-count extraction."""

    request_builder: ChatRequestBuilder
    token_count_builder: TokenCountTextBuilder

    def build_normalized_request(
        self,
        payload: dict[str, Any],
        *,
        logger: Any = None,
    ) -> NormalizedChatRequest:
        """Build a canonical chat request from a provider payload."""
        return self.request_builder(payload, logger=logger)

    def build_token_count_texts(self, payload: dict[str, Any]) -> list[str]:
        """Extract text fragments for provider token counting."""
        return self.token_count_builder(payload)


@dataclass(frozen=True, slots=True)
class DelegatingResponsesAdapter:
    """Delegate Responses normalization to a request-builder callable."""

    request_builder: ResponsesRequestBuilder

    def build_normalized_request(
        self,
        payload: dict[str, Any],
        *,
        logger: Any = None,
    ) -> NormalizedResponsesRequest:
        """Build a canonical Responses request from a provider payload."""
        return self.request_builder(payload, logger=logger)


@dataclass(frozen=True, slots=True)
class DelegatingEmbeddingsAdapter:
    """Delegate embeddings normalization to a request-builder callable."""

    request_builder: EmbeddingsRequestBuilder

    def build_normalized_request(
        self,
        payload: dict[str, Any],
    ) -> NormalizedEmbeddingsRequest:
        """Build a canonical embeddings request from a provider payload."""
        return self.request_builder(payload)


@dataclass(frozen=True, slots=True)
class DelegatingModelsAdapter:
    """Delegate model serialization to a callable."""

    serializer: ModelSerializer

    def serialize_model(self, model: ModelDescriptor) -> Any:
        """Build a provider-specific model payload."""
        return self.serializer(model)


@dataclass(frozen=True, slots=True)
class DelegatingBatchesAdapter:
    """Delegate batch-payload building to a callable."""

    payload_builder: BatchPayloadBuilder

    def build_create_payload(
        self,
        payload: dict[str, Any],
        *,
        logger: Any = None,
    ) -> Any:
        """Build provider-specific batch-create input for the feature layer."""
        return self.payload_builder(payload, logger=logger)
