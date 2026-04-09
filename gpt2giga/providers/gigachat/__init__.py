"""GigaChat provider integration helpers."""

from gpt2giga.providers.gigachat.attachments import AttachmentProcessor
from gpt2giga.providers.gigachat.auth import (
    create_gigachat_client_for_request,
    pass_token_to_gigachat,
)
from gpt2giga.providers.gigachat.chat_mapper import GigaChatChatMapper
from gpt2giga.providers.gigachat.embeddings_mapper import GigaChatEmbeddingsMapper
from gpt2giga.providers.gigachat.client import (
    close_app_gigachat_client,
    create_app_gigachat_client,
    get_gigachat_client,
)
from gpt2giga.providers.gigachat.models_mapper import GigaChatModelsMapper
from gpt2giga.providers.gigachat.request_mapper import RequestTransformer
from gpt2giga.providers.gigachat.response_mapper import ResponseProcessor
from gpt2giga.providers.gigachat.streaming import (
    GigaChatStreamError,
    iter_chat_stream_chunks,
    iter_responses_stream_chunks,
    map_chat_stream_chunk,
)

__all__ = [
    "AttachmentProcessor",
    "close_app_gigachat_client",
    "create_app_gigachat_client",
    "create_gigachat_client_for_request",
    "GigaChatChatMapper",
    "GigaChatEmbeddingsMapper",
    "GigaChatModelsMapper",
    "get_gigachat_client",
    "GigaChatStreamError",
    "iter_chat_stream_chunks",
    "iter_responses_stream_chunks",
    "map_chat_stream_chunk",
    "pass_token_to_gigachat",
    "RequestTransformer",
    "ResponseProcessor",
]
