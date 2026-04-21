"""Canonical internal contracts shared across provider adapters."""

from gpt2giga.core.contracts.normalized import (
    NormalizedChatRequest,
    NormalizedEmbeddingsRequest,
    NormalizedMessage,
    NormalizedResponsesRequest,
    NormalizedStreamEvent,
    NormalizedTool,
    get_request_model,
    to_backend_payload,
)
from gpt2giga.core.contracts.normalized_artifacts import (
    NormalizedArtifactFormat,
    NormalizedArtifactsInventory,
    NormalizedArtifactsInventoryCounts,
    NormalizedBatchRecord,
    NormalizedBatchRequestCounts,
    NormalizedFileRecord,
    NormalizedFileRef,
)

__all__ = [
    "NormalizedArtifactFormat",
    "NormalizedArtifactsInventory",
    "NormalizedArtifactsInventoryCounts",
    "NormalizedBatchRecord",
    "NormalizedBatchRequestCounts",
    "NormalizedChatRequest",
    "NormalizedEmbeddingsRequest",
    "NormalizedFileRecord",
    "NormalizedFileRef",
    "NormalizedMessage",
    "NormalizedResponsesRequest",
    "NormalizedStreamEvent",
    "NormalizedTool",
    "get_request_model",
    "to_backend_payload",
]
