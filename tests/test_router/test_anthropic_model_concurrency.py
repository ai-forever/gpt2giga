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
from gpt2giga.routers.anthropic import router


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self):
        return self.data


class FakeTokensCount:
    def __init__(self, tokens):
        self.tokens = tokens


class GateAnthropicGigachat:
    def __init__(self):
        self.active: dict[str, int] = {}
        self.max_active: dict[str, int] = {}
        self.chat_call_count = 0
        self.token_call_count = 0
        self.chat_payloads = []
        self.release = asyncio.Event()

    async def achat(self, chat):
        model = chat.get("model", "GigaChat")
        self.chat_payloads.append(chat)
        self.chat_call_count += 1
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
                            "message": {"role": "assistant", "content": "Hello!"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                }
            )
        finally:
            self.active[model] -= 1

    async def atokens_count(self, input_, model=None):
        self.token_call_count += 1
        self.active[model] = self.active.get(model, 0) + 1
        try:
            await self.release.wait()
            return [FakeTokensCount(tokens=len(text.split())) for text in input_]
        finally:
            self.active[model] -= 1


class RecordingTransformer:
    def __init__(self, upstream_model: str = "GigaChat"):
        self.upstream_model = upstream_model
        self.prepared_count = 0
        self.second_prepared = asyncio.Event()

    async def prepare_chat_completion(self, data, giga_client=None):
        self.prepared_count += 1
        if self.prepared_count == 2:
            self.second_prepared.set()
        return {"model": self.upstream_model, "messages": data.get("messages", [])}


class StreamingGigachat:
    def __init__(self):
        self.astream_calls = 0

    def astream(self, chat):
        self.astream_calls += 1

        async def gen():
            yield MockResponse(
                {
                    "choices": [{"delta": {"content": "Hel"}}],
                    "usage": None,
                }
            )
            yield MockResponse(
                {
                    "choices": [{"delta": {"content": "lo"}}],
                    "usage": {"completion_tokens": 2},
                }
            )

        return gen()


class FakeAppState:
    def __init__(self, client, limiter):
        self.gigachat_client = client
        self.model_concurrency_limiter = limiter
        self.response_processor = ResponseProcessor(logger=logger)
        self.config = ProxyConfig(
            proxy=ProxySettings(structured_output_mode="function_call")
        )
        self.logger = logger


class FakeStreamRequest:
    def __init__(self, client, limiter):
        self.app = SimpleNamespace(state=FakeAppState(client, limiter))

    async def is_disconnected(self):
        return False


def _make_app(
    *,
    limiter: ModelConcurrencyLimiter,
    gigachat: GateAnthropicGigachat,
    transformer: RecordingTransformer | None = None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.gigachat_client = gigachat
    app.state.model_concurrency_limiter = limiter
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.request_transformer = transformer or RecordingTransformer()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(structured_output_mode="function_call")
    )
    app.state.logger = logger
    return app


def _message_payload(model: str = "claude-visible") -> dict:
    return {
        "model": model,
        "max_tokens": 64,
        "messages": [{"role": "user", "content": "hello world"}],
    }


async def _post_message(client: httpx.AsyncClient, model: str = "claude-visible"):
    return await client.post("/messages", json=_message_payload(model))


async def _wait_for_chat_count(gigachat: GateAnthropicGigachat, count: int) -> None:
    while gigachat.chat_call_count < count:
        await asyncio.sleep(0)


async def _wait_for_token_count(gigachat: GateAnthropicGigachat, count: int) -> None:
    while gigachat.token_call_count < count:
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_anthropic_count_tokens_timeout_returns_429() -> None:
    limiter = ModelConcurrencyLimiter({"claude-visible": 1}, acquire_timeout=0)
    gigachat = GateAnthropicGigachat()
    app = _make_app(limiter=limiter, gigachat=gigachat)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        first = asyncio.create_task(
            client.post("/messages/count_tokens", json=_message_payload())
        )
        await _wait_for_token_count(gigachat, 1)
        limited = await client.post("/messages/count_tokens", json=_message_payload())
        gigachat.release.set()
        first_response = await first

    assert first_response.status_code == 200
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "model_concurrency_limit"
    assert limited.json()["error"]["type"] == "rate_limit_error"


