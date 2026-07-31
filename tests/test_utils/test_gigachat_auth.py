from unittest.mock import MagicMock

import pytest
from gigachat.settings import BASE_URL, SCOPE

from gpt2giga.providers.gigachat import client as client_module
from gpt2giga.providers.gigachat.auth import (
    AccessTokenAuth,
    CredentialsAuth,
    PassTokenError,
    UserPasswordAuth,
    create_gigachat_client_for_request,
    parse_pass_token,
)


class FakeSettings:
    def __init__(self, values, *, fields_set=()):
        self.values = values
        self.model_fields_set = set(fields_set)

    def model_dump(self, *, exclude_none=False):
        if exclude_none:
            return {
                key: value for key, value in self.values.items() if value is not None
            }
        return dict(self.values)


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("giga-auth-access-token", AccessTokenAuth("access-token")),
        ("giga-cred-credential", CredentialsAuth("credential", SCOPE)),
        (
            "giga-cred-credential:CUSTOM_SCOPE",
            CredentialsAuth("credential", "CUSTOM_SCOPE"),
        ),
        (
            "giga-user-user:password:with:colons",
            UserPasswordAuth("user", "password:with:colons"),
        ),
    ],
)
def test_parse_pass_token(token, expected):
    assert parse_pass_token(token) == expected


@pytest.mark.parametrize(
    "token",
    [
        "",
        "unsupported-token",
        "giga-auth-",
        "giga-auth-   ",
        "giga-cred-",
        "giga-cred-credential:",
        "giga-user-user",
        "giga-user-:password",
        "giga-user-user:",
    ],
)
def test_parse_pass_token_rejects_malformed_values_without_echoing_secret(token):
    with pytest.raises(PassTokenError) as exc_info:
        parse_pass_token(token)

    assert str(exc_info.value) == "Invalid GigaChat pass-through token"
    if token:
        assert token not in str(exc_info.value)


@pytest.mark.parametrize(
    ("token", "expected_auth"),
    [
        ("giga-auth-access-token", {"access_token": "access-token"}),
        (
            "giga-cred-credential:CUSTOM_SCOPE",
            {"credentials": "credential", "scope": "CUSTOM_SCOPE"},
        ),
    ],
)
def test_create_request_client_uses_public_constructor(
    monkeypatch, token, expected_auth
):
    constructor = MagicMock()
    monkeypatch.setattr(client_module, "GigaChat", constructor)
    settings = FakeSettings(
        {
            "base_url": BASE_URL,
            "credentials": "base-credential",
            "scope": "BASE_SCOPE",
            "key_file_password": "tls-key-password",
        }
    )

    create_gigachat_client_for_request(settings, token)

    constructor.assert_called_once_with(
        base_url=BASE_URL,
        key_file_password="tls-key-password",
        **expected_auth,
    )


def test_create_user_password_client_requires_explicit_base_url(monkeypatch):
    constructor = MagicMock()
    monkeypatch.setattr(client_module, "GigaChat", constructor)
    settings = FakeSettings({"base_url": BASE_URL})

    with pytest.raises(ValueError) as exc_info:
        create_gigachat_client_for_request(settings, "giga-user-user:secret-value")

    assert "GIGACHAT_BASE_URL" in str(exc_info.value)
    assert "secret-value" not in str(exc_info.value)
    constructor.assert_not_called()
