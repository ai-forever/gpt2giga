import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger

from gpt2giga.models.config import ProxyConfig
from gpt2giga.protocol import ResponseProcessor
from gpt2giga.routers.openai import router


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
                {"choices": [{"delta": {"content": "ok"}}], "usage": None}
            )

        return gen()


class FakeRequestTransformer:
    async def prepare_chat_completion(self, data, giga_client=None):
        return {"model": data.get("model", "giga")}

    async def prepare_response(self, data, giga_client=None):
        return {"model": data.get("model", "giga")}


class FakeRequestTransformerWithoutModel:
    async def prepare_chat_completion(self, data, giga_client=None):
        return {}

    async def prepare_response(self, data, giga_client=None):
        return {}


def make_app():
    app = FastAPI()
    app.include_router(router)
    app.state.gigachat_client = FakeGigachat()
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.request_transformer = FakeRequestTransformer()
    app.state.config = ProxyConfig()
    return app


def test_chat_completions_non_stream_basic():
    app = make_app()
    client = TestClient(app)
    payload = {
        "model": "gpt-x",
        "messages": [{"role": "user", "content": "hi"}],
    }
    resp = client.post("/chat/completions", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "chat.completion"


def test_chat_completions_reports_configured_model_when_model_not_passed():
    app = make_app()
    app.state.config = ProxyConfig(gigachat={"model": "GigaChat-2-Pro"})
    app.state.request_transformer = FakeRequestTransformerWithoutModel()
    client = TestClient(app)
    payload = {
        "model": "GigaChat-2-Max",
        "messages": [{"role": "user", "content": "hi"}],
    }
    resp = client.post("/chat/completions", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["model"] == "GigaChat-2-Pro"


def test_chat_completions_stream_reports_configured_model_when_model_not_passed():
    app = make_app()
    app.state.config = ProxyConfig(gigachat={"model": "GigaChat-2-Pro"})
    app.state.request_transformer = FakeRequestTransformerWithoutModel()
    client = TestClient(app)
    payload = {
        "model": "GigaChat-2-Max",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    }
    with client.stream("POST", "/chat/completions", json=payload) as resp:
        assert resp.status_code == 200
        events = list(resp.iter_lines())

    first_event = next(line for line in events if line.startswith("data: {"))
    body = json.loads(first_event.removeprefix("data: "))
    assert body["model"] == "GigaChat-2-Pro"


def test_chat_completions_non_stream_response_api():
    app = make_app()
    client = TestClient(app)
    payload = {
        "model": "gpt-x",
        "input": "hi",
    }
    resp = client.post("/chat/completions", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "chat.completion"
