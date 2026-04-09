"""Embeddings feature orchestration."""

from __future__ import annotations

from typing import Any

from gpt2giga.app.dependencies import (
    get_config_from_state,
    get_runtime_providers,
    get_runtime_services,
    set_runtime_provider,
    set_runtime_service,
)
from gpt2giga.features.embeddings.contracts import (
    EmbeddingsProviderMapper,
    EmbeddingsRequestData,
    EmbeddingsUpstreamClient,
    PreparedEmbeddingsRequest,
)
from gpt2giga.providers.gigachat.embeddings_mapper import GigaChatEmbeddingsMapper


class EmbeddingsService:
    """Coordinate the internal embeddings flow."""

    def __init__(self, mapper: EmbeddingsProviderMapper, *, embeddings_model: str):
        self.mapper = mapper
        self.embeddings_model = embeddings_model

    async def prepare_request(
        self,
        data: EmbeddingsRequestData,
    ) -> PreparedEmbeddingsRequest:
        """Prepare a provider request for embeddings."""
        return await self.mapper.prepare_request(
            data,
            embeddings_model=self.embeddings_model,
        )

    async def create_embeddings(
        self,
        data: EmbeddingsRequestData,
        *,
        giga_client: EmbeddingsUpstreamClient,
    ) -> Any:
        """Execute an embeddings request from an OpenAI-style payload."""
        prepared_request = await self.prepare_request(data)
        return await giga_client.aembeddings(
            texts=prepared_request["input"],
            model=prepared_request["model"],
        )

    async def embed_texts(
        self,
        texts: list[str],
        *,
        giga_client: EmbeddingsUpstreamClient,
    ) -> Any:
        """Execute an embeddings request for already-normalized texts."""
        return await giga_client.aembeddings(texts=texts, model=self.embeddings_model)


def get_embeddings_service_from_state(state: Any) -> Any:
    """Resolve the app-scoped embeddings service, creating it lazily if needed."""
    services = get_runtime_services(state)
    service = services.embeddings
    if service is not None:
        return service

    providers = get_runtime_providers(state)
    mapper = providers.embeddings_mapper
    if mapper is None:
        mapper = GigaChatEmbeddingsMapper()
        set_runtime_provider(state, "embeddings_mapper", mapper)

    config = get_config_from_state(state)
    embeddings_model = config.proxy_settings.embeddings
    service = EmbeddingsService(mapper, embeddings_model=embeddings_model)
    return set_runtime_service(state, "embeddings", service)
