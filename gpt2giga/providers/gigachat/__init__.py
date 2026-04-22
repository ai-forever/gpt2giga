"""GigaChat provider integration helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from gpt2giga.providers.gigachat.attachments import AttachmentProcessor
    from gpt2giga.providers.gigachat.auth import (
        create_gigachat_client_for_request,
        pass_token_to_gigachat,
    )
    from gpt2giga.providers.gigachat.chat_mapper import GigaChatChatMapper
    from gpt2giga.providers.gigachat.client import (
        close_app_gigachat_client,
        create_app_gigachat_client,
        get_gigachat_client,
    )
    from gpt2giga.providers.gigachat.embeddings_mapper import GigaChatEmbeddingsMapper
    from gpt2giga.providers.gigachat.models_mapper import GigaChatModelsMapper
    from gpt2giga.providers.gigachat.request_mapper import RequestTransformer
    from gpt2giga.providers.gigachat.response_mapper import ResponseProcessor

__all__ = [
    "AttachmentProcessor",
    "close_app_gigachat_client",
    "create_app_gigachat_client",
    "create_gigachat_client_for_request",
    "GigaChatChatMapper",
    "GigaChatEmbeddingsMapper",
    "GigaChatModelsMapper",
    "get_gigachat_client",
    "pass_token_to_gigachat",
    "RequestTransformer",
    "ResponseProcessor",
]


def __getattr__(name: str) -> Any:
    """Lazily expose provider helpers without importing the whole stack eagerly."""
    if name == "AttachmentProcessor":
        from gpt2giga.providers.gigachat.attachments import AttachmentProcessor

        return AttachmentProcessor
    if name in {"create_gigachat_client_for_request", "pass_token_to_gigachat"}:
        from gpt2giga.providers.gigachat.auth import (
            create_gigachat_client_for_request,
            pass_token_to_gigachat,
        )

        if name == "create_gigachat_client_for_request":
            return create_gigachat_client_for_request
        return pass_token_to_gigachat
    if name == "GigaChatChatMapper":
        from gpt2giga.providers.gigachat.chat_mapper import GigaChatChatMapper

        return GigaChatChatMapper
    if name == "GigaChatEmbeddingsMapper":
        from gpt2giga.providers.gigachat.embeddings_mapper import (
            GigaChatEmbeddingsMapper,
        )

        return GigaChatEmbeddingsMapper
    if name in {
        "close_app_gigachat_client",
        "create_app_gigachat_client",
        "get_gigachat_client",
    }:
        from gpt2giga.providers.gigachat.client import (
            close_app_gigachat_client,
            create_app_gigachat_client,
            get_gigachat_client,
        )

        if name == "close_app_gigachat_client":
            return close_app_gigachat_client
        if name == "create_app_gigachat_client":
            return create_app_gigachat_client
        return get_gigachat_client
    if name == "GigaChatModelsMapper":
        from gpt2giga.providers.gigachat.models_mapper import GigaChatModelsMapper

        return GigaChatModelsMapper
    if name == "RequestTransformer":
        from gpt2giga.providers.gigachat.request_mapper import RequestTransformer

        return RequestTransformer
    if name == "ResponseProcessor":
        from gpt2giga.providers.gigachat.response_mapper import ResponseProcessor

        return ResponseProcessor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
