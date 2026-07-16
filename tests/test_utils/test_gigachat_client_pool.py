from gpt2giga.providers.gigachat.pool import GigaChatClientPool


class FakeClient:
    def __init__(self, token: str):
        self.token = token
        self.closed = False

    async def aclose(self):
        self.closed = True


async def test_gigachat_client_pool_reuses_clients_for_same_token():
    created = []

    def create_client(settings, token):
        client = FakeClient(token)
        created.append(client)
        return client

    pool = GigaChatClientPool({}, max_size=2, client_factory=create_client)

    async with pool.acquire("giga-auth-one") as first:
        pass
    async with pool.acquire("giga-auth-one") as second:
        pass

    assert first is second
    assert len(created) == 1
    assert not first.closed
    await pool.aclose()
    assert first.closed


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
