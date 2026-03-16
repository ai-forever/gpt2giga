import sys
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger

from gpt2giga.models.config import ProxyConfig
from gpt2giga.protocol import ResponseProcessor
from gpt2giga.routers.api import router


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self):
        return self.data


class FakeGigachat:
    async def achat(self, chat):
        return MockResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "function_call",
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
        async def gen():
            yield MockResponse(
                {"choices": [{"delta": {"content": "he"}}], "usage": None}
            )
            yield MockResponse(
                {"choices": [{"delta": {"content": "llo"}}], "usage": None}
            )

        return gen()

    async def aembeddings(self, texts, model):
        return {"data": [{"embedding": [0.1, 0.2], "index": 0}], "model": model}


class FakeGigachatReasoning:
    async def achat(self, chat):
        return MockResponse(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "The capital of France is Paris.",
                            "reasoning_content": "This is a straightforward geography question.",
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


class FakeRequestTransformer:
    async def prepare_chat_completion(self, data, giga_client=None):
        return {"model": data.get("model", "giga")}

    async def prepare_response(self, data, giga_client=None):
        return {"model": data.get("model", "giga")}


def make_app(monkeypatch=None):
    app = FastAPI()
    app.include_router(router)
    app.state.gigachat_client = FakeGigachat()
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.request_transformer = FakeRequestTransformer()
    app.state.config = ProxyConfig()
    if monkeypatch:

        class FakeEnc:
            def decode(self, ids):
                return "TEXT"

        fake_tk = SimpleNamespace(encoding_for_model=lambda m: FakeEnc())
        monkeypatch.setattr(
            sys.modules["gpt2giga.protocol.batches"], "tiktoken", fake_tk
        )
    return app


def test_responses_non_stream():
    app = make_app()
    client = TestClient(app)
    resp = client.post("/responses", json={"input": "hi", "model": "gpt-x"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "response"
    assert body["status"] == "completed"


def test_responses_non_stream_includes_reasoning_item():
    app = make_app()
    app.state.gigachat_client = FakeGigachatReasoning()
    client = TestClient(app)
    resp = client.post(
        "/responses",
        json={
            "input": "What is the capital of France?",
            "model": "gpt-x",
            "reasoning": {"effort": "high", "summary": "auto"},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["reasoning"] == {"effort": "high", "summary": "auto"}
    assert body["output"][0]["type"] == "reasoning"
    assert body["output"][0]["summary"][0]["text"] == (
        "This is a straightforward geography question."
    )
    assert body["output"][1]["content"][0]["text"] == "The capital of France is Paris."


def test_embeddings_with_token_ids(monkeypatch):
    app = make_app(monkeypatch)
    client = TestClient(app)
    resp = client.post(
        "/embeddings",
        json={"model": "gpt-x", "input": [1, 2, 3]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert (
        "data" in body and body["model"] == app.state.config.proxy_settings.embeddings
    )
