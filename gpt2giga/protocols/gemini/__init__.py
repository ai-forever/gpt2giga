"""Gemini-compatible protocol adapters."""

from gpt2giga.protocols.gemini.adapter import GeminiProtocolAdapter
from gpt2giga.protocols.gemini.response_adapter import (
    gemini_response_to_normalized,
    normalized_chat_response_to_gemini,
)
from gpt2giga.protocols.gemini.streaming import (
    normalized_stream_event_to_gemini_sse,
)

__all__ = [
    "GeminiProtocolAdapter",
    "gemini_response_to_normalized",
    "normalized_chat_response_to_gemini",
    "normalized_stream_event_to_gemini_sse",
]
