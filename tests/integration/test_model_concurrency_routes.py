import asyncio

import httpx
from fastapi import FastAPI
from loguru import logger

from gpt2giga.common.model_concurrency import ModelConcurrencyLimiter
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import ResponseProcessor
from gpt2giga.routers.openai import router as openai_router


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self):
        return self.data


class CountingGigachat:
    def __init__(self):
        self.active: dict[str, int] = {}
        self.max_active: dict[str, int] = {}
        self.calls: list[dict[str, str]] = []
        self.release = asyncio.Event()

    async def achat(self, chat):
        return await self._record("achat", chat.get("model", "GigaChat"))

    async def aembeddings(self, texts, model):
        return await self._record("aembeddings", model, embedding=True)

    async def _record(self, method: str, model: str, *, embedding: bool = False):
        self.calls.append({"method": method, "model": model})
        self.active[model] = self.active.get(model, 0) + 1
        self.max_active[model] = max(
            self.max_active.get(model, 0),
            self.active[model],
        )
        try:
            await self.release.wait()
            if embedding:
                return {"data": [{"embedding": [0.1], "index": 0}], "model": model}
            return MockResponse(
                {
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                }
            )
        finally:
            self.active[model] -= 1


class FakeTransformer:
    async def prepare_chat(self, data, giga_client=None):
        return {"model": data.get("model", "GigaChat"), "messages": []}

    async def prepare_response_chat(self, data, giga_client=None):
        return {"model": data.get("model", "GigaChat"), "messages": []}


def _make_app(
    limiter: ModelConcurrencyLimiter | None,
) -> tuple[FastAPI, CountingGigachat]:
    app = FastAPI()
    app.include_router(openai_router)
    gigachat = CountingGigachat()
    app.state.gigachat_client = gigachat
    if limiter is not None:
        app.state.model_concurrency_limiter = limiter
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.request_transformer = FakeTransformer()
    app.state.config = ProxyConfig(proxy=ProxySettings(gigachat_api_mode="v1"))
    return app, gigachat


async def _wait_for_calls(gigachat: CountingGigachat, count: int) -> None:
    while len(gigachat.calls) < count:
        await asyncio.sleep(0)


async def _post_chat(client: httpx.AsyncClient, model: str):
    return await client.post(
        "/chat/completions",
        json={"model": model, "messages": [{"role": "user", "content": "hi"}]},
    )


async def _post_response(client: httpx.AsyncClient, model: str):
    return await client.post("/responses", json={"model": model, "input": "hi"})


async def test_model_concurrency_caps_six_calls_to_five_active() -> None:
    app, gigachat = _make_app(
        ModelConcurrencyLimiter({"GigaChat": 1, "GigaChat-Pro": 1, "GigaChat-Max": 5})
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        tasks = [
            asyncio.create_task(_post_chat(client, "GigaChat-Max")) for _ in range(6)
        ]
        await _wait_for_calls(gigachat, 5)

        assert gigachat.active["GigaChat-Max"] == 5

        gigachat.release.set()
        responses = await asyncio.gather(*tasks)

    assert [response.status_code for response in responses] == [200] * 6
    assert gigachat.max_active["GigaChat-Max"] == 5


async def test_model_concurrency_independent_across_openai_routes() -> None:
    app, gigachat = _make_app(
        ModelConcurrencyLimiter({"GigaChat": 1, "GigaChat-Pro": 1})
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        chat = asyncio.create_task(_post_chat(client, "GigaChat"))
        response = asyncio.create_task(_post_response(client, "GigaChat-Pro"))
        await _wait_for_calls(gigachat, 2)

        assert gigachat.active == {"GigaChat": 1, "GigaChat-Pro": 1}

        gigachat.release.set()
        chat_response, responses_response = await asyncio.gather(chat, response)

    assert chat_response.status_code == 200
    assert responses_response.status_code == 200


async def test_model_concurrency_default_limit_is_per_unknown_model() -> None:
    app, gigachat = _make_app(ModelConcurrencyLimiter({}, default_limit=1))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        first = asyncio.create_task(_post_chat(client, "Unknown-A"))
        await _wait_for_calls(gigachat, 1)
        second = asyncio.create_task(_post_response(client, "Unknown-A"))
        third = asyncio.create_task(_post_response(client, "Unknown-B"))
        await _wait_for_calls(gigachat, 2)

        assert gigachat.active == {"Unknown-A": 1, "Unknown-B": 1}

        gigachat.release.set()
        responses = await asyncio.gather(first, second, third)

    assert [response.status_code for response in responses] == [200, 200, 200]
    assert gigachat.max_active["Unknown-A"] == 1
    assert gigachat.max_active["Unknown-B"] == 1


async def test_model_concurrency_disabled_mode_does_not_limit_routes() -> None:
    app, gigachat = _make_app(None)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        first = asyncio.create_task(_post_chat(client, "GigaChat"))
        second = asyncio.create_task(_post_response(client, "GigaChat"))
        await _wait_for_calls(gigachat, 2)
        gigachat.release.set()
        responses = await asyncio.gather(first, second)

    assert [response.status_code for response in responses] == [200, 200]
    assert gigachat.max_active["GigaChat"] == 2
