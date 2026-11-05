from types import SimpleNamespace
import ssl
from unittest.mock import MagicMock

import pytest
import httpx
from gigachat.settings import BASE_URL

from gpt2giga.providers.gigachat import client as client_module
from gpt2giga.providers.gigachat.client import (
    GigaChatClientConfigurationError,
    build_gigachat_client,
    create_gigachat_client,
)
from gpt2giga.models.config import GigaChatCLI
from gpt2giga.providers.gigachat.request_options import (
    GigaRequestOptions,
    gigachat_request_options,
)


async def test_configured_session_header_and_request_override(monkeypatch):
    monkeypatch.setenv("GIGACHAT_SESSION_ID", "configured-session")
    for key in ("CREDENTIALS", "USER", "PASSWORD"):
        monkeypatch.delenv(f"GIGACHAT_{key}", raising=False)
    settings = GigaChatCLI(
        base_url="https://gigachat.test/v1", model="test-model", access_token="test"
    )
    seen = []

    def handle(request):
        seen.append(request.headers.get("X-Session-ID"))
        return httpx.Response(
            200, json={"messages": [{"role": "assistant", "content": "ok"}]}
        )

    original_client = httpx.AsyncClient

    def mocked_client(**kwargs):
        return original_client(**kwargs, transport=httpx.MockTransport(handle))

    monkeypatch.setattr(httpx, "AsyncClient", mocked_client)
    async with build_gigachat_client(settings) as client:
        await client.achat.create("hello")
        options = GigaRequestOptions(
            headers={"x-session-id": "request-session"}, query=(), body={}
        )
        async with gigachat_request_options(client, options):
            await client.achat.create("hello")
        await client.achat.create("hello")
    assert seen == ["configured-session", "request-session", "configured-session"]


class FakeSettings:
    def __init__(self, values, *, fields_set=()):
        self.values = values
        self.model_fields_set = set(fields_set)
        self.exclude_none = None

    def model_dump(self, *, exclude_none=False):
        self.exclude_none = exclude_none
        if exclude_none:
            return {
                key: value for key, value in self.values.items() if value is not None
            }
        return dict(self.values)


def test_bundled_ca_is_loaded_for_verified_sdk_clients(monkeypatch):
    constructor = MagicMock()
    monkeypatch.setattr(client_module, "GigaChat", constructor)
    settings = FakeSettings({"verify_ssl_certs": True})
    build_gigachat_client(settings, request_auth={"access_token": "test"})
    context = constructor.call_args.kwargs["ssl_context"]
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    names = [str(cert["subject"]) for cert in context.get_ca_certs()]
    assert any("Russian Trusted Root CA" in name for name in names)
    assert len(names) > 1
    assert settings.values == {"verify_ssl_certs": True}


@pytest.mark.parametrize(
    "override",
    [
        {"verify_ssl_certs": False},
        {"ca_bundle_file": "/custom/ca.pem"},
        {"ssl_context": ssl.create_default_context()},
        {"use_bundled_ca": False},
    ],
)
def test_explicit_tls_configuration_takes_precedence(monkeypatch, override):
    constructor = MagicMock()
    monkeypatch.setattr(client_module, "GigaChat", constructor)
    values = {"verify_ssl_certs": True, "use_bundled_ca": True, **override}
    build_gigachat_client(FakeSettings(values))
    expected = {key: value for key, value in values.items() if key != "use_bundled_ca"}
    constructor.assert_called_once_with(**expected)


def test_bundled_ca_setting_from_environment(monkeypatch):
    monkeypatch.setenv("GIGACHAT_USE_BUNDLED_CA", "false")
    assert GigaChatCLI().use_bundled_ca is False


def test_create_gigachat_client_excludes_none_settings(monkeypatch):
    constructor = MagicMock()
    monkeypatch.setattr(client_module, "GigaChat", constructor)
    settings = FakeSettings(
        {
            "base_url": "https://api.example/v1",
            "credentials": "credential",
            "model": None,
        },
        fields_set={"base_url"},
    )

    create_gigachat_client(settings)

    assert settings.exclude_none is True
    constructor.assert_called_once_with(
        base_url="https://api.example/v1",
        credentials="credential",
    )
    assert settings.values["credentials"] == "credential"


def test_build_gigachat_client_replaces_base_auth_without_mutating_settings(
    monkeypatch,
):
    constructor = MagicMock()
    monkeypatch.setattr(client_module, "GigaChat", constructor)
    settings = FakeSettings(
        {
            "base_url": BASE_URL,
            "credentials": "base-credential",
            "scope": "BASE_SCOPE",
            "access_token": None,
        }
    )

    build_gigachat_client(settings, request_auth={"access_token": "request-token"})

    constructor.assert_called_once_with(base_url=BASE_URL, access_token="request-token")
    assert settings.values["credentials"] == "base-credential"


@pytest.mark.parametrize(
    "auth",
    [
        {"credentials": "credential", "scope": "GIGACHAT_API_PERS"},
        {"access_token": "access-token"},
    ],
)
def test_sdk_default_base_url_remains_valid_for_non_password_auth(monkeypatch, auth):
    constructor = MagicMock()
    monkeypatch.setattr(client_module, "GigaChat", constructor)
    settings = FakeSettings({"base_url": BASE_URL})

    build_gigachat_client(settings, request_auth=auth)

    constructor.assert_called_once()


def test_username_password_auth_requires_explicit_base_url(monkeypatch):
    constructor = MagicMock()
    monkeypatch.setattr(client_module, "GigaChat", constructor)
    settings = FakeSettings(
        {
            "base_url": BASE_URL,
            "user": "user",
            "password": "super-secret-value",
        },
        fields_set={"user", "password"},
    )

    with pytest.raises(GigaChatClientConfigurationError) as exc_info:
        create_gigachat_client(settings)

    assert "GIGACHAT_BASE_URL" in str(exc_info.value)
    assert "super-secret-value" not in str(exc_info.value)
    constructor.assert_not_called()


def test_username_password_auth_accepts_explicit_base_url(monkeypatch):
    constructor = MagicMock(return_value=SimpleNamespace())
    monkeypatch.setattr(client_module, "GigaChat", constructor)
    settings = FakeSettings(
        {
            "base_url": "https://password-auth.example/v1",
            "user": "user",
            "password": "password",
        },
        fields_set={"base_url", "user", "password"},
    )

    result = create_gigachat_client(settings)

    assert result is constructor.return_value
    constructor.assert_called_once_with(
        base_url="https://password-auth.example/v1",
        user="user",
        password="password",
    )
