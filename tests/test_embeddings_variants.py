import sys
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gpt2giga.config import ProxyConfig
from gpt2giga.routers import api_router


class FakeClient:
    async def aembeddings(self, texts, model):
        return {"data": [{"embedding": [0.1], "index": 0}], "model": model}


def make_app(monkeypatch=None):
    app = FastAPI()
    app.include_router(api_router)
    app.state.gigachat_client = FakeClient()
    app.state.config = ProxyConfig()
    if monkeypatch:

        class FakeEnc:
            def decode(self, ids):
                return "X"

        fake_tk = SimpleNamespace(encoding_for_model=lambda m: FakeEnc())
        monkeypatch.setattr(
            sys.modules["gpt2giga.routers.api_router"], "tiktoken", fake_tk
        )
    return app


def test_embeddings_input_string(monkeypatch):
    app = make_app(monkeypatch)
    client = TestClient(app)
    resp = client.post("/embeddings", json={"model": "gpt-x", "input": "hello"})
    assert resp.status_code == 200


def test_embeddings_input_list_of_list_tokens(monkeypatch):
    app = make_app(monkeypatch)
    client = TestClient(app)
    resp = client.post(
        "/embeddings", json={"model": "gpt-x", "input": [[1, 2, 3], [4]]}
    )
    assert resp.status_code == 200
