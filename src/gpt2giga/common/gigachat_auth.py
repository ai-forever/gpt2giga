"""Compatibility facade for GigaChat provider auth helpers."""

from gpt2giga.providers.gigachat.auth import (
    AccessTokenAuth,
    CredentialsAuth,
    PassTokenError,
    UserPasswordAuth,
    create_gigachat_client_for_request,
    parse_pass_token,
    pass_token_to_gigachat,
)

__all__ = [
    "AccessTokenAuth",
    "CredentialsAuth",
    "PassTokenError",
    "UserPasswordAuth",
    "create_gigachat_client_for_request",
    "parse_pass_token",
    "pass_token_to_gigachat",
]
