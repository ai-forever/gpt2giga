import sys
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gpt2giga.models.config import ProxyConfig
from gpt2giga.routers.openai import router as openai_router


class FakeClient:
    async def aembeddings(self, texts, model):
        return {"data": [{"embedding": [0.1], "index": 0}], "model": model}


def make_app(monkeypatch=None, pass_model=False):
    app = FastAPI()
    app.include_router(openai_router)
    app.state.gigachat_client = FakeClient()
    config = ProxyConfig()
    if pass_model:
        config.proxy_settings.pass_model = True
    app.state.config = config
    if monkeypatch:

        class FakeEnc:
            def decode(self, ids):
                return "X"

        fake_tk = SimpleNamespace(encoding_for_model=lambda m: FakeEnc())
        monkeypatch.setattr(
            sys.modules["gpt2giga.protocol.batches"], "tiktoken", fake_tk
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


def test_embeddings_uses_configured_model_by_default(monkeypatch):
    """Without pass_model the configured embeddings model is always used."""
    app = make_app(monkeypatch, pass_model=False)
    client = TestClient(app)
    resp = client.post(
        "/embeddings", json={"model": "text-embedding-ada-002", "input": "hello"}
    )
    assert resp.status_code == 200
    assert resp.json()["model"] == app.state.config.proxy_settings.embeddings


def test_embeddings_pass_model_forwards_client_model(monkeypatch):
    """With pass_model=True the model from the request body is forwarded."""
    app = make_app(monkeypatch, pass_model=True)
    client = TestClient(app)
    resp = client.post("/embeddings", json={"model": "Embeddings-2", "input": "hello"})
    assert resp.status_code == 200
    assert resp.json()["model"] == "Embeddings-2"


def test_embeddings_pass_model_falls_back_to_configured(monkeypatch):
    """With pass_model=True but no model in request, falls back to configured."""
    app = make_app(monkeypatch, pass_model=True)
    client = TestClient(app)
    resp = client.post("/embeddings", json={"input": "hello"})
    assert resp.status_code == 200
    assert resp.json()["model"] == app.state.config.proxy_settings.embeddings
