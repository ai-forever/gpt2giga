from typing import Any

from gigachat import GigaChat
from gigachat.settings import SCOPE

from gpt2giga.constants import _AUTH_KEYS


def pass_token_to_gigachat(gigachat_client: GigaChat, token: str) -> GigaChat:
    """Mutate GigaChat _settings for giga-cred- and giga-user- tokens."""
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
    """Create a request-scoped GigaChat client for the given token.

    For giga-auth- the client is created with access_token in the constructor (required
    by the SDK). For giga-cred- and giga-user- a client is created from settings and
    then _settings is mutated via pass_token_to_gigachat.
    """
    if token.startswith("giga-auth-"):
        kwargs = dict(settings.model_dump())
        for key in _AUTH_KEYS:
            kwargs.pop(key, None)
        kwargs["access_token"] = token.replace("giga-auth-", "", 1)
        return GigaChat(**kwargs)
    gigachat_client = GigaChat(**settings.model_dump())
    return pass_token_to_gigachat(gigachat_client, token)
