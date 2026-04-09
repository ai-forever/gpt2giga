from types import SimpleNamespace

import pytest

from gpt2giga.features.embeddings.service import (
    EmbeddingsService,
    get_embeddings_service_from_state,
)
from gpt2giga.models.config import ProxyConfig


class FakeMapper:
    def __init__(self):
        self.prepared_with = None

    async def prepare_request(self, data, *, embeddings_model):
        self.prepared_with = (data, embeddings_model)
        return {"input": ["hello"], "model": embeddings_model}


class FakeClient:
    def __init__(self):
        self.last_request = None

    async def aembeddings(self, texts, model):
        self.last_request = (list(texts), model)
        return {"data": [{"embedding": [0.1], "index": 0}], "model": model}


@pytest.mark.asyncio
async def test_embeddings_service_create_embeddings_uses_mapper_contract():
    mapper = FakeMapper()
    service = EmbeddingsService(mapper, embeddings_model="EmbeddingsGigaR")
    giga_client = FakeClient()
    data = {"model": "gpt-x", "input": "hello"}

    result = await service.create_embeddings(data, giga_client=giga_client)

    assert mapper.prepared_with == (data, "EmbeddingsGigaR")
    assert giga_client.last_request == (["hello"], "EmbeddingsGigaR")
    assert result["model"] == "EmbeddingsGigaR"


@pytest.mark.asyncio
async def test_get_embeddings_service_from_state_builds_default_mapper_from_config():
    state = SimpleNamespace(config=ProxyConfig())

    service = get_embeddings_service_from_state(state)
    prepared = await service.prepare_request({"model": "gpt-x", "input": "hello"})

    assert state.embeddings_service is service
    assert state.embeddings_mapper is service.mapper
    assert prepared == {
        "input": ["hello"],
        "model": state.config.proxy_settings.embeddings,
    }
