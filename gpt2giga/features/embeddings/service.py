"""Embeddings feature orchestration."""

from __future__ import annotations

from typing import Any

from gpt2giga.core.contracts import to_backend_payload
from gpt2giga.features.embeddings.contracts import (
    EmbeddingsProviderMapper,
    EmbeddingsRequestData,
    EmbeddingsUpstreamClient,
    PreparedEmbeddingsRequest,
)
from gpt2giga.providers.gigachat.embeddings_mapper import (
    apply_embedding_encoding_format,
    normalize_embedding_response,
)
from gpt2giga.providers.gigachat.resource_api import create_embeddings


class EmbeddingsService:
    """Coordinate the internal embeddings flow."""

    def __init__(
        self,
        mapper: EmbeddingsProviderMapper,
        *,
        embeddings_model: str,
        pass_model: bool = False,
    ):
        self.mapper = mapper
        self.embeddings_model = embeddings_model
        self.pass_model = pass_model

    async def prepare_request(
        self,
        data: EmbeddingsRequestData,
    ) -> PreparedEmbeddingsRequest:
        """Prepare a provider request for embeddings."""
        return await self.mapper.prepare_request(
            data,
            embeddings_model=self.embeddings_model,
            pass_model=self.pass_model,
        )

    async def create_embeddings(
        self,
        data: EmbeddingsRequestData,
        *,
        giga_client: EmbeddingsUpstreamClient,
    ) -> Any:
        """Execute an embeddings request from an OpenAI-style payload."""
        request_payload = to_backend_payload(data)
        prepared_request = await self.prepare_request(data)
        response = await create_embeddings(
            giga_client,
            texts=prepared_request["input"],
            model=prepared_request["model"],
        )
        normalized = normalize_embedding_response(
            response,
            model=prepared_request["model"],
        )
        return apply_embedding_encoding_format(
            normalized,
            request_payload.get("encoding_format"),
        )

    async def embed_texts(
        self,
        texts: list[str],
        *,
        giga_client: EmbeddingsUpstreamClient,
    ) -> Any:
        """Execute an embeddings request for already-normalized texts."""
        return await create_embeddings(
            giga_client,
            texts=texts,
            model=self.embeddings_model,
        )


def get_embeddings_service_from_state(state: Any) -> Any:
    """Resolve the app-scoped embeddings service, creating it lazily if needed."""
    from gpt2giga.app.dependencies import (
        get_config_from_state,
        get_runtime_providers,
        get_runtime_services,
        set_runtime_provider,
        set_runtime_service,
    )
    from gpt2giga.providers.gigachat.embeddings_mapper import GigaChatEmbeddingsMapper

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
    proxy_settings = config.proxy_settings
    service = EmbeddingsService(
        mapper,
        embeddings_model=proxy_settings.embeddings,
        pass_model=proxy_settings.pass_model,
    )
    return set_runtime_service(state, "embeddings", service)
