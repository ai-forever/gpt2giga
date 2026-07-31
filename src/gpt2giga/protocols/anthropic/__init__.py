"""Anthropic protocol adapter namespace."""

from gpt2giga.protocols.anthropic.adapter import AnthropicProtocolAdapter
from gpt2giga.protocols.anthropic.response_adapter import (
    normalized_chat_response_to_anthropic,
)
from gpt2giga.protocols.anthropic.streaming import AnthropicStreamProjector

__all__ = [
    "AnthropicProtocolAdapter",
    "AnthropicStreamProjector",
    "normalized_chat_response_to_anthropic",
]
