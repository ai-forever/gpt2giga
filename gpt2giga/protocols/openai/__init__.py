"""OpenAI protocol adapter namespace."""

from gpt2giga.protocols.openai.adapter import OpenAIProtocolAdapter
from gpt2giga.protocols.openai.response_adapter import (
    normalized_chat_response_to_openai,
)
from gpt2giga.protocols.openai.streaming import (
    normalized_stream_done_sse,
    normalized_stream_event_to_openai_chunk,
    normalized_stream_event_to_openai_sse,
)

__all__ = [
    "OpenAIProtocolAdapter",
    "normalized_chat_response_to_openai",
    "normalized_stream_done_sse",
    "normalized_stream_event_to_openai_chunk",
    "normalized_stream_event_to_openai_sse",
]
