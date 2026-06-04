import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gigachat.models.chat_completions import ChatCompletionChunk
from gigachat.models.chat_completions import ChatCompletionResponse
from loguru import logger

from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import ResponseProcessor
from gpt2giga.routers.openai import router


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
        self.thread_id = None

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
        response_payload = {
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
        if self.thread_id is not None:
            response_payload["thread_id"] = self.thread_id
        return ChatCompletionResponse.model_validate(response_payload)

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
                    ]
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
        return {"contract": "chat-v1"}

    async def prepare_response(self, data, giga_client=None):
        self.v1_calls.append((data, giga_client))
        return {"contract": "responses-v1"}

    async def prepare_response_v2(self, data, giga_client=None):
        self.v2_calls.append((data, giga_client))
        return {"contract": "responses-v2"}


def make_app(gigachat_api_mode: str, responses_api_mode: str):
    app = FastAPI()
    app.include_router(router)
    app.state.gigachat_client = FakeGigachat()
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.request_transformer = FakeRequestTransformer()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(
            gigachat_api_mode=gigachat_api_mode,
            responses_api_mode=responses_api_mode,
        ),
    )
    return app


@pytest.mark.parametrize(
    ("gigachat_api_mode", "responses_api_mode", "expected_mode"),
    [
        ("v1", "inherit", "v1"),
        ("v2", "inherit", "v2"),
        ("v1", "v2", "v2"),
        ("v2", "v1", "v1"),
    ],
)
def test_responses_api_mode_matrix(
    gigachat_api_mode,
    responses_api_mode,
    expected_mode,
):
    app = make_app(gigachat_api_mode, responses_api_mode)
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={
            "model": "gpt-x",
            "input": "hi",
        },
    )

    assert response.status_code == 200
    if expected_mode == "v1":
        assert app.state.request_transformer.v1_calls
        assert not app.state.request_transformer.v2_calls
        assert app.state.gigachat_client.achat.v1_calls == [
            {"contract": "responses-v1"}
        ]
        assert app.state.gigachat_client.achat.v2_calls == []
        assert response.json()["output"][0]["content"][0]["text"] == "ok-v1"
    else:
        assert not app.state.request_transformer.v1_calls
        assert app.state.request_transformer.v2_calls
        assert app.state.gigachat_client.achat.v1_calls == []
        assert app.state.gigachat_client.achat.v2_calls == [
            {"contract": "responses-v2"}
        ]
        assert response.json()["output"][0]["content"][0]["text"] == "ok-v2"


def test_responses_v2_non_stream_returns_openai_response_object():
    app = make_app("v2", "inherit")
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={
            "model": "gpt-x",
            "input": "hi",
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["object"] == "response"
    assert body["status"] == "completed"
    assert body["output"][0]["type"] == "message"
    assert body["output"][0]["content"][0]["text"] == "ok-v2"
    assert body["usage"]["input_tokens"] == 2
    assert body["usage"]["output_tokens"] == 3


def test_responses_v2_uses_thread_id_as_response_id():
    app = make_app("v2", "inherit")
    app.state.gigachat_client.achat.thread_id = "thread_1"
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={
            "model": "gpt-x",
            "input": "hi",
        },
    )

    assert response.status_code == 200
    assert response.json()["id"] == "resp_thread_1"


def test_responses_v2_stream_uses_primary_stream():
    app = make_app("v2", "inherit")
    client = TestClient(app)

    with client.stream(
        "POST",
        "/responses",
        json={
            "model": "gpt-x",
            "input": "hi",
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: response.output_text.delta" in body
    assert "ok-stream" in body
    assert not app.state.request_transformer.v1_calls
    assert app.state.request_transformer.v2_calls
    assert app.state.gigachat_client.achat.v1_calls == []
    assert app.state.gigachat_client.achat.v2_calls == []
    assert app.state.gigachat_client.achat.stream_calls == [
        {"contract": "responses-v2"}
    ]
