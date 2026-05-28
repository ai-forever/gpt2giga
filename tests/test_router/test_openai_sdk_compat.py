from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger
from openai import OpenAI

from gpt2giga.middlewares.rquid_context import RquidMiddleware
from gpt2giga.models.config import ProxyConfig
from gpt2giga.protocol import RequestTransformer, ResponseProcessor
from gpt2giga.routers.openai import router as openai_router


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self):
        return self.data


class FakeGigachat:
    def __init__(self):
        self.chat_payloads = []
        self.embedding_calls = []

    async def achat(self, chat):
        self.chat_payloads.append(chat)
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

    def astream(self, chat):
        self.chat_payloads.append(chat)

        async def gen():
            yield MockResponse(
                {
                    "choices": [
                        {
                            "delta": {"content": "ok"},
                            "finish_reason": None,
                        }
                    ],
                    "usage": None,
                }
            )

        return gen()

    async def aembeddings(self, texts, model):
        self.embedding_calls.append({"texts": texts, "model": model})
        return {
            "data": [
                {
                    "embedding": [0.0, 1.0],
                    "index": 0,
                    "usage": {"prompt_tokens": 2},
                }
            ],
            "model": model,
        }


def _make_app():
    app = FastAPI()
    app.add_middleware(RquidMiddleware)
    app.include_router(openai_router)
    config = ProxyConfig()
    app.state.config = config
    app.state.gigachat_client = FakeGigachat()
    app.state.request_transformer = RequestTransformer(config, logger=logger)
    app.state.response_processor = ResponseProcessor(logger=logger)
    return app


def _make_openai_client(app):
    test_client = TestClient(app)
    return OpenAI(
        api_key="test",
        base_url=str(test_client.base_url),
        http_client=test_client,
    )


def test_openai_sdk_chat_completions_create():
    app = _make_app()
    client = _make_openai_client(app)

    response = client.chat.completions.create(
        model="GigaChat",
        messages=[{"role": "user", "content": "hello"}],
    )

    assert response.choices[0].message.content == "ok"
    assert app.state.gigachat_client.chat_payloads[-1]["messages"][0]["content"] == (
        "hello"
    )


def test_openai_sdk_chat_completions_streaming_create():
    app = _make_app()
    client = _make_openai_client(app)

    stream = client.chat.completions.create(
        model="GigaChat",
        messages=[{"role": "user", "content": "hello"}],
        stream=True,
    )

    assert "".join(chunk.choices[0].delta.content or "" for chunk in stream) == "ok"


def test_openai_sdk_responses_create():
    app = _make_app()
    client = _make_openai_client(app)

    response = client.responses.create(model="GigaChat", input="hello")

    assert response.output_text == "ok"
    assert app.state.gigachat_client.chat_payloads[-1]["messages"][0]["content"] == (
        "hello"
    )


def test_openai_sdk_embeddings_create():
    app = _make_app()
    client = _make_openai_client(app)

    response = client.embeddings.create(model="EmbeddingsGigaR", input="hello")

    assert response.data[0].embedding == [0.0, 1.0]
    assert app.state.gigachat_client.embedding_calls == [
        {"texts": ["hello"], "model": "EmbeddingsGigaR"}
    ]


def test_openai_sdk_raw_response_exposes_request_id_header():
    app = _make_app()
    client = _make_openai_client(app)

    raw_response = client.chat.completions.with_raw_response.create(
        model="GigaChat",
        messages=[{"role": "user", "content": "hello"}],
    )

    assert raw_response.headers.get("x-request-id")
    assert raw_response.parse().choices[0].message.content == "ok"


def test_openai_sdk_extra_body_supported_key_reaches_additional_fields():
    app = _make_app()
    client = _make_openai_client(app)

    client.chat.completions.create(
        model="GigaChat",
        messages=[{"role": "user", "content": "hello"}],
        extra_body={"profanity_check": False},
    )

    assert app.state.gigachat_client.chat_payloads[-1]["additional_fields"] == {
        "profanity_check": False
    }


def test_openai_sdk_custom_extra_body_reaches_additional_fields():
    app = _make_app()
    client = _make_openai_client(app)

    client.chat.completions.create(
        model="GigaChat",
        messages=[{"role": "user", "content": "hello"}],
        extra_body={"custom_flag": "on"},
    )

    assert app.state.gigachat_client.chat_payloads[-1]["additional_fields"] == {
        "custom_flag": "on"
    }
