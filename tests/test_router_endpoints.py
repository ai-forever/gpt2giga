from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gpt2giga.config import ProxyConfig
from gpt2giga.protocol import ResponseProcessor
from gpt2giga.router import router


class FakeGigachat:
    async def achat(self, chat):
        return SimpleNamespace(
            dict=lambda: {
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }
        )

    async def astream(self, chat):
        async def gen():
            yield SimpleNamespace(
                dict=lambda: {"choices": [{"delta": {"content": "he"}}], "usage": None}
            )
            yield SimpleNamespace(
                dict=lambda: {"choices": [{"delta": {"content": "llo"}}], "usage": None}
            )

        return gen()

    async def aembeddings(self, texts, model):
        return {"data": [{"embedding": [0.1, 0.2], "index": 0}], "model": model}


class FakeRequestTransformer:
    def send_to_gigachat(self, data):
        return SimpleNamespace(model=data.get("model", "giga"))


def make_app(monkeypatch=None):
    app = FastAPI()
    app.include_router(router)
    app.state.gigachat_client = FakeGigachat()
    app.state.response_processor = ResponseProcessor()
    app.state.request_transformer = FakeRequestTransformer()
    app.state.config = ProxyConfig()
    if monkeypatch:

        class FakeEnc:
            def decode(self, ids):
                return "TEXT"

        fake_tk = SimpleNamespace(encoding_for_model=lambda m: FakeEnc())
        monkeypatch.setattr("gpt2giga.router.tiktoken", fake_tk)
    return app


def test_responses_non_stream():
    app = make_app()
    client = TestClient(app)
    resp = client.post("/responses", json={"input": "hi", "model": "gpt-x"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "response"
    assert body["status"] == "completed"


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
