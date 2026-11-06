"""Stable public model metadata and Gemini cursor contracts."""

from types import SimpleNamespace
import ssl

import pytest
from fastapi.testclient import TestClient
from google import genai
from google.genai import types
from sdk_client_support import make_httpx_client

from gpt2giga.app.factory import create_app
from gpt2giga.models.config import ProxyConfig
from gpt2giga.routers.gemini.models import build_gemini_model
from gpt2giga.routers.openai.models import _build_anthropic_model


def _app():
    app = create_app(ProxyConfig(gigachat={"model": "GigaChat-3-Ultra"}))

    class Client:
        async def aget_models(self):
            return SimpleNamespace(
                data=[
                    {"id": "GigaChat-3-Ultra", "type": "chat"},
                    {"id": "Embeddings", "type": "embedder"},
                ],
                object="list",
            )

    app.state.gigachat_client = Client()
    return app


@pytest.mark.parametrize(
    "prefix", ["", "/v1", "/v2", "/v1beta", "/v1/v1beta", "/v2/v1beta"]
)
def test_gemini_pagination_visits_visible_models_once(prefix):
    client = TestClient(_app())
    headers = {"x-goog-api-client": "genai-python/2.14.0"}
    first = client.get(f"{prefix}/models", params={"pageSize": 1}, headers=headers)
    assert first.status_code == 200
    assert len(first.json()["models"]) == 1
    token = first.json()["nextPageToken"]
    assert token
    second = client.get(
        f"{prefix}/models", params={"pageSize": 1, "pageToken": token}, headers=headers
    )
    assert second.status_code == 200
    assert second.json()["nextPageToken"] == ""
    assert {first.json()["models"][0]["name"], second.json()["models"][0]["name"]} == {
        "models/GigaChat-3-Ultra",
        "models/Embeddings",
    }


@pytest.mark.parametrize(
    "params",
    [{"pageToken": "bogus"}, {"pageSize": "bad"}, {"pageSize": 0}, {"pageSize": 1001}],
)
def test_invalid_gemini_cursor_is_protocol_error(params):
    response = TestClient(_app()).get("/v1beta/models", params=params)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == 400
    assert response.json()["error"]["status"] == "INVALID_ARGUMENT"


def test_google_sdk_model_pager_follows_next_page_token(monkeypatch, tmp_path):
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "unused-ca.pem"))
    monkeypatch.setenv("SSL_CERT_DIR", str(tmp_path / "unused-ca-directory"))
    app = _app()
    fake_client = app.state.gigachat_client
    monkeypatch.setattr(
        "gpt2giga.app.lifecycle.create_gigachat_client", lambda _: fake_client
    )
    client = genai.Client(
        api_key="test",
        http_options=types.HttpOptions(
            base_url="http://testserver",
            httpx_client=make_httpx_client(app),
            client_args={"verify": ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)},
            async_client_args={
                "verify": ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
                "ssl": ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
            },
        ),
    )
    try:
        models = list(client.models.list(config={"page_size": 1}))
    finally:
        client.close()
    assert [model.name for model in models] == [
        "models/Embeddings",
        "models/GigaChat-3-Ultra",
    ]


@pytest.mark.parametrize(
    ("model", "methods"),
    [
        ({"id": "future", "owned_by": "gigachat", "description": "chat embedding"}, []),
        ({"id": "GigaChat-4-Future"}, []),
        (
            {"id": "provider-text", "type": "chat"},
            ["generateContent", "streamGenerateContent", "countTokens"],
        ),
        (
            {"id": "provider-vector", "type": "embedder"},
            ["embedContent", "batchEmbedContents"],
        ),
        (
            {"id": "GigaChat-3-Ultra", "capabilities": {"streaming": False}},
            ["generateContent", "countTokens"],
        ),
        ({"id": "GigaChat-3-Ultra", "supportedGenerationMethods": []}, []),
    ],
)
def test_methods_use_explicit_catalog_facts(model, methods):
    assert build_gemini_model(model)["supportedGenerationMethods"] == methods


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({}, "1970-01-01T00:00:00+00:00"),
        ({"created_at": "bad"}, "1970-01-01T00:00:00+00:00"),
        ({"created_at": 1735689600}, "2025-01-01T00:00:00+00:00"),
        ({"release_date": "2025-01-01"}, "2025-01-01T00:00:00+00:00"),
        ({"created_at": "2025-01-01T03:00:00+03:00"}, "2025-01-01T00:00:00+00:00"),
    ],
)
def test_anthropic_model_created_at_is_release_date_or_stable_epoch(metadata, expected):
    model = {"id": "model", **metadata}
    assert _build_anthropic_model(model)["created_at"] == expected
    assert _build_anthropic_model(model)["created_at"] == expected
