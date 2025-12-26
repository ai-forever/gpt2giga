from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger

from gpt2giga.config import ProxyConfig
from gpt2giga.protocol import ResponseProcessor
from gpt2giga.routers.api_router import router


class FakeGigachat:
    async def achat(self, chat):
        return SimpleNamespace(
            dict=lambda: {
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


class FakeRequestTransformer:
    async def send_to_gigachat(self, data):
        return SimpleNamespace(model=data.get("model", "giga")), None


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
    assert body["object"] == "response"
