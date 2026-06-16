import secrets
from unittest.mock import patch

import pytest
from types import SimpleNamespace

from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from gpt2giga.auth import verify_api_key
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.routers.openai import router as openai_router


class FakeModel(BaseModel):
    id_: str = Field(alias="id")
    object_: str = Field(default="model", alias="object")
    owned_by: str = "gigachat"


class FakeModels(BaseModel):
    data: list[FakeModel]
    object_: str = "list"


class FakeClient:
    async def aget_models(self):
        return FakeModels(data=[FakeModel(id="GigaChat", object="model")])

    async def aget_model(self, model: str):
        return FakeModel(id=model, object="model")


def make_request(headers: dict, config: ProxyConfig, query_params: dict | None = None):
    app = SimpleNamespace(state=SimpleNamespace(config=config))
    req = SimpleNamespace(headers=headers, query_params=query_params or {}, app=app)
    return req


def test_verify_api_key_success_bearer():
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = "secret"
    req = make_request({"authorization": "Bearer secret"}, cfg)
    assert verify_api_key(req) == "secret"


def test_verify_api_key_success_x_api_key():
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = "secret"
    req = make_request({"x-api-key": "secret"}, cfg)
    assert verify_api_key(req) == "secret"


def test_verify_api_key_success_x_goog_api_key():
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = "secret"
    req = make_request({"x-goog-api-key": "secret"}, cfg)
    assert verify_api_key(req) == "secret"


@pytest.mark.parametrize("query_name", ["x-api-key", "key"])
def test_verify_api_key_success_query_key(query_name):
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = "secret"
    req = make_request({}, cfg, query_params={query_name: "secret"})
    assert verify_api_key(req) == "secret"


def test_verify_api_key_missing():
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = "secret"
    req = make_request({}, cfg)
    with pytest.raises(HTTPException) as ex:
        verify_api_key(req)
    assert ex.value.status_code == 401


@pytest.mark.parametrize(
    ("headers", "query_params"),
    [
        ({"x-goog-api-key": "secret"}, {}),
        ({"x-api-key": "secret"}, {}),
        ({"authorization": "Bearer secret"}, {}),
        ({}, {"key": "secret"}),
        ({}, {"x-api-key": "secret"}),
    ],
)
def test_gemini_models_auth_accepts_supported_api_key_locations(
    headers,
    query_params,
):
    app = FastAPI()
    app.include_router(
        openai_router,
        prefix="/v1",
        dependencies=[Depends(verify_api_key)],
    )
    app.state.gigachat_client = FakeClient()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(enable_api_key_auth=True, api_key="secret")
    )

    response = TestClient(app).get(
        "/v1/models",
        headers=headers,
        params=query_params,
    )

    assert response.status_code == 200
    if query_params.get("key") or "x-goog-api-key" in headers:
        assert response.json()["models"][0]["name"] == "models/GigaChat"
    else:
        assert response.json()["data"][0]["id"] == "GigaChat"


def test_gemini_models_auth_rejects_wrong_query_key():
    app = FastAPI()
    app.include_router(
        openai_router,
        prefix="/v1",
        dependencies=[Depends(verify_api_key)],
    )
    app.state.gigachat_client = FakeClient()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(enable_api_key_auth=True, api_key="secret")
    )

    response = TestClient(app).get("/v1/models", params={"key": "wrong"})

    assert response.status_code == 401


def test_gemini_models_auth_disabled_allows_missing_key():
    app = FastAPI()
    app.include_router(openai_router, prefix="/v1")
    app.state.gigachat_client = FakeClient()
    app.state.config = ProxyConfig(
        proxy=ProxySettings(enable_api_key_auth=False, api_key=None)
    )

    response = TestClient(app).get("/v1/models")

    assert response.status_code == 200
    assert response.json()["data"][0]["id"] == "GigaChat"


def test_verify_api_key_not_configured():
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = None
    req = make_request({"authorization": "Bearer any"}, cfg)
    with pytest.raises(HTTPException) as ex:
        verify_api_key(req)
    assert ex.value.status_code == 500


def test_verify_api_key_invalid():
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = "secret"
    req = make_request({"authorization": "Bearer wrong"}, cfg)
    with pytest.raises(HTTPException) as ex:
        verify_api_key(req)
    assert ex.value.status_code == 401


def test_verify_api_key_uses_constant_time_comparison():
    """Verify that API key comparison uses secrets.compare_digest (constant-time)."""
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = "secret"
    req = make_request({"authorization": "Bearer secret"}, cfg)
    with patch(
        "gpt2giga.auth.secrets.compare_digest", wraps=secrets.compare_digest
    ) as mock_cmp:
        result = verify_api_key(req)
        mock_cmp.assert_called_once_with("secret", "secret")
    assert result == "secret"


def test_verify_api_key_constant_time_rejects_wrong_key():
    """Verify that constant-time comparison correctly rejects invalid keys."""
    cfg = ProxyConfig()
    cfg.proxy_settings.api_key = "correct-key"
    req = make_request({"authorization": "Bearer wrong-key"}, cfg)
    with patch(
        "gpt2giga.auth.secrets.compare_digest", wraps=secrets.compare_digest
    ) as mock_cmp:
        with pytest.raises(HTTPException) as ex:
            verify_api_key(req)
        mock_cmp.assert_called_once_with("wrong-key", "correct-key")
    assert ex.value.status_code == 401
