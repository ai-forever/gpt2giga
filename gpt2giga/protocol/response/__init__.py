"""Response transformation (GigaChat -> OpenAI)."""

from .gigachat_chat_completion_adapter import (
    GIGACHAT_PROVIDER_METADATA_KEY,
    adapt_chat_completion_chunk_to_chat_chunk_shape,
    adapt_chat_completion_to_chat_shape,
    adapt_chat_completion_usage,
    extract_chat_completion_assistant_text,
    extract_chat_completion_function_call,
    extract_chat_completion_thread_id,
    hydrate_chat_completion_image_files,
)
from .processor import ResponseProcessor

__all__ = [
    "GIGACHAT_PROVIDER_METADATA_KEY",
    "ResponseProcessor",
    "adapt_chat_completion_chunk_to_chat_chunk_shape",
    "adapt_chat_completion_to_chat_shape",
    "adapt_chat_completion_usage",
    "extract_chat_completion_assistant_text",
    "extract_chat_completion_function_call",
    "extract_chat_completion_thread_id",
    "hydrate_chat_completion_image_files",
]
