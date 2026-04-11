"""Anthropic-compatible provider adapters and descriptor."""

from gpt2giga.providers.anthropic.capabilities import (
    ANTHROPIC_PROVIDER_DESCRIPTOR,
    AnthropicBatchValidationError,
    anthropic_provider_adapters,
)

__all__ = [
    "ANTHROPIC_PROVIDER_DESCRIPTOR",
    "AnthropicBatchValidationError",
    "anthropic_provider_adapters",
]
