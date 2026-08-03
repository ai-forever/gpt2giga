from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from gpt2giga.routers.openai import router


def make_app():
    app = FastAPI()
    app.include_router(router)

    class Model(BaseModel):
        id_: str = Field(alias="id")
        """Название модели"""
        object_: str = Field(alias="object")
        """Тип сущности в ответе, например, модель"""
        owned_by: str
        """Владелец модели"""

    class FakeModels(BaseModel):
        data: list = [
            Model(**{"id": "GigaChat-3-Pro", "object": "model", "owned_by": "m1"}),
            Model(**{"id": "Embeddings-2", "object": "model", "owned_by": "m1"}),
        ]
        object_: str = "list"

    class FakeClient:
        def __init__(self):
            self.model_list_calls = 0
            self.model_get_calls = 0
            self._settings = SimpleNamespace(
                credentials="credential",
                scope="scope",
                user=None,
                password=None,
                access_token=None,
                model="GigaChat-3-Pro",
            )

        async def aget_models(self):
            self.model_list_calls += 1
            return FakeModels()

        async def aget_model(self, model: str):
            self.model_get_calls += 1
            return Model(id=model, object="model", owned_by="m1")

    app.state.gigachat_client = FakeClient()
    return app


def test_models_list():
    app = make_app()
    client = TestClient(app)
    resp = client.get("/models")
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "list"
    assert [model["metadata"]["type"] for model in body["data"]] == [
        "chat",
        "embedder",
    ]
    assert [model["id"] for model in body["data"]] == [
        "GigaChat-3-Pro",
        "Embeddings-2",
    ]


def test_models_one():
    app = make_app()
    client = TestClient(app)
    resp = client.get("/models/GigaChat-3-Pro")
    assert resp.status_code == 200
    assert resp.json()["id"] == "GigaChat-3-Pro"
    assert resp.json()["metadata"] == {"type": "chat"}


def test_embedding_model_metadata():
    app = make_app()
    client = TestClient(app)
    resp = client.get("/models/Embeddings-2")
    assert resp.status_code == 200
    assert resp.json()["metadata"] == {"type": "embedder"}


def test_list_and_retrieve_share_one_catalog_snapshot():
    app = make_app()
    client = TestClient(app)

    assert client.get("/models").status_code == 200
    assert client.get("/models/GigaChat-3-Pro").status_code == 200

    assert app.state.gigachat_client.model_list_calls == 1
    assert app.state.gigachat_client.model_get_calls == 0


def test_models_explicit_refresh_bypasses_fresh_cache():
    app = make_app()
    client = TestClient(app)

    assert client.get("/models").status_code == 200
    assert client.get("/models").status_code == 200
    assert client.get("/models?refresh=true").status_code == 200

    assert app.state.gigachat_client.model_list_calls == 2


def test_unknown_model_is_not_fabricated_by_single_model_lookup():
    app = make_app()
    response = TestClient(app).get("/models/not-visible")

    assert response.status_code == 404
    assert app.state.gigachat_client.model_list_calls == 1
    assert app.state.gigachat_client.model_get_calls == 0
