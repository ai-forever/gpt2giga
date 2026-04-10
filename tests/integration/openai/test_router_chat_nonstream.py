from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger

from gpt2giga.api.middleware.observability import ObservabilityMiddleware
from gpt2giga.core.config.settings import ProxyConfig
from gpt2giga.app.dependencies import ensure_runtime_dependencies
from gpt2giga.providers.gigachat import ResponseProcessor
from gpt2giga.api.openai import router


def _get_model(data):
    return data.model if hasattr(data, "model") else data.get("model", "giga")


def _get_messages(data):
    if hasattr(data, "messages"):
        return [message.to_openai_message() for message in data.messages]
    return data.get("messages")


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self, *args, **kwargs):
        return self.data


class FakeGigachat:
    def __init__(self):
        self.last_method = None

    async def achat(self, chat):
        self.last_method = "v1"
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

    async def achat_v2(self, chat):
        self.last_method = "v2"
        return MockResponse(
            {
                "model": "gpt-x",
                "created_at": 123,
                "messages": [
                    {
                        "message_id": "msg-1",
                        "role": "assistant",
                        "content": [{"text": "ok-v2"}],
                    }
                ],
                "finish_reason": "stop",
                "usage": {
                    "input_tokens": 1,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens": 1,
                    "total_tokens": 2,
                },
            }
        )


class FakeRequestTransformer:
    def __init__(self):
        self.last_mode = None

    async def prepare_chat_completion(self, data, giga_client=None):
        self.last_mode = "v1"
        return {"model": _get_model(data)}

    async def prepare_chat_completion_v2(self, data, giga_client=None):
        self.last_mode = "v2"
        return {"model": _get_model(data), "messages": _get_messages(data)}

    async def prepare_response(self, data, giga_client=None):
        return {"model": _get_model(data)}


def make_app(*, config=None, observability: bool = False):
    app = FastAPI()
    app.include_router(router)
    app.state.gigachat_client = FakeGigachat()
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.request_transformer = FakeRequestTransformer()
    app.state.config = config or ProxyConfig()
    if observability:
        ensure_runtime_dependencies(app.state, config=app.state.config)
        app.add_middleware(ObservabilityMiddleware)
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
    assert body["object"] == "chat.completion"


def test_chat_completions_non_stream_v2_mode():
    app = make_app(
        config=ProxyConfig.model_validate({"proxy": {"gigachat_api_mode": "v2"}})
    )
    client = TestClient(app)
    payload = {
        "model": "gpt-x",
        "messages": [{"role": "user", "content": "hi"}],
    }
    resp = client.post("/chat/completions", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "ok-v2"
    assert app.state.gigachat_client.last_method == "v2"
    assert app.state.request_transformer.last_mode == "v2"


def test_chat_completions_non_stream_records_audit_metadata():
    app = make_app(observability=True)
    client = TestClient(app)

    resp = client.post(
        "/chat/completions",
        json={
            "model": "gpt-x",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert resp.status_code == 200
    recent_requests = app.state.stores.recent_requests.recent()
    assert len(recent_requests) == 1
    event = recent_requests[0]
    assert event["endpoint"] == "/chat/completions"
    assert event["model"] == "gpt-x"
    assert event["token_usage"] == {
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "total_tokens": 2,
    }
    assert event["stream_duration_ms"] is None
    assert event["error_type"] is None
