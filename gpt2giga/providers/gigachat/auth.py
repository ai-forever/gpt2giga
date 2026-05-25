"""GigaChat authentication and request-scoped client helpers."""

from typing import Any

from gigachat import GigaChat
from gigachat.settings import SCOPE

from gpt2giga.core.constants import _AUTH_KEYS
from gpt2giga.providers.gigachat.client import dump_gigachat_settings


def pass_token_to_gigachat(gigachat_client: GigaChat, token: str) -> GigaChat:
    """Apply a pass-through token to an existing GigaChat client settings object."""
    gigachat_client._settings.credentials = None
    gigachat_client._settings.user = None
    gigachat_client._settings.password = None
    if token.startswith("giga-user-"):
        user, password = token.replace("giga-user-", "", 1).split(":")
        gigachat_client._settings.user = user
        gigachat_client._settings.password = password
    elif token.startswith("giga-cred-"):
        parts = token.replace("giga-cred-", "", 1).split(":")
        gigachat_client._settings.credentials = parts[0]
        gigachat_client._settings.scope = parts[1] if len(parts) > 1 else SCOPE
    return gigachat_client


def create_gigachat_client_for_request(settings: Any, token: str) -> GigaChat:
    """Build a request-scoped GigaChat client for a pass-through auth token."""
    if token.startswith("giga-auth-"):
        kwargs = dump_gigachat_settings(settings)
        for key in _AUTH_KEYS:
            kwargs.pop(key, None)
        kwargs["access_token"] = token.replace("giga-auth-", "", 1)
        return GigaChat(**kwargs)

    gigachat_client = GigaChat(**dump_gigachat_settings(settings))
    return pass_token_to_gigachat(gigachat_client, token)
