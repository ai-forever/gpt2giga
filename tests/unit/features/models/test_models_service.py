from types import SimpleNamespace

import pytest

from gpt2giga.features.models.service import (
    ModelsService,
    get_models_service_from_state,
)
from gpt2giga.models.config import ProxyConfig


class FakeMapper:
    def __init__(self):
        self.list_called_with = None
        self.single_called_with = None
        self.embeddings_called_with = None

    def list_descriptors(self, response):
        self.list_called_with = response
        return [
            {
                "id": "GigaChat-2-Max",
                "object": "model",
                "owned_by": "gigachat",
                "kind": "generation",
            }
        ]

    def build_descriptor(self, model_obj, *, kind="generation"):
        self.single_called_with = (model_obj, kind)
        return {
            "id": getattr(model_obj, "id", "unknown"),
            "object": "model",
            "owned_by": "gigachat",
            "kind": kind,
        }

    def build_embeddings_descriptor(self, model_id):
        self.embeddings_called_with = model_id
        return {
            "id": model_id,
            "object": "model",
            "owned_by": "gpt2giga",
            "kind": "embeddings",
        }


class FakeClient:
    def __init__(self):
        self.list_response = SimpleNamespace(data=["raw-model"])
        self.last_model = None

    async def aget_models(self):
        return self.list_response

    async def aget_model(self, model: str):
        self.last_model = model
        return SimpleNamespace(id=model)


@pytest.mark.asyncio
async def test_models_service_uses_mapper_contract_and_adds_embeddings_model():
    mapper = FakeMapper()
    service = ModelsService(mapper, embeddings_model="EmbeddingsGigaR")
    giga_client = FakeClient()

    listed = await service.list_models(
        giga_client=giga_client,
        include_embeddings_model=True,
    )
    single = await service.get_model("GigaChat-2-Pro", giga_client=giga_client)

    assert mapper.list_called_with is giga_client.list_response
    assert mapper.embeddings_called_with == "EmbeddingsGigaR"
    assert listed[0]["id"] == "GigaChat-2-Max"
    assert listed[1]["kind"] == "embeddings"
    assert giga_client.last_model == "GigaChat-2-Pro"
    assert mapper.single_called_with[1] == "generation"
    assert single["id"] == "GigaChat-2-Pro"


@pytest.mark.asyncio
async def test_get_models_service_from_state_supports_normalized_embeddings_id():
    class UnusedClient:
        async def aget_models(self):
            raise AssertionError("aget_models should not be called")

        async def aget_model(self, model: str):
            raise AssertionError("aget_model should not be called")

    state = SimpleNamespace(config=ProxyConfig())
    service = get_models_service_from_state(state)

    descriptor = await service.get_model(
        f"models/{state.config.proxy_settings.embeddings}",
        giga_client=UnusedClient(),
        allow_embeddings_model=True,
    )

    assert state.models_service is service
    assert state.models_mapper is not None
    assert descriptor["kind"] == "embeddings"
    assert descriptor["id"] == f"models/{state.config.proxy_settings.embeddings}"
