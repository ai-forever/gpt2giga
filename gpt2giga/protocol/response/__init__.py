"""Response transformation (GigaChat -> OpenAI)."""

from .gigachat_v2_adapter import (
    adapt_v2_chunk_to_v1_shape,
    adapt_v2_completion_to_v1_shape,
    adapt_v2_usage,
    extract_v2_assistant_text,
    extract_v2_function_call,
)
from .processor import ResponseProcessor

__all__ = [
    "ResponseProcessor",
    "adapt_v2_chunk_to_v1_shape",
    "adapt_v2_completion_to_v1_shape",
    "adapt_v2_usage",
    "extract_v2_assistant_text",
    "extract_v2_function_call",
]
