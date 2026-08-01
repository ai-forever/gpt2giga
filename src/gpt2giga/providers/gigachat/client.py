"""GigaChat provider client construction and lifecycle helpers."""

from typing import Any, Mapping, Protocol, TypedDict

from gigachat import GigaChat
from gigachat.settings import BASE_URL

from gpt2giga.providers.gigachat.types import SupportsAclose

_REQUEST_AUTH_FIELDS = frozenset(
    {"access_token", "credentials", "scope", "user", "password"}
)


class SupportsModelDump(Protocol):
    """Represent settings accepted by the GigaChat client factory."""

    def model_dump(self, *, exclude_none: bool = False) -> dict[str, Any]:
        """Return constructor-compatible settings."""


class GigaChatRequestAuth(TypedDict, total=False):
    """Public GigaChat constructor fields for request-scoped authentication."""

    access_token: str
    credentials: str
    scope: str
    user: str
    password: str


class GigaChatClientConfigurationError(ValueError):
    """Report an unsafe GigaChat client configuration without exposing secrets."""


def create_gigachat_client(settings: SupportsModelDump) -> GigaChat:
    """Create the application-scoped GigaChat SDK client."""
    return build_gigachat_client(settings)


def build_gigachat_client(
    settings: SupportsModelDump,
    *,
    request_auth: GigaChatRequestAuth | None = None,
) -> GigaChat:
    """Build a client from base settings and optional request auth."""
    client_kwargs = settings.model_dump(exclude_none=True)
    if request_auth is not None:
        for key in _REQUEST_AUTH_FIELDS:
            client_kwargs.pop(key, None)
        client_kwargs.update(request_auth)

    _validate_username_password_base_url(settings, client_kwargs)
    return GigaChat(**client_kwargs)


def _validate_username_password_base_url(
    settings: SupportsModelDump,
    client_kwargs: Mapping[str, Any],
) -> None:
    if not (client_kwargs.get("user") or client_kwargs.get("password")):
        return

    base_url = client_kwargs.get("base_url", BASE_URL)
    fields_set = getattr(settings, "model_fields_set", set())
    if base_url == BASE_URL and "base_url" not in fields_set:
        raise GigaChatClientConfigurationError(
            "GIGACHAT_BASE_URL must be set explicitly when using "
            "GIGACHAT_USER/GIGACHAT_PASSWORD authentication; gigachat>=0.2.3 "
            f"defaults to {BASE_URL}"
        )


async def close_gigachat_client(client: SupportsAclose | None, logger: Any) -> None:
    """Close a GigaChat SDK client without failing application shutdown."""
    if client is None:
        return
    try:
        await client.aclose()
        logger.info("GigaChat client closed")
    except Exception as exc:
        logger.warning(f"Error closing GigaChat client: {exc}")
