import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from loguru import logger

from gpt2giga.common.model_concurrency import (
    ModelConcurrencyLimiter,
    ModelConcurrencyTimeoutError,
)
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import ResponseProcessor
from gpt2giga.routers.openai import router


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self):
        return self.data


class GateGigachat:
    def __init__(self):
        self.active: dict[str, int] = {}
        self.max_active: dict[str, int] = {}
        self.call_count = 0
        self.release = asyncio.Event()

    async def achat(self, chat):
        model = chat.get("model", "GigaChat")
        self.call_count += 1
        self.active[model] = self.active.get(model, 0) + 1
        self.max_active[model] = max(
            self.max_active.get(model, 0),
            self.active[model],
        )
        try:
            await self.release.wait()
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


class RecordingTransformer:
    def __init__(self):
        self.prepared_count = 0
        self.second_prepared = asyncio.Event()

    async def prepare_chat(self, data, giga_client=None):
        return {"model": data.get("model", "GigaChat"), "messages": []}

    async def prepare_response_chat(self, data, giga_client=None):
        self.prepared_count += 1
        if self.prepared_count == 2:
            self.second_prepared.set()
        return {"model": data.get("model", "GigaChat"), "messages": []}


class StreamingGigachat:
    def __init__(self):
        self.astream_calls = 0

    def astream(self, chat):
        self.astream_calls += 1

        async def gen():
            yield MockResponse(
                {
                    "choices": [{"delta": {"content": "A"}, "finish_reason": None}],
                    "usage": None,
                }
            )
            yield MockResponse(
                {
                    "choices": [{"delta": {"content": "B"}, "finish_reason": None}],
                    "usage": None,
                }
            )

        return gen()


class FakeAppState:
    def __init__(self, client, limiter):
        self.gigachat_client = client
        self.model_concurrency_limiter = limiter
        self.response_processor = ResponseProcessor(logger=logger)
        self.config = ProxyConfig(proxy=ProxySettings(gigachat_api_mode="v1"))


class FakeStreamRequest:
    def __init__(self, client, limiter):
        self.app = SimpleNamespace(state=FakeAppState(client, limiter))

    async def is_disconnected(self):
        return False


def _make_responses_app(
    *,
    limiter: ModelConcurrencyLimiter,
    gigachat: GateGigachat,
    transformer: RecordingTransformer | None = None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.gigachat_client = gigachat
    app.state.model_concurrency_limiter = limiter
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.request_transformer = transformer or RecordingTransformer()
    app.state.config = ProxyConfig(proxy=ProxySettings(gigachat_api_mode="v1"))
    return app


async def _post_response(client: httpx.AsyncClient, model: str):
    return await client.post("/responses", json={"model": model, "input": "hi"})


async def _post_stream_response(client: httpx.AsyncClient, model: str):
    return await client.post(
        "/responses",
        json={"model": model, "input": "hi", "stream": True},
    )


async def _wait_for_call_count(gigachat: GateGigachat, count: int) -> None:
    while gigachat.call_count < count:
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_responses_non_stream_serializes_same_model() -> None:
    limiter = ModelConcurrencyLimiter({"GigaChat": 1})
    gigachat = GateGigachat()
    transformer = RecordingTransformer()
    app = _make_responses_app(
        limiter=limiter,
        gigachat=gigachat,
        transformer=transformer,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        first = asyncio.create_task(_post_response(client, "GigaChat"))
        await _wait_for_call_count(gigachat, 1)
        second = asyncio.create_task(_post_response(client, "GigaChat"))
        await asyncio.wait_for(transformer.second_prepared.wait(), timeout=1)

        assert gigachat.call_count == 1

        gigachat.release.set()
        first_response, second_response = await asyncio.gather(first, second)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert gigachat.max_active["GigaChat"] == 1


@pytest.mark.asyncio
async def test_responses_non_stream_timeout_returns_429() -> None:
    limiter = ModelConcurrencyLimiter({"GigaChat": 1}, acquire_timeout=0)
    gigachat = GateGigachat()
    app = _make_responses_app(limiter=limiter, gigachat=gigachat)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        first = asyncio.create_task(_post_response(client, "GigaChat"))
        await _wait_for_call_count(gigachat, 1)
        limited = await _post_response(client, "GigaChat")
        gigachat.release.set()
        first_response = await first

    assert first_response.status_code == 200
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "model_concurrency_limit"


@pytest.mark.asyncio
async def test_responses_stream_timeout_returns_http_429_before_sse() -> None:
    limiter = ModelConcurrencyLimiter({"GigaChat": 1}, acquire_timeout=0)
    gigachat = GateGigachat()
    app = _make_responses_app(limiter=limiter, gigachat=gigachat)

    async with limiter.limit("GigaChat"):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            limited = await _post_stream_response(client, "GigaChat")

    assert limited.status_code == 429
    assert limited.headers["content-type"].startswith("application/json")
    assert limited.json()["error"]["code"] == "model_concurrency_limit"
    assert gigachat.call_count == 0


@pytest.mark.asyncio
async def test_stream_responses_holds_slot_until_completion() -> None:
    from gpt2giga.common.streaming import stream_responses_generator

    limiter = ModelConcurrencyLimiter({"GigaChat": 1}, acquire_timeout=0)
    client = StreamingGigachat()
    request = FakeStreamRequest(client, limiter)
    chat = SimpleNamespace(model="GigaChat")

    generator = stream_responses_generator(
        request,
        chat,
        response_id="resp",
        request_data={"model": "client-model"},
        effective_model="GigaChat",
    )
    lines = [await anext(generator), await anext(generator), await anext(generator)]

    assert "event: response.created" in lines[0]
    assert "event: response.in_progress" in lines[1]
    assert "event: response.output_item.added" in lines[2]
    with pytest.raises(ModelConcurrencyTimeoutError):
        async with limiter.limit("GigaChat"):
            pass

    lines.extend([line async for line in generator])

    assert any("event: response.completed" in line for line in lines)
    async with limiter.limit("GigaChat"):
        pass


@pytest.mark.asyncio
async def test_stream_responses_timeout_does_not_call_upstream() -> None:
    from gpt2giga.common.streaming import stream_responses_generator

    limiter = ModelConcurrencyLimiter({"GigaChat": 1}, acquire_timeout=0)
    client = StreamingGigachat()
    request = FakeStreamRequest(client, limiter)
    chat = SimpleNamespace(model="GigaChat")

    async with limiter.limit("GigaChat"):
        lines = [
            line
            async for line in stream_responses_generator(
                request,
                chat,
                response_id="resp",
                request_data={"model": "client-model"},
                effective_model="GigaChat",
            )
        ]

    assert client.astream_calls == 0
    assert len(lines) == 1
    assert "event: error" in lines[0]
    assert '"code": "model_concurrency_limit"' in lines[0]
