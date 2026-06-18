from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.providers.fusion.model_discovery import FUSION_MODEL_CREATED
from gpt2giga.routers.gemini.models import router as gemini_models_router
from gpt2giga.routers.litellm.models import router as litellm_models_router
from gpt2giga.routers.openai import router as openai_router


class FakeModel(BaseModel):
    id_: str = Field(alias="id")
    object_: str = Field(default="model", alias="object")
    owned_by: str = "gigachat"


class FakeModels(BaseModel):
    data: list[FakeModel]
    object_: str = "list"


class FakeClient:
    def __init__(self):
        self.model_calls: list[str] = []

    async def aget_models(self):
        return FakeModels(data=[FakeModel(id="GigaChat", object="model")])

    async def aget_model(self, model: str):
        self.model_calls.append(model)
        return FakeModel(id=model, object="model")


def _fusion_config() -> ProxyConfig:
    return ProxyConfig(
        proxy=ProxySettings(
            fusion_enabled=True,
            fusion_aliases=["gpt2giga/fusion-code", "GigaChat-Fusion-Code"],
        )
    )


def _make_openai_app() -> FastAPI:
    app = FastAPI()
    app.include_router(openai_router)
    app.include_router(litellm_models_router)
    app.state.config = _fusion_config()
    app.state.gigachat_client = FakeClient()
    return app


def _make_gemini_app() -> FastAPI:
    app = FastAPI()
    app.include_router(gemini_models_router)
    app.state.config = _fusion_config()
    app.state.gigachat_client = FakeClient()
    return app


def test_openai_models_list_includes_fusion_aliases():
    response = TestClient(_make_openai_app()).get("/models")

    assert response.status_code == 200
    data = response.json()["data"]
    ids = [item["id"] for item in data]
    assert ids == ["GigaChat", "gpt2giga/fusion-code", "GigaChat-Fusion-Code"]
    assert data[1]["created"] == FUSION_MODEL_CREATED
    assert data[2]["created"] == FUSION_MODEL_CREATED


def test_openai_model_retrieve_returns_fusion_alias_without_upstream_call():
    app = _make_openai_app()
    response = TestClient(app).get("/models/gpt2giga/fusion-code")

    assert response.status_code == 200
    assert response.json()["id"] == "gpt2giga/fusion-code"
    assert response.json()["created"] == FUSION_MODEL_CREATED
    assert app.state.gigachat_client.model_calls == []


def test_anthropic_models_list_includes_fusion_shape():
    response = TestClient(_make_openai_app()).get(
        "/models",
        headers={"anthropic-version": "2023-06-01"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"][1]["id"] == "gpt2giga/fusion-code"
    assert body["data"][1]["display_name"] == "GigaFusion Code"
    assert body["data"][1]["type"] == "model"


def test_gemini_models_list_includes_fusion_shape():
    response = TestClient(_make_gemini_app()).get("/models")

    assert response.status_code == 200
    body = response.json()
    assert body["models"][1]["name"] == "models/gpt2giga/fusion-code"
    assert body["models"][1]["displayName"] == "GigaFusion Code"
    assert body["models"][1]["supportedGenerationMethods"] == [
        "generateContent",
        "streamGenerateContent",
        "countTokens",
    ]


def test_gemini_model_retrieve_returns_fusion_alias_without_upstream_call():
    app = _make_gemini_app()
    response = TestClient(app).get("/models/gpt2giga/fusion-code")

    assert response.status_code == 200
    assert response.json()["baseModelId"] == "gpt2giga/fusion-code"
    assert app.state.gigachat_client.model_calls == []


def test_litellm_model_info_includes_fusion_aliases():
    response = TestClient(_make_openai_app()).get("/model/info")

    assert response.status_code == 200
    entries = response.json()["data"]
    assert entries[1]["model_name"] == "gpt2giga/fusion-code"
    assert entries[1]["model_info"]["owned_by"] == "gpt2giga"


def test_litellm_model_query_returns_fusion_without_upstream_call():
    app = _make_openai_app()
    response = TestClient(app).get(
        "/model/info",
        params={"model": "gpt2giga/fusion-code"},
    )

    assert response.status_code == 200
    assert response.json()["model_name"] == "gpt2giga/fusion-code"
    assert app.state.gigachat_client.model_calls == []
