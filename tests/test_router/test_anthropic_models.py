from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from anthropic import Anthropic

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
        return FakeModels(
            data=[
                FakeModel(id="GigaChat", object="model"),
                FakeModel(id="GigaChat-Pro", object="model"),
            ]
        )

    async def aget_model(self, model: str):
        return FakeModel(id=model, object="model")


def _make_app():
    app = FastAPI()
    app.include_router(openai_router)
    app.include_router(openai_router, prefix="/v1")
    app.state.gigachat_client = FakeClient()
    return app


def _make_anthropic_client(app):
    test_client = TestClient(app)
    return Anthropic(
        api_key="test",
        base_url=str(test_client.base_url),
        http_client=test_client,
    )


def test_anthropic_models_list_uses_anthropic_shape():
    app = _make_app()
    client = _make_anthropic_client(app)

    page = client.models.list()

    assert page.data[0].id == "GigaChat"
    assert page.data[0].display_name == "GigaChat"
    assert page.data[0].type == "model"
    assert page.first_id == "GigaChat"
    assert page.last_id == "GigaChat-Pro"
    assert page.has_more is False


def test_anthropic_models_list_paginates():
    app = _make_app()
    client = _make_anthropic_client(app)

    page = client.models.list(limit=1)

    assert [model.id for model in page.data] == ["GigaChat"]
    assert page.first_id == "GigaChat"
    assert page.last_id == "GigaChat"
    assert page.has_more is True


def test_anthropic_models_retrieve_uses_anthropic_shape():
    app = _make_app()
    client = _make_anthropic_client(app)

    model = client.models.retrieve("GigaChat-Pro")

    assert model.id == "GigaChat-Pro"
    assert model.display_name == "GigaChat-Pro"
    assert model.type == "model"


def test_openai_models_keep_openai_shape_without_anthropic_headers():
    app = _make_app()
    response = TestClient(app).get("/v1/models")

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert body["data"][0]["id"] == "GigaChat"
    assert body["data"][0]["object"] == "model"
    assert "display_name" not in body["data"][0]


def test_gemini_models_list_uses_gemini_shape_for_google_client_headers():
    app = _make_app()
    response = TestClient(app).get(
        "/v1/models",
        headers={"x-goog-api-client": "genai-python/1.0"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["models"][0]["name"] == "models/GigaChat"
    assert body["models"][0]["supportedGenerationMethods"] == [
        "generateContent",
        "streamGenerateContent",
        "countTokens",
    ]
    assert body["nextPageToken"] == ""


def test_gemini_model_retrieve_uses_gemini_shape_for_google_client_headers():
    app = _make_app()
    response = TestClient(app).get(
        "/v1/models/GigaChat-Pro",
        headers={"x-goog-api-client": "genai-python/1.0"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "models/GigaChat-Pro"
    assert body["baseModelId"] == "GigaChat-Pro"
