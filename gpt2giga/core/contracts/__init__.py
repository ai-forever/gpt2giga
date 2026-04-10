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

__all__ = [
    "NormalizedChatRequest",
    "NormalizedEmbeddingsRequest",
    "NormalizedMessage",
    "NormalizedResponsesRequest",
    "NormalizedStreamEvent",
    "NormalizedTool",
    "get_request_model",
    "to_backend_payload",
]
