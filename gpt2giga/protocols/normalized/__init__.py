"""Normalized protocol model namespace."""

from gpt2giga.protocols.normalized.diagnostics import (
    NormalizationDiagnosticEvent,
    build_normalization_diagnostic,
    normalized_shape_hash,
)
from gpt2giga.protocols.normalized.models import (
    NormalizedChatRequest,
    NormalizedChoice,
    NormalizedContentPart,
    NormalizedEmbeddingRequest,
    NormalizedError,
    NormalizedGenerationConfig,
    NormalizedMessage,
    NormalizedRequest,
    NormalizedResponse,
    NormalizedResponseFormat,
    NormalizedStreamEvent,
    NormalizedStreamEventType,
    NormalizedTool,
    NormalizedToolCall,
    NormalizedUsage,
)
from gpt2giga.protocols.normalized.shadow import (
    is_shadow_normalization_enabled,
    run_openai_chat_shadow_normalization,
)

__all__ = [
    "NormalizationDiagnosticEvent",
    "NormalizedChatRequest",
    "NormalizedChoice",
    "NormalizedContentPart",
    "NormalizedEmbeddingRequest",
    "NormalizedError",
    "NormalizedGenerationConfig",
    "NormalizedMessage",
    "NormalizedRequest",
    "NormalizedResponse",
    "NormalizedResponseFormat",
    "NormalizedStreamEvent",
    "NormalizedStreamEventType",
    "NormalizedTool",
    "NormalizedToolCall",
    "NormalizedUsage",
    "build_normalization_diagnostic",
    "is_shadow_normalization_enabled",
    "normalized_shape_hash",
    "run_openai_chat_shadow_normalization",
]
