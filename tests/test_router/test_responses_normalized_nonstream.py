from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger

from gpt2giga.common.model_concurrency import ModelConcurrencyLimiter
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import ResponseProcessor
from gpt2giga.protocols.openai import OpenAIProtocolAdapter
from gpt2giga.routers.openai.responses import router


class _Response:
    def model_dump(self):
        return {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "normalized"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 2,
                "completion_tokens": 3,
                "total_tokens": 5,
            },
        }


class _GigaChat:
    def __init__(self):
        self.calls = []

    async def achat(self, payload):
        self.calls.append(payload)
        return _Response()


class _Transformer:
    def __init__(self):
        self.chat_calls = []
        self.legacy_responses_calls = []

    async def prepare_chat(self, data, giga_client=None):
        self.chat_calls.append(data)
        return data

    async def prepare_response_chat(self, data, giga_client=None, **kwargs):
        self.legacy_responses_calls.append(data)
        raise AssertionError("legacy Responses owner must not run")


def _app() -> tuple[FastAPI, _GigaChat, _Transformer]:
    app = FastAPI()
    app.include_router(router)
    client = _GigaChat()
    transformer = _Transformer()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(gigachat_api_mode="v1"),
        gigachat={"model": "GigaChat-2-Max"},
    )
    app.state.gigachat_client = client
    app.state.logger = logger
    app.state.model_concurrency_limiter = ModelConcurrencyLimiter({})
    app.state.openai_protocol_adapter = OpenAIProtocolAdapter()
    app.state.request_transformer = transformer
    app.state.response_processor = ResponseProcessor(logger=logger)
    return app, client, transformer


def test_responses_nonstream_uses_normalized_protocol_and_provider_owners() -> None:
    app, giga_client, transformer = _app()

    response = TestClient(app).post(
        "/responses",
        json={
            "input": "hello",
            "instructions": "Be concise.",
            "model": "bridge/codex-test",
        },
    )

    assert response.status_code == 200
    assert response.json()["model"] == "bridge/codex-test"
    assert response.json()["output"][0]["content"][0]["text"] == "normalized"
    assert response.json()["usage"] == {
        "input_tokens": 2,
        "output_tokens": 3,
        "total_tokens": 5,
    }
    assert transformer.legacy_responses_calls == []
    assert transformer.chat_calls[0]["messages"] == [
        {"role": "system", "content": "Be concise."},
        {"role": "user", "content": "hello"},
    ]
    assert giga_client.calls[0]["model"] == "GigaChat-2-Max"


def test_responses_normalized_rejects_unknown_field_before_provider_io() -> None:
    app, giga_client, transformer = _app()

    response = TestClient(app).post(
        "/responses",
        json={
            "input": "hello",
            "model": "bridge/codex-test",
            "provider": "untrusted",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "unsupported_semantic",
        "message": "The selected bridge route cannot preserve this semantic.",
        "param": "provider",
        "type": "invalid_request_error",
    }
    assert transformer.chat_calls == []
    assert transformer.legacy_responses_calls == []
    assert giga_client.calls == []
