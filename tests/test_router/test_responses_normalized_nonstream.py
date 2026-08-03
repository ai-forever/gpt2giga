from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger
import pytest

from gpt2giga.common.model_concurrency import ModelConcurrencyLimiter
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import ResponseProcessor
from gpt2giga.protocols.openai import OpenAIProtocolAdapter
from gpt2giga.providers.gigachat import GigaChatProviderAdapter
from gpt2giga.routers.openai.responses import router


class _Response:
    def __init__(self, data=None):
        self.data = data

    def model_dump(self):
        return self.data or {
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
        self.stream_calls = []

    async def achat(self, payload):
        self.calls.append(payload)
        return _Response()

    def astream(self, payload):
        self.stream_calls.append(payload)

        async def generate():
            yield _Response(
                {
                    "choices": [{"delta": {"content": "nor"}, "finish_reason": None}],
                    "usage": None,
                }
            )
            yield _Response(
                {
                    "choices": [
                        {"delta": {"content": "malized"}, "finish_reason": "stop"}
                    ],
                    "usage": {
                        "prompt_tokens": 2,
                        "completion_tokens": 3,
                        "total_tokens": 5,
                    },
                }
            )

        return generate()


class _Transformer:
    def __init__(self, *, allow_native: bool = False):
        self.chat_calls = []
        self.native_responses_calls = []
        self.allow_native = allow_native

    async def prepare_chat(self, data, giga_client=None):
        self.chat_calls.append(data)
        return data

    async def prepare_response_chat(self, data, giga_client=None, **kwargs):
        self.native_responses_calls.append(data)
        if not self.allow_native:
            raise AssertionError("native Responses owner must not run")
        return {"model": data["model"], "messages": []}


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
    limiter = ModelConcurrencyLimiter({})
    app.state.model_concurrency_limiter = limiter
    app.state.openai_protocol_adapter = OpenAIProtocolAdapter()
    app.state.request_transformer = transformer
    response_processor = ResponseProcessor(logger=logger)
    app.state.response_processor = response_processor
    app.state.responses_provider_adapter = GigaChatProviderAdapter(
        config=app.state.config,
        request_transformer=transformer,
        giga_client=client,
        model_limiter=limiter,
        response_processor=response_processor,
        api_mode="v1",
        forced_model="GigaChat-2-Max",
    )
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
    assert transformer.native_responses_calls == []
    assert transformer.chat_calls[0]["messages"] == [
        {"role": "system", "content": "Be concise."},
        {"role": "user", "content": "hello"},
    ]
    assert giga_client.calls[0]["model"] == "GigaChat-2-Max"


@pytest.mark.parametrize(
    "field",
    ["conversation", "previous_response_id", "reasoning", "reasoning_effort"],
)
def test_responses_normalized_rejects_state_and_reasoning_before_provider_io(
    field: str,
) -> None:
    app, giga_client, transformer = _app()

    response = TestClient(app).post(
        "/responses",
        json={
            "input": "hello",
            "model": "bridge/codex-test",
            field: "fixture",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "unsupported_semantic",
        "message": "The selected bridge route cannot preserve this semantic.",
        "param": field,
        "type": "invalid_request_error",
    }
    assert transformer.chat_calls == []
    assert transformer.native_responses_calls == []
    assert giga_client.calls == []


def test_responses_native_path_requires_no_workaround_flag() -> None:
    app, giga_client, _transformer = _app()
    native_transformer = _Transformer(allow_native=True)
    app.state.request_transformer = native_transformer
    del app.state.responses_provider_adapter

    response = TestClient(app).post(
        "/responses",
        json={
            "input": "hello",
            "model": "bridge/codex-test",
            "reasoning": {"effort": "high"},
        },
    )

    assert response.status_code == 200
    assert len(native_transformer.native_responses_calls) == 1
    assert native_transformer.chat_calls == []
    assert len(giga_client.calls) == 1


def test_responses_defaults_to_normalized_without_startup_adapter() -> None:
    app, giga_client, transformer = _app()
    del app.state.openai_protocol_adapter

    response = TestClient(app).post(
        "/responses",
        json={"input": "hello", "model": "bridge/codex-test"},
    )

    assert response.status_code == 200
    assert transformer.native_responses_calls == []
    assert len(giga_client.calls) == 1


def test_responses_stream_uses_normalized_events_without_native_fallback() -> None:
    app, giga_client, transformer = _app()

    with TestClient(app).stream(
        "POST",
        "/responses",
        json={
            "input": "hello",
            "model": "bridge/codex-test",
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert [
        block.splitlines()[0]
        for block in body.split("\n\n")
        if block.startswith("event: ")
    ] == [
        "event: response.created",
        "event: response.output_item.added",
        "event: response.content_part.added",
        "event: response.output_text.delta",
        "event: response.output_text.delta",
        "event: response.output_text.done",
        "event: response.content_part.done",
        "event: response.output_item.done",
        "event: response.completed",
    ]
    assert '"text": "normalized"' in body
    assert '"total_tokens": 5' in body
    assert transformer.native_responses_calls == []
    assert giga_client.calls == []
    assert len(giga_client.stream_calls) == 1
