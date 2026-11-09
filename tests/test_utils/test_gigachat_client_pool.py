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


async def test_cancel_before_yield_releases_lease_and_owns_evicted_cleanup():
    import asyncio

    closing = asyncio.Event()
    release = asyncio.Event()
    created = {}

    class BlockingClient(FakeClient):
        async def aclose(self):
            if self.token == "first":
                closing.set()
                await release.wait()
            await super().aclose()

    def factory(settings, token):
        created[token] = BlockingClient(token)
        return created[token]

    pool = GigaChatClientPool({}, max_size=1, client_factory=factory)
    async with pool.acquire("first"):
        pass

    async def acquire_second():
        async with pool.acquire("second"):
            pytest.fail("cancelled acquisition must not yield")

    task = asyncio.create_task(acquire_second())
    await closing.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert all(entry.active_requests == 0 for entry in pool._entries.values())
    assert pool._cleanup_tasks
    release.set()
    await pool.aclose()
    assert created["first"].closed
    assert created["second"].closed
    assert not pool._cleanup_tasks


async def test_evicted_close_timeout_is_retained_for_shutdown_retry():
    import asyncio

    release = asyncio.Event()
    created = {}

    class BlockingClient(FakeClient):
        async def aclose(self):
            if self.token == "first":
                await release.wait()
            await super().aclose()

    def factory(settings, token):
        created[token] = BlockingClient(token)
        return created[token]

    pool = GigaChatClientPool({}, max_size=1, client_factory=factory)
    pool._CLOSE_TIMEOUT_SECONDS = 0.01
    async with pool.acquire("first"):
        pass
    async with pool.acquire("second"):
        pass
    assert list(pool._failed_cleanup.values()) == [created["first"]]
    release.set()
    await pool.aclose()
    assert all(client.closed for client in created.values())
    assert not pool._failed_cleanup
