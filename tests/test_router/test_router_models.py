from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from gpt2giga.routers.api_router import router


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
        data: list = [Model(**{"id": "m1", "object": "model", "owned_by": "m1"})]
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


def test_models_one():
    app = make_app()
    client = TestClient(app)
    resp = client.get("/models/m1")
    assert resp.status_code == 200
    assert resp.json()["id"] == "m1"
