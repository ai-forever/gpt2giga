"""OpenAI protocol adapter namespace."""

from gpt2giga.protocols.openai.adapter import OpenAIProtocolAdapter
from gpt2giga.protocols.openai.response_adapter import (
    normalized_chat_response_to_openai,
)
from gpt2giga.protocols.openai.responses_from_normalized import (
    buffered_response_sse_from_normalized_response,
    normalized_response_to_openai_response,
    responses_request_to_normalized,
)
from gpt2giga.protocols.openai.streaming import (
    normalized_stream_done_sse,
    normalized_stream_event_to_openai_chunk,
    normalized_stream_event_to_openai_sse,
)

__all__ = [
    "OpenAIProtocolAdapter",
    "buffered_response_sse_from_normalized_response",
    "normalized_chat_response_to_openai",
    "normalized_response_to_openai_response",
    "normalized_stream_done_sse",
    "normalized_stream_event_to_openai_chunk",
    "normalized_stream_event_to_openai_sse",
    "responses_request_to_normalized",
]
