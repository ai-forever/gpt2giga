import asyncio

import httpx
from fastapi import FastAPI

from gpt2giga.common.model_concurrency import ModelConcurrencyLimiter
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.routers.openai import router


class GateEmbeddingsClient:
    def __init__(self):
        self.active: dict[str, int] = {}
        self.max_active: dict[str, int] = {}
        self.calls: list[dict] = []
        self.release = asyncio.Event()

    async def aembeddings(self, texts, model):
        self.calls.append({"texts": texts, "model": model})
        self.active[model] = self.active.get(model, 0) + 1
        self.max_active[model] = max(
            self.max_active.get(model, 0),
            self.active[model],
        )
        try:
            await self.release.wait()
            return {"data": [{"embedding": [0.1], "index": 0}], "model": model}
        finally:
            self.active[model] -= 1


def _make_app(
    *,
    limiter: ModelConcurrencyLimiter | None,
    gigachat: GateEmbeddingsClient,
    pass_model: bool = False,
) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.gigachat_client = gigachat
    if limiter is not None:
        app.state.model_concurrency_limiter = limiter
    app.state.config = ProxyConfig(proxy=ProxySettings(pass_model=pass_model))
    return app


async def _post_embedding(client: httpx.AsyncClient, model: str):
    return await client.post("/embeddings", json={"model": model, "input": "hello"})


async def _wait_for_call_count(gigachat: GateEmbeddingsClient, count: int) -> None:
    while len(gigachat.calls) < count:
        await asyncio.sleep(0)


async def test_embeddings_same_model_serializes() -> None:
    limiter = ModelConcurrencyLimiter({"EmbeddingsGigaR": 1})
    gigachat = GateEmbeddingsClient()
    app = _make_app(limiter=limiter, gigachat=gigachat)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        first = asyncio.create_task(_post_embedding(client, "ignored-client-model"))
        await _wait_for_call_count(gigachat, 1)
        second = asyncio.create_task(_post_embedding(client, "ignored-client-model"))
        await asyncio.sleep(0)
        gigachat.release.set()
        first_response, second_response = await asyncio.gather(first, second)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert gigachat.max_active["EmbeddingsGigaR"] == 1


async def test_embeddings_different_models_are_independent() -> None:
    limiter = ModelConcurrencyLimiter({"Embeddings": 1, "Embeddings-2": 1})
    gigachat = GateEmbeddingsClient()
    app = _make_app(limiter=limiter, gigachat=gigachat, pass_model=True)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        first = asyncio.create_task(_post_embedding(client, "Embeddings"))
        second = asyncio.create_task(_post_embedding(client, "Embeddings-2"))
        await _wait_for_call_count(gigachat, 2)

        assert gigachat.active == {"Embeddings": 1, "Embeddings-2": 1}

        gigachat.release.set()
        first_response, second_response = await asyncio.gather(first, second)

    assert first_response.status_code == 200
    assert second_response.status_code == 200


async def test_embeddings_timeout_returns_429() -> None:
    limiter = ModelConcurrencyLimiter({"EmbeddingsGigaR": 1}, acquire_timeout=0)
    gigachat = GateEmbeddingsClient()
    app = _make_app(limiter=limiter, gigachat=gigachat)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        first = asyncio.create_task(_post_embedding(client, "ignored-client-model"))
        await _wait_for_call_count(gigachat, 1)
        limited = await _post_embedding(client, "ignored-client-model")
        gigachat.release.set()
        first_response = await first

    assert first_response.status_code == 200
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "model_concurrency_limit"


async def test_embeddings_disabled_limiter_preserves_concurrency() -> None:
    gigachat = GateEmbeddingsClient()
    app = _make_app(limiter=None, gigachat=gigachat)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        first = asyncio.create_task(_post_embedding(client, "ignored-client-model"))
        second = asyncio.create_task(_post_embedding(client, "ignored-client-model"))
        await _wait_for_call_count(gigachat, 2)
        gigachat.release.set()
        first_response, second_response = await asyncio.gather(first, second)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert gigachat.max_active["EmbeddingsGigaR"] == 2


async def test_embeddings_pass_model_false_uses_transformed_model() -> None:
    limiter = ModelConcurrencyLimiter({"raw-client-model": 1}, acquire_timeout=0)
    gigachat = GateEmbeddingsClient()
    app = _make_app(limiter=limiter, gigachat=gigachat, pass_model=False)

    async with limiter.limit("raw-client-model"):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = asyncio.create_task(_post_embedding(client, "raw-client-model"))
            await _wait_for_call_count(gigachat, 1)
            gigachat.release.set()
            result = await response

    assert result.status_code == 200
    assert gigachat.calls == [{"texts": ["hello"], "model": "EmbeddingsGigaR"}]
