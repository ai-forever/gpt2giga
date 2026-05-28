from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger
import pytest

from gpt2giga.models.config import ProxyConfig
from gpt2giga.protocol import RequestTransformer, ResponseProcessor
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


class FakeRequestTransformer:
    async def prepare_chat_completion(self, data, giga_client=None):
        return {"model": data.get("model", "giga")}

    async def prepare_response(self, data, giga_client=None):
        return {"model": data.get("model", "giga")}


def make_app():
    app = FastAPI()
    app.include_router(router)
    app.state.gigachat_client = FakeGigachat()
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.request_transformer = FakeRequestTransformer()
    app.state.config = ProxyConfig()
    return app


def make_app_with_real_transformer():
    app = FastAPI()
    app.include_router(router)
    app.state.gigachat_client = FakeGigachat()
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.config = ProxyConfig()
    app.state.request_transformer = RequestTransformer(app.state.config, logger=logger)
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


def test_chat_completions_rejects_unsupported_param_with_openai_error():
    app = make_app_with_real_transformer()
    client = TestClient(app)
    payload = {
        "model": "gpt-x",
        "messages": [{"role": "user", "content": "hi"}],
        "logprobs": True,
    }

    resp = client.post("/chat/completions", json=payload)

    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["type"] == "invalid_request_error"
    assert resp.json()["detail"]["error"]["param"] == "logprobs"


def test_chat_completions_rejects_malformed_tools_with_openai_error():
    app = make_app_with_real_transformer()
    client = TestClient(app)
    payload = {
        "model": "gpt-x",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": "bad",
    }

    resp = client.post("/chat/completions", json=payload)

    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["type"] == "invalid_request_error"
    assert resp.json()["detail"]["error"]["param"] == "tools"


@pytest.mark.parametrize(
    ("tool_payload", "param"),
    [
        (
            {"functions": [{"parameters": {"type": "object", "properties": {}}}]},
            "functions",
        ),
        (
            {
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "parameters": {"type": "object", "properties": {}}
                        },
                    }
                ]
            },
            "tools",
        ),
    ],
)
def test_chat_completions_rejects_tool_definitions_without_name(tool_payload, param):
    app = make_app_with_real_transformer()
    client = TestClient(app)
    payload = {
        "model": "gpt-x",
        "messages": [{"role": "user", "content": "hi"}],
        **tool_payload,
    }

    resp = client.post("/chat/completions", json=payload)

    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["type"] == "invalid_request_error"
    assert resp.json()["detail"]["error"]["param"] == param


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
