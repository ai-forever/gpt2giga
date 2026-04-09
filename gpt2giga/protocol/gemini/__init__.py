"""Gemini Developer API protocol helpers."""

from gpt2giga.protocol.gemini.request import (
    GeminiAPIError,
    build_openai_data_from_gemini_request,
    extract_embed_texts,
    extract_text_for_token_count,
    model_resource_name,
    normalize_model_name,
    read_gemini_request_json,
)
from gpt2giga.protocol.gemini.response import (
    build_batch_embed_contents_response,
    build_generate_content_response,
    build_gemini_model,
    build_single_embed_content_response,
    gemini_error_response,
    gemini_exceptions_handler,
)
from gpt2giga.protocol.gemini.streaming import stream_gemini_generate_content

__all__ = [
    "GeminiAPIError",
    "build_batch_embed_contents_response",
    "build_generate_content_response",
    "build_gemini_model",
    "build_openai_data_from_gemini_request",
    "build_single_embed_content_response",
    "extract_embed_texts",
    "extract_text_for_token_count",
    "gemini_error_response",
    "gemini_exceptions_handler",
    "model_resource_name",
    "normalize_model_name",
    "read_gemini_request_json",
    "stream_gemini_generate_content",
]
