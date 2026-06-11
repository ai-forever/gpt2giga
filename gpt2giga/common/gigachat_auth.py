"""Compatibility facade for GigaChat provider auth helpers."""

from gpt2giga.providers.gigachat.auth import (
    create_gigachat_client_for_request,
    pass_token_to_gigachat,
)

__all__ = ["create_gigachat_client_for_request", "pass_token_to_gigachat"]
