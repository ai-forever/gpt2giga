"""Provider adapter interfaces for external compatibility layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from gpt2giga.core.contracts import (
    NormalizedChatRequest,
    NormalizedEmbeddingsRequest,
    NormalizedResponsesRequest,
)
from gpt2giga.features.models.contracts import ModelDescriptor


@runtime_checkable
class ChatProviderAdapter(Protocol):
    """Translate provider chat payloads into the canonical chat contract."""

    def build_normalized_request(
        self,
        payload: dict[str, Any],
        *,
        logger: Any = None,
    ) -> NormalizedChatRequest:
        """Build a canonical chat request from a provider payload."""


@runtime_checkable
class TokenCountProviderAdapter(ChatProviderAdapter, Protocol):
    """Extend a chat adapter with provider-specific token-count extraction."""

    def build_token_count_texts(self, payload: dict[str, Any]) -> list[str]:
        """Extract text fragments for upstream token counting."""


@runtime_checkable
class ResponsesProviderAdapter(Protocol):
    """Translate provider Responses payloads into the canonical contract."""

    def build_normalized_request(
        self,
        payload: dict[str, Any],
        *,
        logger: Any = None,
    ) -> NormalizedResponsesRequest:
        """Build a canonical Responses request from a provider payload."""


@runtime_checkable
class EmbeddingsProviderAdapter(Protocol):
    """Translate provider embeddings payloads into the canonical contract."""

    def build_normalized_request(
        self,
        payload: dict[str, Any],
    ) -> NormalizedEmbeddingsRequest:
        """Build a canonical embeddings request from a provider payload."""


@runtime_checkable
class ModelsProviderAdapter(Protocol):
    """Present internal model descriptors in a provider-specific shape."""

    def serialize_model(self, model: ModelDescriptor) -> Any:
        """Build a provider-specific model payload."""


@runtime_checkable
class FilesProviderAdapter(Protocol):
    """Translate provider file-upload payloads into feature-layer arguments."""

    def extract_create_file_args(
        self,
        multipart: dict[str, Any],
    ) -> tuple[str, Any]:
        """Extract normalized file-create arguments from a multipart payload."""


@runtime_checkable
class BatchesProviderAdapter(Protocol):
    """Translate provider batch payloads into feature-layer arguments."""

    def build_create_payload(
        self,
        payload: dict[str, Any],
        *,
        logger: Any = None,
    ) -> Any:
        """Build provider-specific batch-create input for the feature layer."""


@dataclass(frozen=True, slots=True)
class ProviderAdapterBundle:
    """Capability adapters implemented by a provider package."""

    chat: ChatProviderAdapter | None = None
    responses: ResponsesProviderAdapter | None = None
    embeddings: EmbeddingsProviderAdapter | None = None
    models: ModelsProviderAdapter | None = None
    files: FilesProviderAdapter | None = None
    batches: BatchesProviderAdapter | None = None
