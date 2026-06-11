import json

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from gigachat.models.chat_completions import ChatCompletionChunk
from gigachat.models.chat_completions import ChatCompletionResponse
from loguru import logger

from gpt2giga.common.api_mode import force_gigachat_api_mode
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
        self.chat_calls = []
        self.chat_completion_calls = []
        self.stream_calls = []

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
                    ]
                }
            )
            yield ChatCompletionChunk.model_validate(
                {
                    "messages": [
                        {
                            "role": "assistant",
                            "tools_state_id": "new-state",
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
        return {"contract": "v1"}

    async def prepare_chat_completion(self, data, giga_client=None):
        self.chat_completion_calls.append((data, giga_client))
        return {"contract": "v2"}

    async def prepare_response_chat(self, data, giga_client=None):
        return {"contract": "responses-v1"}


def make_app(mode: str):
    app = FastAPI()
    app.include_router(router)
    configure_app_state(app, mode)
    return app


def make_versioned_app(mode: str):
    app = FastAPI()
    app.include_router(router)
    app.include_router(
        router,
        prefix="/v1",
        dependencies=[Depends(force_gigachat_api_mode("v1"))],
    )
    app.include_router(
        router,
        prefix="/v2",
        dependencies=[Depends(force_gigachat_api_mode("v2"))],
    )
    configure_app_state(app, mode)
    return app


def configure_app_state(app: FastAPI, mode: str):
    app.state.gigachat_client = FakeGigachat()
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.request_transformer = FakeRequestTransformer()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(gigachat_api_mode=mode),
    )


def test_chat_completions_v1_mode_uses_root_achat():
    app = make_app("v1")
    client = TestClient(app)

    response = client.post(
        "/chat/completions",
        json={
            "model": "gpt-x",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "ok-v1"
    assert app.state.request_transformer.chat_calls
    assert not app.state.request_transformer.chat_completion_calls
    assert app.state.gigachat_client.achat.chat_calls == [{"contract": "v1"}]
    assert app.state.gigachat_client.achat.chat_completion_calls == []


def test_chat_completions_v2_mode_uses_chat_completion_create():
    app = make_app("v2")
    client = TestClient(app)

    response = client.post(
        "/chat/completions",
        json={
            "model": "gpt-x",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "ok-v2"
    assert body["usage"]["prompt_tokens"] == 2
    assert body["usage"]["completion_tokens"] == 3
    assert not app.state.request_transformer.chat_calls
    assert app.state.request_transformer.chat_completion_calls
    assert app.state.gigachat_client.achat.chat_calls == []
    assert app.state.gigachat_client.achat.chat_completion_calls == [{"contract": "v2"}]


def test_chat_completions_v1_prefix_forces_v1_when_default_is_v2():
    app = make_versioned_app("v2")
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-x",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "ok-v1"
    assert app.state.request_transformer.chat_calls
    assert not app.state.request_transformer.chat_completion_calls
    assert app.state.gigachat_client.achat.chat_calls == [{"contract": "v1"}]
    assert app.state.gigachat_client.achat.chat_completion_calls == []


def test_chat_completions_v2_prefix_forces_v2_when_default_is_v1():
    app = make_versioned_app("v1")
    client = TestClient(app)

    response = client.post(
        "/v2/chat/completions",
        json={
            "model": "gpt-x",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "ok-v2"
    assert not app.state.request_transformer.chat_calls
    assert app.state.request_transformer.chat_completion_calls
    assert app.state.gigachat_client.achat.chat_calls == []
    assert app.state.gigachat_client.achat.chat_completion_calls == [{"contract": "v2"}]


def test_chat_completions_v2_stream_uses_chat_completion_stream():
    app = make_app("v2")
    client = TestClient(app)

    with client.stream(
        "POST",
        "/chat/completions",
        json={
            "model": "gpt-x",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "ok-stream" in body
    assert "data: [DONE]" in body
    assert not app.state.request_transformer.chat_calls
    assert app.state.request_transformer.chat_completion_calls
    assert app.state.gigachat_client.achat.chat_calls == []
    assert app.state.gigachat_client.achat.chat_completion_calls == []
    assert app.state.gigachat_client.achat.stream_calls == [{"contract": "v2"}]


def test_chat_completions_v2_stream_preserves_called_tools_from_request():
    app = make_app("v2")
    client = TestClient(app)

    with client.stream(
        "POST",
        "/chat/completions",
        json={
            "model": "gpt-x",
            "messages": [
                {
                    "role": "assistant",
                    "tools_state_id": "state-1",
                    "content": [
                        {
                            "function_call": {
                                "name": "run_shell_command",
                                "arguments": {"command": "make install"},
                            }
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tools_state_id": "state-1",
                    "content": [
                        {
                            "function_result": {
                                "name": "run_shell_command",
                                "result": {"result": "ok"},
                            }
                        }
                    ],
                },
            ],
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    chunks = [
        json.loads(line.removeprefix("data: "))
        for line in body.splitlines()
        if line.startswith("data: {")
    ]
    metadata = chunks[-1]["metadata"]

    assert response.status_code == 200
    assert metadata["gigachat_tool_state_id"] == "new-state"
    assert json.loads(metadata["gigachat_called_tools"]) == [
        {
            "index": 0,
            "message_index": 0,
            "name": "run_shell_command",
            "arguments": {"command": "make install"},
            "content_index": 0,
            "role": "assistant",
            "tools_state_id": "state-1",
        }
    ]
