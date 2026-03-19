import sys
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger

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


class FakeGigachatFunctionCall:
    async def achat(self, chat):
        return MockResponse(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "function_call": {
                                "name": "lookup_weather",
                                "arguments": {"city": "Moscow"},
                            },
                            "functions_state_id": "state_1",
                        },
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


def make_app_with_real_transformer():
    app = FastAPI()
    app.include_router(router)
    app.state.gigachat_client = FakeGigachat()
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.request_transformer = RequestTransformer(ProxyConfig(), logger)
    app.state.request_transformer.tool_call_store = {}
    app.state.tool_call_session_store = app.state.request_transformer.tool_call_store
    app.state.config = ProxyConfig()
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


def test_responses_store_function_call_session():
    app = make_app()
    app.state.gigachat_client = FakeGigachatFunctionCall()
    client = TestClient(app)

    resp = client.post("/responses", json={"input": "weather", "model": "gpt-x"})

    assert resp.status_code == 200
    body = resp.json()
    stored = app.state.tool_call_session_store[body["id"]]
    assert stored["api_type"] == "responses"
    assert stored["call_ids"] == [body["output"][0]["call_id"]]
    assert stored["call_names"][body["output"][0]["call_id"]] == "lookup_weather"


def test_responses_continue_with_previous_response_id_and_call_id():
    app = make_app_with_real_transformer()
    app.state.tool_call_session_store["resp_prev"] = {
        "assistant_tool_call_message": {
            "tool_calls": [
                {
                    "id": "call_1",
                    "name": "lookup_weather",
                    "arguments": {"city": "Moscow"},
                }
            ]
        },
        "call_ids": ["call_1"],
        "call_names": {"call_1": "lookup_weather"},
        "completed_call_ids": [],
        "completed": False,
    }
    captured_chat = {}

    class CaptureGigachat:
        async def achat(self, chat):
            captured_chat.update(chat)
            return MockResponse(
                {
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "done"},
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

    app.state.gigachat_client = CaptureGigachat()
    client = TestClient(app)

    resp = client.post(
        "/responses",
        json={
            "model": "gpt-x",
            "previous_response_id": "resp_prev",
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": "call_1",
                    "output": {"temp": 10},
                }
            ],
        },
    )

    assert resp.status_code == 200
    assert [message["role"] for message in captured_chat["messages"]] == ["function"]
    assert captured_chat["messages"][0]["name"] == "lookup_weather"
    assert app.state.tool_call_session_store["resp_prev"]["completed_call_ids"] == [
        "call_1"
    ]


def test_chat_completions_multiple_tool_results_rebuilt_for_gigachat():
    app = make_app_with_real_transformer()
    captured_chat = {}

    class CaptureGigachat:
        async def achat(self, chat):
            captured_chat.update(chat)
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

    app.state.gigachat_client = CaptureGigachat()
    client = TestClient(app)

    resp = client.post(
        "/chat/completions",
        json={
            "model": "gpt-x",
            "messages": [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "fn1", "arguments": "{}"},
                        },
                        {
                            "id": "call_2",
                            "type": "function",
                            "function": {"name": "fn2", "arguments": "{}"},
                        },
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call_1",
                    "name": "fn1",
                    "content": {"ok": 1},
                },
                {
                    "role": "tool",
                    "tool_call_id": "call_2",
                    "name": "fn2",
                    "content": {"ok": 2},
                },
            ],
        },
    )

    assert resp.status_code == 200
    assert [message["role"] for message in captured_chat["messages"]] == [
        "assistant",
        "function",
        "assistant",
        "function",
    ]
    assert captured_chat["messages"][0]["function_call"]["name"] == "fn1"
    assert captured_chat["messages"][2]["function_call"]["name"] == "fn2"


def test_chat_completions_tool_result_without_tool_call_returns_400():
    app = make_app_with_real_transformer()
    client = TestClient(app)

    resp = client.post(
        "/chat/completions",
        json={
            "model": "gpt-x",
            "messages": [
                {
                    "role": "tool",
                    "tool_call_id": "missing_call",
                    "name": "fn1",
                    "content": {"ok": 1},
                }
            ],
        },
    )

    assert resp.status_code == 400
    assert "Tool result does not match any assistant tool call in history" in str(
        resp.json()
    )


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
