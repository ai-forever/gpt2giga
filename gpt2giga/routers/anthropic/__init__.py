"""Anthropic router package."""

from fastapi import APIRouter

from gpt2giga.routers.anthropic.batches import (
    _build_anthropic_batch_error,
    _build_anthropic_batch_object,
    _build_anthropic_batch_request_counts,
    _build_anthropic_batch_results,
    _paginate_anthropic_batches,
    _rfc3339_from_timestamp,
    router as batches_router,
)
from gpt2giga.routers.anthropic.conversion import (
    _build_openai_data_from_anthropic_request,
    _convert_anthropic_messages_to_openai,
    _convert_anthropic_tools_to_openai,
    _convert_assistant_blocks,
    _convert_user_blocks,
    _extract_text_from_openai_messages,
    _extract_tool_definitions_text,
)
from gpt2giga.routers.anthropic.messages import router as messages_router
from gpt2giga.routers.anthropic.responses import (
    _anthropic_http_exception,
    _build_anthropic_response,
    _map_stop_reason,
)
from gpt2giga.routers.anthropic.streaming import _stream_anthropic_generator

router = APIRouter(tags=["Anthropic"])
router.include_router(messages_router)
router.include_router(batches_router)

__all__ = [
    "router",
    "_anthropic_http_exception",
    "_build_anthropic_batch_error",
    "_build_anthropic_batch_object",
    "_build_anthropic_batch_request_counts",
    "_build_anthropic_batch_results",
    "_build_anthropic_response",
    "_build_openai_data_from_anthropic_request",
    "_convert_anthropic_messages_to_openai",
    "_convert_anthropic_tools_to_openai",
    "_convert_assistant_blocks",
    "_convert_user_blocks",
    "_extract_text_from_openai_messages",
    "_extract_tool_definitions_text",
    "_map_stop_reason",
    "_paginate_anthropic_batches",
    "_rfc3339_from_timestamp",
    "_stream_anthropic_generator",
]
