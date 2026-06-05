from fastapi import FastAPI
from fastapi.testclient import TestClient
from gigachat.models.chat_completions import ChatCompletionChunk
from gigachat.models.chat_completions import ChatCompletionResponse
from loguru import logger

from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import ResponseProcessor
from gpt2giga.routers.anthropic import router


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self):
        return self.data


class FakeAChatResource:
    def __init__(self):
        self.v1_calls = []
        self.v2_calls = []
        self.stream_calls = []

    async def __call__(self, payload):
        self.v1_calls.append(payload)
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
        self.v2_calls.append(payload)
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

    def stream(self, payload):
        self.stream_calls.append(payload)

        async def gen():
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
        self.v1_calls = []
        self.v2_calls = []

    async def prepare_chat_completion(self, data, giga_client=None):
        self.v1_calls.append((data, giga_client))
        return {"contract": "anthropic-v1"}

    async def prepare_chat_completion_v2(self, data, giga_client=None):
        self.v2_calls.append((data, giga_client))
        return {"contract": "anthropic-v2"}


def make_app(mode: str):
    app = FastAPI()
    app.include_router(router)
    app.state.gigachat_client = FakeGigachat()
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
    assert app.state.request_transformer.v1_calls
    assert not app.state.request_transformer.v2_calls
    assert app.state.gigachat_client.achat.v1_calls == [{"contract": "anthropic-v1"}]
    assert app.state.gigachat_client.achat.v2_calls == []


def test_anthropic_messages_v2_mode_uses_primary_create():
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
    assert not app.state.request_transformer.v1_calls
    assert app.state.request_transformer.v2_calls
    assert app.state.gigachat_client.achat.v1_calls == []
    assert app.state.gigachat_client.achat.v2_calls == [{"contract": "anthropic-v2"}]


def test_anthropic_messages_v2_stream_uses_primary_stream():
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
    assert not app.state.request_transformer.v1_calls
    assert app.state.request_transformer.v2_calls
    assert app.state.gigachat_client.achat.v1_calls == []
    assert app.state.gigachat_client.achat.v2_calls == []
    assert app.state.gigachat_client.achat.stream_calls == [
        {"contract": "anthropic-v2"}
    ]
