"""Gemini-compatible protocol adapters."""

from gpt2giga.protocols.gemini.adapter import GeminiProtocolAdapter
from gpt2giga.protocols.gemini.response_adapter import (
    normalized_chat_response_to_gemini,
)
from gpt2giga.protocols.gemini.streaming import (
    normalized_stream_event_to_gemini_sse,
)

__all__ = [
    "GeminiProtocolAdapter",
    "normalized_chat_response_to_gemini",
    "normalized_stream_event_to_gemini_sse",
]
