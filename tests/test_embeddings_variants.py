import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gpt2giga.models.config import ProxyConfig
from gpt2giga.protocol.embeddings import transform_embedding_body
from gpt2giga.routers.openai import router as openai_router


class FakeClient:
    def __init__(self):
        self.embedding_calls = []

    async def aembeddings(self, texts, model):
        self.embedding_calls.append({"texts": texts, "model": model})
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
            sys.modules["gpt2giga.protocol.embeddings"], "tiktoken", fake_tk
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
    app.state.config.proxy_settings.pass_model = False
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


def test_embeddings_endpoint_currently_does_not_pass_extra_body_to_aembeddings():
    app = make_app(pass_model=True)
    client = TestClient(app)
    resp = client.post(
        "/embeddings",
        json={
            "model": "Embeddings-2",
            "input": "hello",
            "extra_body": {"custom_flag": "on"},
        },
    )

    assert resp.status_code == 200
    assert app.state.gigachat_client.embedding_calls == [
        {"texts": ["hello"], "model": "Embeddings-2"}
    ]


@pytest.mark.asyncio
async def test_transform_embedding_body_merges_extra_body():
    transformed = await transform_embedding_body(
        {"input": "hello", "extra_body": {"custom_flag": "on"}},
        "EmbeddingsGigaR",
    )

    assert transformed == {
        "input": ["hello"],
        "model": "EmbeddingsGigaR",
        "custom_flag": "on",
    }


def test_embeddings_accepts_matching_dimensions_for_configured_model():
    app = make_app(pass_model=False)
    client = TestClient(app)
    app.state.config.proxy_settings.pass_model = False
    resp = client.post("/embeddings", json={"input": "hello", "dimensions": 2560})

    assert resp.status_code == 200
    assert resp.json()["model"] == "EmbeddingsGigaR"


@pytest.mark.parametrize(
    ("model", "dimensions"),
    [
        ("Embeddings", 1024),
        ("Embeddings-2", 1024),
        ("GigaEmbeddings-3B-2025-09", 2048),
        ("EmbeddingsGigaR", 2560),
    ],
)
def test_embeddings_accepts_matching_dimensions_for_passed_model(model, dimensions):
    app = make_app(pass_model=True)
    client = TestClient(app)
    resp = client.post(
        "/embeddings",
        json={"model": model, "input": "hello", "dimensions": dimensions},
    )

    assert resp.status_code == 200
    assert resp.json()["model"] == model


@pytest.mark.parametrize(
    ("body", "param"),
    [
        ({}, "input"),
        ({"input": ""}, "input"),
        ({"input": None}, "input"),
        ({"input": {"text": "hello"}}, "input"),
        ({"input": ["hello", [1, 2, 3]]}, "input"),
        ({"input": [1, "2"]}, "input"),
        ({"input": [[1], ["2"]]}, "input"),
        ({"input": "hello", "encoding_format": "json"}, "encoding_format"),
        ({"input": "hello", "dimensions": 128}, "dimensions"),
        ({"input": "hello", "dimensions": 0}, "dimensions"),
        ({"input": "hello", "dimensions": "1024"}, "dimensions"),
        (
            {"input": "hello", "model": "UnknownEmbeddings", "dimensions": 1024},
            "dimensions",
        ),
    ],
)
def test_embeddings_rejects_invalid_openai_requests(body, param):
    app = make_app()
    client = TestClient(app)
    resp = client.post("/embeddings", json=body)

    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["type"] == "invalid_request_error"
    assert resp.json()["detail"]["error"]["param"] == param


def test_embeddings_rejects_token_ids_without_decodable_model():
    app = make_app()
    client = TestClient(app)
    resp = client.post("/embeddings", json={"input": [1, 2, 3]})

    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["type"] == "invalid_request_error"
    assert resp.json()["detail"]["error"]["param"] == "model"
