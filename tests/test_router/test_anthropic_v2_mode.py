import asyncio
import json

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gigachat.models.chat_completions import ChatCompletionChunk
from gigachat.models.chat_completions import ChatCompletionResponse
from loguru import logger

from gpt2giga.common.model_concurrency import ModelConcurrencyLimiter
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import ResponseProcessor
from gpt2giga.routers.anthropic import router


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self, *args, **kwargs):
        return self.data


class FakeAChatResource:
    def __init__(self):
        self.chat_calls = []
        self.chat_completion_calls = []
        self.stream_calls = []
        self.openai_style_stream = False
        self.source_stream = False
        self.active_create_calls = 0
        self.max_active_create_calls = 0
        self.release_create: asyncio.Event | None = None

    async def __call__(self, payload):
        self.chat_calls.append(payload)
        return MockResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok-v1"},
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

    async def create(self, payload):
        self.chat_completion_calls.append(payload)
        self.active_create_calls += 1
        self.max_active_create_calls = max(
            self.max_active_create_calls,
            self.active_create_calls,
        )
        try:
            if self.release_create is not None:
                await self.release_create.wait()
            return ChatCompletionResponse.model_validate(
                {
                    "model": "GigaChat-2-Max",
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [{"text": "ok-v2"}],
                        }
                    ],
                    "finish_reason": "stop",
                    "usage": {
                        "input_tokens": 2,
                        "output_tokens": 3,
                        "total_tokens": 5,
                    },
                }
            )
        finally:
            self.active_create_calls -= 1

    def stream(self, payload):
        self.stream_calls.append(payload)

        async def gen():
            if self.source_stream:
                yield ChatCompletionChunk.model_validate(
                    {
                        "messages": [
                            {
                                "role": "assistant",
                                "content": [
                                    {
                                        "inline_data": {
                                            "sources": {
                                                "1": {
                                                    "url": (
                                                        "https://example.test/source"
                                                    ),
                                                    "title": "Example Source",
                                                }
                                            }
                                        }
                                    }
                                ],
                            }
                        ]
                    }
                )
                yield ChatCompletionChunk.model_validate(
                    {
                        "messages": [
                            {
                                "role": "assistant",
                                "content": [{"text": "Answer. "}],
                            }
                        ]
                    }
                )
                yield ChatCompletionChunk.model_validate(
                    {
                        "messages": [
                            {
                                "role": "assistant",
                                "content": [{"text": "[sources=[1"}],
                            }
                        ]
                    }
                )
                yield ChatCompletionChunk.model_validate(
                    {
                        "messages": [
                            {
                                "role": "assistant",
                                "content": [{"text": "]]"}],
                            }
                        ],
                        "finish_reason": "stop",
                    }
                )
                return

            if self.openai_style_stream:
                for text in ("Прив", "ет", "! Чем", " могу", " помочь?"):
                    yield MockResponse(
                        {
                            "choices": [
                                {
                                    "delta": {
                                        "content": text,
                                        "role": "assistant",
                                    },
                                    "index": 0,
                                }
                            ],
                            "created": 1781307410,
                            "model": "GigaChat-3-Ultra:32.3.18.5",
                            "object": "chat.completions",
                        }
                    )
                yield MockResponse(
                    {
                        "choices": [
                            {
                                "delta": {
                                    "content": "",
                                    "role": "assistant",
                                    "functions_state_id": (
                                        "019ebe32-089b-7bee-b7a2-0d924c288064"
                                    ),
                                },
                                "index": 0,
                                "finish_reason": "stop",
                            }
                        ],
                        "created": 1781307410,
                        "model": "GigaChat-3-Ultra:32.3.18.5",
                        "object": "chat.completions",
                        "usage": {
                            "prompt_tokens": 27413,
                            "completion_tokens": 8,
                            "total_tokens": 27421,
                            "precached_prompt_tokens": 0,
                        },
                    }
                )
                return

            yield ChatCompletionChunk.model_validate(
                {
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [{"text": "ok-stream"}],
                        }
                    ],
                    "usage": {
                        "input_tokens": 2,
                        "output_tokens": 3,
                        "total_tokens": 5,
                    },
                }
            )

        return gen()


class FakeGigachat:
    def __init__(self):
        self.achat = FakeAChatResource()


class FakeRequestTransformer:
    def __init__(self):
        self.chat_calls = []
        self.chat_completion_calls = []

    async def prepare_chat(self, data, giga_client=None):
        self.chat_calls.append((data, giga_client))
        return {"contract": "anthropic-v1"}

    async def prepare_chat_completion(self, data, giga_client=None):
        self.chat_completion_calls.append((data, giga_client))
        return {"contract": "anthropic-v2"}


def make_app(
    mode: str,
    *,
    limiter: ModelConcurrencyLimiter | None = None,
):
    app = FastAPI()
    app.include_router(router)
    app.state.gigachat_client = FakeGigachat()
    if limiter is not None:
        app.state.model_concurrency_limiter = limiter
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.request_transformer = FakeRequestTransformer()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(gigachat_api_mode=mode),
    )
    app.state.logger = logger
    return app


