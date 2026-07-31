"""Pass-token authentication and bounded client-pool contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest
from gigachat.settings import SCOPE, Settings as GigaChatSettings

from gpt2giga.providers.gigachat import client as client_module
from gpt2giga.providers.gigachat.auth import (
    AccessTokenAuth,
    CredentialsAuth,
    PassTokenError,
    UserPasswordAuth,
    create_gigachat_client_for_request,
    parse_pass_token,
)
from gpt2giga.providers.gigachat.pool import GigaChatClientPool


@pytest.mark.parametrize(
    ("token", "expected_auth", "expected_constructor"),
    [
        (
            "giga-auth-access-token",
            AccessTokenAuth("access-token"),
            {"access_token": "access-token"},
        ),
        (
            "giga-cred-credential",
            CredentialsAuth("credential", SCOPE),
            {"credentials": "credential", "scope": SCOPE},
        ),
        (
            "giga-cred-credential:CUSTOM_SCOPE",
            CredentialsAuth("credential", "CUSTOM_SCOPE"),
            {"credentials": "credential", "scope": "CUSTOM_SCOPE"},
        ),
        (
            "giga-user-alice:password:with:colons",
            UserPasswordAuth("alice", "password:with:colons"),
            {"user": "alice", "password": "password:with:colons"},
        ),
    ],
)
def test_pass_token_builds_sdk_client_with_one_public_auth_mode(
    monkeypatch,
    token: str,
    expected_auth: Any,
    expected_constructor: dict[str, str],
) -> None:
    constructor = MagicMock()
    monkeypatch.setattr(client_module, "GigaChat", constructor)
    settings = GigaChatSettings(
        base_url="https://gigachat.test/v1",
        credentials="base-credential",
        scope="BASE_SCOPE",
        verify_ssl_certs=False,
        model="configured-model",
    )

    assert parse_pass_token(token) == expected_auth
    create_gigachat_client_for_request(settings, token)

    kwargs = constructor.call_args.kwargs
    for name, value in expected_constructor.items():
        assert kwargs[name] == value
    for excluded in {"access_token", "credentials", "scope", "user", "password"} - set(
        expected_constructor
    ):
        assert excluded not in kwargs
    assert kwargs["base_url"] == "https://gigachat.test/v1"
    assert kwargs["verify_ssl_certs"] is False
    assert kwargs["model"] == "configured-model"


@pytest.mark.parametrize(
    "token",
    [
        "unsupported-secret",
        "giga-auth-",
        "giga-cred-credential:",
        "giga-user-user",
        "giga-user-:password",
        "giga-user-user:",
    ],
)
def test_malformed_token_fails_closed_without_secret_echo(token: str) -> None:
    with pytest.raises(PassTokenError) as exc_info:
        parse_pass_token(token)

    assert str(exc_info.value) == "Invalid GigaChat pass-through token"
    assert token not in str(exc_info.value)


@dataclass
class PooledClient:
    auth: AccessTokenAuth | CredentialsAuth | UserPasswordAuth
    closed: bool = False

    async def aclose(self) -> None:
        self.closed = True


async def test_pool_reuses_same_auth_and_evicts_oldest_idle_client() -> None:
    created: list[PooledClient] = []

    def factory(_settings: Any, token: str) -> PooledClient:
        client = PooledClient(parse_pass_token(token))
        created.append(client)
        return client

    pool = GigaChatClientPool({}, max_size=1, client_factory=factory)
    async with pool.acquire("giga-auth-first") as first:
        pass
    async with pool.acquire("giga-auth-first") as reused:
        assert reused is first
    async with pool.acquire("giga-cred-second:CUSTOM_SCOPE") as second:
        assert first.closed
        assert not second.closed

    assert len(created) == 2
    assert second.auth == CredentialsAuth("second", "CUSTOM_SCOPE")
    await pool.aclose()
    assert second.closed


async def test_pool_never_evicts_an_active_request_client() -> None:
    def factory(_settings: Any, token: str) -> PooledClient:
        return PooledClient(parse_pass_token(token))

    pool = GigaChatClientPool({}, max_size=1, client_factory=factory)
    async with pool.acquire("giga-auth-first") as first:
        async with pool.acquire("giga-auth-second") as second:
            assert not first.closed
            assert not second.closed
        assert second.closed
        assert not first.closed

    await pool.aclose()
    assert first.closed


async def test_pool_rejects_malformed_token_before_creating_client() -> None:
    pool = GigaChatClientPool({}, max_size=1)

    with pytest.raises(PassTokenError, match="Invalid GigaChat pass-through token"):
        async with pool.acquire("malformed-secret"):
            pass

    await pool.aclose()
