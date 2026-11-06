"""GigaChat provider client construction and lifecycle helpers."""

from typing import Any, Mapping, Protocol, TypedDict
import os
import ssl
from importlib.resources import files

import certifi

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
        client_kwargs.update(dict.fromkeys(_REQUEST_AUTH_FIELDS, ""))
        client_kwargs.update(request_auth)

    _validate_username_password_base_url(settings, client_kwargs)
    use_bundled_ca = client_kwargs.pop("use_bundled_ca", True)
    if (
        use_bundled_ca
        and client_kwargs.get("verify_ssl_certs", False)
        and not client_kwargs.get("ssl_context")
        and not client_kwargs.get("ca_bundle_file")
    ):
        cert_file = client_kwargs.get("cert_file")
        if not cert_file and (
            client_kwargs.get("key_file") or client_kwargs.get("key_file_password")
        ):
            raise GigaChatClientConfigurationError(
                "key_file and key_file_password require cert_file"
            )
        trust_env = client_kwargs.get("trust_env", True)
        context = _bundled_ca_context(trust_env=trust_env)
        if cert_file:
            context.load_cert_chain(
                cert_file,
                client_kwargs.get("key_file") or None,
                client_kwargs.get("key_file_password") or None,
            )
            if not client_kwargs.get("auth_ssl_context"):
                client_kwargs["auth_ssl_context"] = _bundled_ca_context(
                    trust_env=trust_env
                )
            client_kwargs.update(cert_file="", key_file="", key_file_password="")
        client_kwargs["ssl_context"] = context
    return GigaChat(**client_kwargs)


def _bundled_ca_context(*, trust_env: bool) -> ssl.SSLContext:
    """Create a fresh verified context with public and bundled trust roots."""
    context = ssl.create_default_context(
        cafile=(os.environ.get("SSL_CERT_FILE") if trust_env else None)
        or certifi.where(),
        capath=os.environ.get("SSL_CERT_DIR") if trust_env else None,
    )
    context.load_verify_locations(
        cadata=files("gpt2giga.providers.gigachat")
        .joinpath("certs/russian_trusted_root_ca.pem")
        .read_text(encoding="ascii")
    )
    return context


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
