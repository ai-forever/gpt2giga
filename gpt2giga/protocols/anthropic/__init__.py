"""Anthropic protocol adapter namespace."""

from gpt2giga.protocols.anthropic.response_from_normalized import (
    buffered_anthropic_sse_from_normalized_response,
    normalized_response_to_anthropic_message,
)

__all__ = [
    "buffered_anthropic_sse_from_normalized_response",
    "normalized_response_to_anthropic_message",
]
