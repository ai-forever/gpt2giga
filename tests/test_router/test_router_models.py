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
        async def aget_models(self):
            return FakeModels()

        async def aget_model(self, model: str):
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


def test_models_one():
    app = make_app()
    client = TestClient(app)
    resp = client.get("/models/m1")
    assert resp.status_code == 200
    assert resp.json()["id"] == "m1"
    assert resp.json()["metadata"] == {"type": "chat"}


def test_embedding_model_metadata():
    app = make_app()
    client = TestClient(app)
    resp = client.get("/models/Embeddings-2")
    assert resp.status_code == 200
    assert resp.json()["metadata"] == {"type": "embedder"}