@pytest.mark.asyncio
async def test_anthropic_messages_non_stream_serializes_same_upstream_model() -> None:
    limiter = ModelConcurrencyLimiter({"GigaChat": 1})
    gigachat = GateAnthropicGigachat()
    transformer = RecordingTransformer(upstream_model="GigaChat")
    app = _make_app(
        limiter=limiter,
        gigachat=gigachat,
        transformer=transformer,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        first = asyncio.create_task(_post_message(client))
        await _wait_for_chat_count(gigachat, 1)
        second = asyncio.create_task(_post_message(client))
        await asyncio.wait_for(transformer.second_prepared.wait(), timeout=1)

        assert gigachat.chat_call_count == 1

        gigachat.release.set()
        first_response, second_response = await asyncio.gather(first, second)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert gigachat.max_active["GigaChat"] == 1


@pytest.mark.asyncio
async def test_anthropic_messages_uses_effective_model_but_preserves_display_model() -> (
    None
):
    limiter = ModelConcurrencyLimiter({"claude-visible": 1}, acquire_timeout=0)
    gigachat = GateAnthropicGigachat()
    app = _make_app(
        limiter=limiter,
        gigachat=gigachat,
        transformer=RecordingTransformer(upstream_model="GigaChat"),
    )

    async with limiter.limit("claude-visible"):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = asyncio.create_task(_post_message(client))
            await _wait_for_chat_count(gigachat, 1)
            gigachat.release.set()
            result = await response

    assert result.status_code == 200
    assert result.json()["model"] == "claude-visible"
    assert gigachat.chat_payloads == [
        {
            "model": "GigaChat",
            "messages": [{"role": "user", "content": "hello world"}],
        }
    ]


@pytest.mark.asyncio
async def test_stream_anthropic_holds_slot_until_generator_closes() -> None:
    from gpt2giga.protocol.anthropic.streaming import _stream_anthropic_generator

    limiter = ModelConcurrencyLimiter({"GigaChat": 1}, acquire_timeout=0)
    client = StreamingGigachat()
    request = FakeStreamRequest(client, limiter)
    chat = {"model": "GigaChat", "messages": []}

    generator = _stream_anthropic_generator(
        request,
        "claude-visible",
        chat,
        response_id="anthropic",
        giga_client=client,
        effective_model="GigaChat",
    )
    lines = [await anext(generator), await anext(generator), await anext(generator)]

    assert "event: message_start" in lines[0]
    assert '"model": "claude-visible"' in lines[0]
    assert "event: ping" in lines[1]
    assert "event: content_block_start" in lines[2]
    with pytest.raises(ModelConcurrencyTimeoutError):
        async with limiter.limit("GigaChat"):
            pass

    await generator.aclose()

    async with limiter.limit("GigaChat"):
        pass


@pytest.mark.asyncio
async def test_stream_anthropic_timeout_does_not_call_upstream() -> None:
    from gpt2giga.protocol.anthropic.streaming import _stream_anthropic_generator

    limiter = ModelConcurrencyLimiter({"GigaChat": 1}, acquire_timeout=0)
    client = StreamingGigachat()
    request = FakeStreamRequest(client, limiter)
    chat = {"model": "GigaChat", "messages": []}

    async with limiter.limit("GigaChat"):
        lines = [
            line
            async for line in _stream_anthropic_generator(
                request,
                "claude-visible",
                chat,
                response_id="anthropic",
                giga_client=client,
                effective_model="GigaChat",
            )
        ]

    assert client.astream_calls == 0
    assert any("event: error" in line for line in lines)
    assert any('"code": "model_concurrency_limit"' in line for line in lines)
