"""GigaChat provider authentication helpers."""

from dataclasses import dataclass
from typing import TypeAlias

from gigachat import GigaChat
from gigachat.settings import SCOPE

from gpt2giga.providers.gigachat.client import (
    GigaChatRequestAuth,
    SupportsModelDump,
    build_gigachat_client,
)

_INVALID_PASS_TOKEN_MESSAGE = "Invalid GigaChat pass-through token"


class PassTokenError(ValueError):
    """Report malformed pass-through auth without retaining the raw token."""

    def __init__(self) -> None:
        super().__init__(_INVALID_PASS_TOKEN_MESSAGE)


@dataclass(frozen=True, slots=True)
class AccessTokenAuth:
    """Represent a request-scoped SDK access token."""

    access_token: str


@dataclass(frozen=True, slots=True)
class CredentialsAuth:
    """Represent request-scoped OAuth credentials and scope."""

    credentials: str
    scope: str = SCOPE


@dataclass(frozen=True, slots=True)
class UserPasswordAuth:
    """Represent request-scoped username/password authentication."""

    user: str
    password: str


RequestAuth: TypeAlias = AccessTokenAuth | CredentialsAuth | UserPasswordAuth


def parse_pass_token(token: str) -> RequestAuth:
    """Parse a supported pass-through token without including it in errors."""
    if token.startswith("giga-auth-"):
        return AccessTokenAuth(_required_value(token.removeprefix("giga-auth-")))

    if token.startswith("giga-cred-"):
        raw_credentials = token.removeprefix("giga-cred-")
        credentials, separator, scope = raw_credentials.partition(":")
        credentials = _required_value(credentials)
        if not separator:
            scope = SCOPE
        else:
            scope = _required_value(scope)
        return CredentialsAuth(credentials=credentials, scope=scope)

    if token.startswith("giga-user-"):
        raw_user_password = token.removeprefix("giga-user-")
        user, separator, password = raw_user_password.partition(":")
        if not separator:
            raise PassTokenError
        return UserPasswordAuth(
            user=_required_value(user),
            password=_required_value(password),
        )

    raise PassTokenError


def _required_value(value: str) -> str:
    if not value or not value.strip():
        raise PassTokenError
    return value


def _constructor_auth(auth: RequestAuth) -> GigaChatRequestAuth:
    if isinstance(auth, AccessTokenAuth):
        return {"access_token": auth.access_token}
    if isinstance(auth, CredentialsAuth):
        return {"credentials": auth.credentials, "scope": auth.scope}
    return {"user": auth.user, "password": auth.password}


def create_gigachat_client_for_request(
    settings: SupportsModelDump,
    token: str,
) -> GigaChat:
    """Create a credential-specific client through the public SDK constructor."""
    auth = parse_pass_token(token)
    return build_gigachat_client(settings, request_auth=_constructor_auth(auth))


def pass_token_to_gigachat(settings: SupportsModelDump, token: str) -> GigaChat:
    """Build a pass-token client without mutating an existing SDK client."""
    return create_gigachat_client_for_request(settings, token)