def test_anthropic_messages_v1_mode_uses_root_achat():
    app = make_app("v1")
    client = TestClient(app)

    response = client.post(
        "/messages",
        json={
            "model": "claude-x",
            "max_tokens": 16,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["content"][0]["text"] == "ok-v1"
    assert app.state.request_transformer.chat_calls
    assert not app.state.request_transformer.chat_completion_calls
    assert app.state.gigachat_client.achat.chat_calls == [{"contract": "anthropic-v1"}]
    assert app.state.gigachat_client.achat.chat_completion_calls == []


def test_anthropic_messages_v2_mode_uses_chat_completion_create():
    app = make_app("v2")
    client = TestClient(app)

    response = client.post(
        "/messages",
        json={
            "model": "claude-x",
            "max_tokens": 16,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["type"] == "message"
    assert body["content"][0]["text"] == "ok-v2"
    assert body["usage"]["input_tokens"] == 2
    assert body["usage"]["output_tokens"] == 3
    assert not app.state.request_transformer.chat_calls
    assert app.state.request_transformer.chat_completion_calls
    assert app.state.gigachat_client.achat.chat_calls == []
    assert app.state.gigachat_client.achat.chat_completion_calls == [
        {"contract": "anthropic-v2"}
    ]


def test_anthropic_messages_v2_mode_passes_builtin_tools_to_transformer():
    app = make_app("v2")
    client = TestClient(app)

    response = client.post(
        "/messages",
        json={
            "model": "claude-x",
            "max_tokens": 16,
            "messages": [{"role": "user", "content": "search"}],
            "tools": [
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": 3,
                }
            ],
            "tool_choice": {"type": "tool", "name": "web_search"},
        },
    )

    assert response.status_code == 200
    transformed_data = app.state.request_transformer.chat_completion_calls[0][0]
    assert transformed_data["tools"] == [{"type": "web_search", "max_uses": 3}]
    assert transformed_data["tool_choice"] == {"type": "web_search"}
    assert "functions" not in transformed_data
    assert "function_call" not in transformed_data


async def _wait_for_chat_completion_transformer_calls(app, count: int) -> None:
    while len(app.state.request_transformer.chat_completion_calls) < count:
        await asyncio.sleep(0)


async def _wait_for_chat_completion_create_calls(app, count: int) -> None:
    while len(app.state.gigachat_client.achat.chat_completion_calls) < count:
        await asyncio.sleep(0)


def _anthropic_payload() -> dict:
    return {
        "model": "claude-x",
        "max_tokens": 16,
        "messages": [{"role": "user", "content": "hi"}],
    }


async def _post_anthropic_message(client: httpx.AsyncClient) -> httpx.Response:
    return await client.post("/messages", json=_anthropic_payload())


async def test_anthropic_messages_v2_mode_serializes_same_upstream_model():
    app = make_app("v2", limiter=ModelConcurrencyLimiter({"GigaChat": 1}))
    app.state.gigachat_client.achat.release_create = asyncio.Event()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        first = asyncio.create_task(_post_anthropic_message(client))
        await _wait_for_chat_completion_create_calls(app, 1)
        second = asyncio.create_task(_post_anthropic_message(client))
        await _wait_for_chat_completion_transformer_calls(app, 2)

        assert len(app.state.gigachat_client.achat.chat_completion_calls) == 1
        assert app.state.gigachat_client.achat.active_create_calls == 1

        app.state.gigachat_client.achat.release_create.set()
        first_response, second_response = await asyncio.gather(first, second)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert app.state.gigachat_client.achat.max_active_create_calls == 1


def test_anthropic_messages_v2_stream_uses_chat_completion_stream():
    app = make_app("v2")
    client = TestClient(app)

    with client.stream(
        "POST",
        "/messages",
        json={
            "model": "claude-x",
            "max_tokens": 16,
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: content_block_delta" in body
    assert "ok-stream" in body
    assert not app.state.request_transformer.chat_calls
    assert app.state.request_transformer.chat_completion_calls
    assert app.state.gigachat_client.achat.chat_calls == []
    assert app.state.gigachat_client.achat.chat_completion_calls == []
    assert app.state.gigachat_client.achat.stream_calls == [
        {"contract": "anthropic-v2"}
    ]


def test_anthropic_messages_v2_stream_renders_sources_section():
    app = make_app("v2")
    app.state.gigachat_client.achat.source_stream = True
    client = TestClient(app)

    with client.stream(
        "POST",
        "/messages",
        json={
            "model": "claude-x",
            "max_tokens": 16,
            "messages": [{"role": "user", "content": "search"}],
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "[sources=" not in body
    assert "Sources:" in body
    assert "- [Example Source](https://example.test/source)" in body


def test_anthropic_messages_v2_stream_handles_openai_style_chat_completion_chunks():
    app = make_app("v2")
    app.state.gigachat_client.achat.openai_style_stream = True
    client = TestClient(app)

    with client.stream(
        "POST",
        "/messages",
        json={
            "model": "claude-x",
            "max_tokens": 16,
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    events: list[tuple[str, dict]] = []
    pending_event: str | None = None
    for line in body.splitlines():
        if line.startswith("event: "):
            pending_event = line.removeprefix("event: ")
        elif line.startswith("data: ") and pending_event is not None:
            events.append((pending_event, json.loads(line.removeprefix("data: "))))
            pending_event = None

    event_names = [event_name for event_name, _ in events]
    assert event_names.index("content_block_start") < event_names.index(
        "content_block_delta"
    )
    text_deltas = [
        event["delta"]["text"]
        for event_name, event in events
        if event_name == "content_block_delta"
        and event["delta"]["type"] == "text_delta"
    ]
    assert "".join(text_deltas) == "Привет! Чем могу помочь?"

    message_delta = next(
        event for event_name, event in events if event_name == "message_delta"
    )
    assert message_delta["delta"]["stop_reason"] == "end_turn"
    assert message_delta["usage"]["output_tokens"] == 8
