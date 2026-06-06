"""OpenAI protocol adapter namespace."""

from gpt2giga.protocols.openai.adapter import OpenAIProtocolAdapter
from gpt2giga.protocols.openai.response_adapter import (
    normalized_chat_response_to_openai,
)

__all__ = ["OpenAIProtocolAdapter", "normalized_chat_response_to_openai"]
