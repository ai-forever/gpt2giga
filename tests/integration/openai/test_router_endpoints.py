import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger

from gpt2giga.core.config.settings import ProxyConfig
from gpt2giga.providers.gigachat import ResponseProcessor
from gpt2giga.api.openai import router


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self, *args, **kwargs):
        return self.data


class FakeGigachat:
    def __init__(self):
        self.last_responses_method = None

    async def achat(self, chat):
        self.last_responses_method = "v1"
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

    async def achat_v2(self, chat):
        self.last_responses_method = "v2"
        storage = chat.get("storage")
        thread_id = None
        if isinstance(storage, dict):
            thread_id = storage.get("thread_id")

        if thread_id == "thread-1":
            text = "continued"
        else:
            thread_id = "thread-1"
            text = "ok"

        return MockResponse(
            {
                "model": "gpt-x",
                "thread_id": thread_id,
                "created_at": 123,
                "messages": [
                    {
                        "message_id": "msg-1",
                        "role": "assistant",
                        "content": [{"text": text}],
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

    def astream(self, chat):
        async def gen():
            self.last_responses_method = "v1"
            yield MockResponse(
                {
                    "model": "gpt-x",
                    "choices": [{"delta": {"role": "assistant", "content": "he"}}],
                    "usage": None,
                }
            )
            yield MockResponse(
                {
                    "model": "gpt-x",
                    "choices": [
                        {
                            "delta": {"role": "assistant", "content": "llo"},
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

    def astream_v2(self, chat):
        async def gen():
            self.last_responses_method = "v2"
            yield MockResponse(
                {
                    "model": "gpt-x",
                    "created_at": 123,
                    "thread_id": "thread-1",
                    "messages": [
                        {
                            "message_id": "msg-1",
                            "role": "assistant",
                            "content": [{"text": "he"}],
                        }
                    ],
                }
            )
            yield MockResponse(
                {
                    "model": "gpt-x",
                    "created_at": 123,
                    "thread_id": "thread-1",
                    "messages": [
                        {
                            "message_id": "msg-1",
                            "role": "assistant",
                            "content": [{"text": "llo"}],
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

        return gen()

    async def aembeddings(self, texts, model):
        return {"data": [{"embedding": [0.1, 0.2], "index": 0}], "model": model}


class FakeRequestTransformer:
    def __init__(self):
        self.last_mode = None

    async def prepare_chat_completion(self, data, giga_client=None):
        return {"model": data.get("model", "giga")}

    async def prepare_response(self, data, giga_client=None):
        self.last_mode = "v1"
        return {"model": data.get("model", "giga")}

    async def prepare_response_v2(
        self,
        data,
        giga_client=None,
        response_store=None,
    ):
        self.last_mode = "v2"
        thread_id = None
        conversation = data.get("conversation")
        if isinstance(conversation, dict):
            thread_id = conversation.get("id")
        elif data.get("previous_response_id") and response_store:
            metadata = response_store.get(data["previous_response_id"], {})
            thread_id = metadata.get("thread_id")

        return {
            "model": data.get("model", "giga"),
            "messages": [
                {"role": "user", "content": [{"text": data.get("input", "")}]}
            ],
            "storage": {"thread_id": thread_id} if thread_id else True,
        }


def make_app(monkeypatch=None, *, config=None):
    app = FastAPI()
    app.include_router(router)
    app.state.gigachat_client = FakeGigachat()
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.request_transformer = FakeRequestTransformer()
    app.state.config = config or ProxyConfig()
    if monkeypatch:

        class FakeEnc:
            def decode(self, ids):
                return "TEXT"

        fake_tk = type(
            "FakeTokenizer", (), {"encoding_for_model": lambda self, m: FakeEnc()}
        )()
        monkeypatch.setattr(
            sys.modules["gpt2giga.providers.gigachat.embeddings_mapper"],
            "tiktoken",
            fake_tk,
        )
    return app


def test_responses_non_stream():
    app = make_app(
        config=ProxyConfig.model_validate({"proxy": {"gigachat_api_mode": "v2"}})
    )
    client = TestClient(app)
    resp = client.post("/responses", json={"input": "hi", "model": "gpt-x"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "response"
    assert body["status"] == "completed"
    assert body["conversation"] == {"id": "thread-1"}
    assert "store" not in body


def test_responses_non_stream_v1_mode_uses_legacy_backend_path():
    app = make_app(
        config=ProxyConfig.model_validate({"proxy": {"gigachat_api_mode": "v1"}})
    )
    client = TestClient(app)

    resp = client.post("/responses", json={"input": "hi", "model": "gpt-x"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["output"][0]["content"][0]["text"] == "ok"
    assert body.get("conversation") is None
    assert app.state.gigachat_client.last_responses_method == "v1"
    assert app.state.request_transformer.last_mode == "v1"


def test_responses_non_stream_preserves_reasoning_config():
    app = make_app(
        config=ProxyConfig.model_validate({"proxy": {"gigachat_api_mode": "v2"}})
    )
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
    assert body["output"][0]["type"] == "message"
    assert body["output"][0]["content"][0]["text"] == "ok"


def test_responses_non_stream_previous_response_id_reuses_thread():
    app = make_app(
        config=ProxyConfig.model_validate({"proxy": {"gigachat_api_mode": "v2"}})
    )
    client = TestClient(app)

    first = client.post("/responses", json={"input": "hi", "model": "gpt-x"})
    assert first.status_code == 200
    first_body = first.json()

    second = client.post(
        "/responses",
        json={
            "input": "continue",
            "model": "gpt-x",
            "previous_response_id": first_body["id"],
        },
    )
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["conversation"] == first_body["conversation"]
    assert second_body["output"][0]["content"][0]["text"] == "continued"


def test_responses_stream_returns_sse_events():
    app = make_app(
        config=ProxyConfig.model_validate({"proxy": {"gigachat_api_mode": "v2"}})
    )
    client = TestClient(app)

    with client.stream(
        "POST",
        "/responses",
        json={"input": "hi", "model": "gpt-x", "stream": True},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = "".join(resp.iter_text())

    assert "event: response.created" in body
    assert "event: response.in_progress" in body
    assert "event: response.output_text.delta" in body
    assert "event: response.completed" in body


def test_responses_stream_v1_mode_returns_sse_events():
    app = make_app(
        config=ProxyConfig.model_validate({"proxy": {"gigachat_api_mode": "v1"}})
    )
    client = TestClient(app)

    with client.stream(
        "POST",
        "/responses",
        json={"input": "hi", "model": "gpt-x", "stream": True},
    ) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())

    assert "event: response.created" in body
    assert "event: response.output_text.delta" in body
    assert "event: response.completed" in body
    assert app.state.gigachat_client.last_responses_method == "v1"
    assert app.state.request_transformer.last_mode == "v1"


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
