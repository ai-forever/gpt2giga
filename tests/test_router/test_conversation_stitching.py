from copy import deepcopy

from fastapi import FastAPI
from fastapi.testclient import TestClient
from gigachat.models.chat_completions import ChatCompletionResponse
from loguru import logger

from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import ResponseProcessor
from gpt2giga.routers.anthropic import router as anthropic_router
from gpt2giga.routers.openai import router as openai_router


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self):
        return self.data


class FakeAChatResource:
    def __init__(self):
        self.v1_calls = []
        self.v2_calls = []

    async def __call__(self, payload):
        self.v1_calls.append(deepcopy(payload))
        return MockResponse(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": f"ok-{len(self.v1_calls)}",
                        },
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
        self.v2_calls.append(deepcopy(payload))
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


class FakeGigachat:
    def __init__(self):
        self.achat = FakeAChatResource()
        self.stream_calls = []

    def astream(self, payload):
        self.stream_calls.append(deepcopy(payload))

        async def gen():
            yield MockResponse(
                {
                    "choices": [
                        {
                            "delta": {"role": "assistant", "content": "stream-"},
                            "finish_reason": None,
                        }
                    ],
                    "usage": None,
                }
            )
            yield MockResponse(
                {
                    "choices": [
                        {
                            "delta": {"content": "ok"},
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

        return gen()


class FakeRequestTransformer:
    def __init__(self):
        self.chat_calls = []
        self.response_v1_calls = []
        self.response_v2_calls = []

    async def prepare_chat_completion(self, data, giga_client=None):
        self.chat_calls.append(deepcopy(data))
        return {
            "model": data.get("model", "giga"),
            "messages": deepcopy(data.get("messages", [])),
        }

    async def prepare_chat_completion_v2(self, data, giga_client=None):
        self.chat_calls.append(deepcopy(data))
        return {"contract": "chat-v2"}

    async def prepare_response(self, data, giga_client=None):
        self.response_v1_calls.append(deepcopy(data))
        return {"model": data.get("model", "giga"), "messages": []}

    async def prepare_response_v2(self, data, giga_client=None):
        self.response_v2_calls.append(deepcopy(data))
        return {"contract": "responses-v2"}


def make_openai_app(**settings):
    app = FastAPI()
    app.include_router(openai_router)
    app.state.gigachat_client = FakeGigachat()
    app.state.logger = logger
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.request_transformer = FakeRequestTransformer()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(
            conversation_stitching_enabled=True,
            **settings,
        )
    )
    return app


def make_anthropic_app(**settings):
    app = FastAPI()
    app.include_router(anthropic_router)
    app.state.gigachat_client = FakeGigachat()
    app.state.logger = logger
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.request_transformer = FakeRequestTransformer()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(
            conversation_stitching_enabled=True,
            **settings,
        )
    )
    return app


def test_chat_completions_stitches_second_turn_by_conversation_id():
    app = make_openai_app(gigachat_api_mode="v1")
    client = TestClient(app)

    first = client.post(
        "/chat/completions",
        json={
            "model": "gpt-x",
            "conversation": "conv-1",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    second = client.post(
        "/chat/completions",
        json={
            "model": "gpt-x",
            "conversation": "conv-1",
            "messages": [{"role": "user", "content": "again"}],
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert app.state.request_transformer.chat_calls[1]["messages"] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "ok-1"},
        {"role": "user", "content": "again"},
    ]


def test_chat_completions_full_history_is_not_duplicated():
    app = make_openai_app(gigachat_api_mode="v1")
    client = TestClient(app)

    client.post(
        "/chat/completions",
        json={
            "model": "gpt-x",
            "conversation": "conv-1",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    client.post(
        "/chat/completions",
        json={
            "model": "gpt-x",
            "conversation": "conv-1",
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "ok-1"},
                {"role": "user", "content": "again"},
            ],
        },
    )

    assert app.state.request_transformer.chat_calls[1]["messages"] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "ok-1"},
        {"role": "user", "content": "again"},
    ]


def test_chat_completions_namespaces_conversations_by_api_key():
    app = make_openai_app(gigachat_api_mode="v1")
    client = TestClient(app)

    client.post(
        "/chat/completions",
        headers={"authorization": "Bearer key-a"},
        json={
            "model": "gpt-x",
            "conversation": "conv-1",
            "messages": [{"role": "user", "content": "from-a"}],
        },
    )
    client.post(
        "/chat/completions",
        headers={"authorization": "Bearer key-b"},
        json={
            "model": "gpt-x",
            "conversation": "conv-1",
            "messages": [{"role": "user", "content": "from-b"}],
        },
    )

    assert app.state.request_transformer.chat_calls[1]["messages"] == [
        {"role": "user", "content": "from-b"}
    ]


def test_chat_completions_session_id_is_opt_in_conversation_key():
    default_app = make_openai_app(gigachat_api_mode="v1")
    default_client = TestClient(default_app)
    for content in ("one", "two"):
        default_client.post(
            "/chat/completions",
            headers={"x-session-id": "session-1"},
            json={
                "model": "gpt-x",
                "messages": [{"role": "user", "content": content}],
            },
        )

    enabled_app = make_openai_app(
        gigachat_api_mode="v1",
        conversation_use_session_id=True,
    )
    enabled_client = TestClient(enabled_app)
    for content in ("one", "two"):
        enabled_client.post(
            "/chat/completions",
            headers={"x-session-id": "session-1"},
            json={
                "model": "gpt-x",
                "messages": [{"role": "user", "content": content}],
            },
        )

    assert default_app.state.request_transformer.chat_calls[1]["messages"] == [
        {"role": "user", "content": "two"}
    ]
    assert enabled_app.state.request_transformer.chat_calls[1]["messages"] == [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "ok-1"},
        {"role": "user", "content": "two"},
    ]


def test_responses_v2_with_previous_response_id_skips_local_stitching():
    app = make_openai_app(gigachat_api_mode="v2", responses_api_mode="inherit")
    client = TestClient(app)

    response = client.post(
        "/responses",
        json={
            "model": "gpt-x",
            "conversation": "conv-1",
            "previous_response_id": "resp_previous",
            "input": "hello",
        },
    )

    assert response.status_code == 200
    assert app.state.request_transformer.response_v2_calls[0]["input"] == "hello"


def test_chat_completions_stream_updates_conversation_after_completion():
    app = make_openai_app(gigachat_api_mode="v1")
    client = TestClient(app)

    with client.stream(
        "POST",
        "/chat/completions",
        json={
            "model": "gpt-x",
            "conversation": "conv-1",
            "stream": True,
            "messages": [{"role": "user", "content": "hello"}],
        },
    ) as response:
        body = "".join(response.iter_text())
    client.post(
        "/chat/completions",
        json={
            "model": "gpt-x",
            "conversation": "conv-1",
            "messages": [{"role": "user", "content": "again"}],
        },
    )

    assert response.status_code == 200
    assert "data: [DONE]" in body
    assert app.state.request_transformer.chat_calls[1]["messages"] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "stream-ok"},
        {"role": "user", "content": "again"},
    ]


def test_anthropic_messages_stitches_by_metadata_conversation_id():
    app = make_anthropic_app(gigachat_api_mode="v1")
    client = TestClient(app)

    client.post(
        "/messages",
        json={
            "model": "claude",
            "metadata": {"conversation_id": "conv-1"},
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    client.post(
        "/messages",
        json={
            "model": "claude",
            "metadata": {"conversation_id": "conv-1"},
            "messages": [{"role": "user", "content": "again"}],
        },
    )

    assert app.state.request_transformer.chat_calls[1]["messages"] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "ok-1"},
        {"role": "user", "content": "again"},
    ]
