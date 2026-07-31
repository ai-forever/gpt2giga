from unittest.mock import MagicMock

import pytest

from gpt2giga.providers.gigachat.auth import PassTokenError
from gpt2giga.providers.gigachat.pool import GigaChatClientPool


class FakeClient:
    def __init__(self, token: str, *, close_error: Exception | None = None):
        self.token = token
        self.closed = False
        self.close_calls = 0
        self.close_error = close_error

    async def aclose(self):
        self.close_calls += 1
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


async def test_gigachat_client_pool_reuses_clients_for_same_token():
    created = []

    def create_client(settings, token):
        client = FakeClient(token)
        created.append(client)
        return client

    pool = GigaChatClientPool({}, max_size=2, client_factory=create_client)

    async with pool.acquire("giga-auth-one") as first:
        async with pool.acquire("giga-auth-one") as concurrent:
            assert concurrent is first
    async with pool.acquire("giga-auth-one") as second:
        pass

    assert first is second
    assert len(created) == 1
    assert not first.closed
    await pool.aclose()
    assert first.closed
    assert first.close_calls == 1
    await pool.aclose()
    assert first.close_calls == 1


async def test_gigachat_client_pool_evicts_oldest_idle_client():
    created = []

    def create_client(settings, token):
        client = FakeClient(token)
        created.append(client)
        return client

    pool = GigaChatClientPool({}, max_size=1, client_factory=create_client)

    async with pool.acquire("first") as first:
        pass
    async with pool.acquire("second") as second:
        assert first.closed
        assert not second.closed

    await pool.aclose()
    assert second.closed


async def test_gigachat_client_pool_does_not_evict_active_client():
    created = []

    def create_client(settings, token):
        client = FakeClient(token)
        created.append(client)
        return client

    pool = GigaChatClientPool({}, max_size=1, client_factory=create_client)

    async with pool.acquire("first") as first:
        async with pool.acquire("second") as second:
            assert not first.closed
            assert not second.closed
        assert second.closed
        assert not first.closed

    await pool.aclose()
    assert first.closed


async def test_gigachat_client_pool_uses_lru_order_for_idle_clients():
    def create_client(settings, token):
        return FakeClient(token)

    pool = GigaChatClientPool({}, max_size=2, client_factory=create_client)

    async with pool.acquire("first") as first:
        pass
    async with pool.acquire("second") as second:
        pass
    async with pool.acquire("first"):
        pass
    async with pool.acquire("third") as third:
        assert second.closed
        assert not first.closed
        assert not third.closed

    await pool.aclose()
    assert first.closed
    assert third.closed


async def test_gigachat_client_pool_does_not_cache_malformed_token():
    pool = GigaChatClientPool({}, max_size=2)

    with pytest.raises(PassTokenError):
        async with pool.acquire("malformed-secret-token"):
            pass

    assert not pool._entries
    await pool.aclose()


async def test_gigachat_client_pool_close_failure_is_safe_and_redacted():
    secret = "giga-auth-secret-value"
    logger = MagicMock()
    created = []

    def create_client(settings, token):
        close_error = RuntimeError(f"failed to close {secret}") if not created else None
        client = FakeClient(token, close_error=close_error)
        created.append(client)
        return client

    pool = GigaChatClientPool(
        {}, max_size=2, logger=logger, client_factory=create_client
    )
    async with pool.acquire(secret):
        pass
    async with pool.acquire("giga-auth-other"):
        pass

    await pool.aclose()

    assert all(client.close_calls == 1 for client in created)
    logger.warning.assert_called_once_with("Failed to close pooled GigaChat client")
    assert secret not in str(logger.warning.call_args)
