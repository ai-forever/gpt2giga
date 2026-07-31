from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from gigachat.settings import BASE_URL

from gpt2giga.providers.gigachat import client as client_module
from gpt2giga.providers.gigachat.client import (
    GigaChatClientConfigurationError,
    build_gigachat_client,
    create_gigachat_client,
)


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
