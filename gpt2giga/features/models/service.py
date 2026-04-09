"""Models feature orchestration."""

from __future__ import annotations

from typing import Any

from gpt2giga.app.dependencies import (
    get_config_from_state,
    get_runtime_providers,
    get_runtime_services,
    set_runtime_provider,
    set_runtime_service,
)
from gpt2giga.features.models.contracts import (
    ModelDescriptor,
    ModelListData,
    ModelsProviderMapper,
    ModelsUpstreamClient,
)
from gpt2giga.providers.gigachat.models_mapper import GigaChatModelsMapper


class ModelsService:
    """Coordinate the internal model-discovery flow."""

    def __init__(self, mapper: ModelsProviderMapper, *, embeddings_model: str):
        self.mapper = mapper
        self.embeddings_model = embeddings_model
        self.normalized_embeddings_model = _normalize_model_id(embeddings_model)

    async def list_models(
        self,
        *,
        giga_client: ModelsUpstreamClient,
        include_embeddings_model: bool = False,
    ) -> ModelListData:
        """Return internal descriptors for available models."""
        descriptors = list(
            self.mapper.list_descriptors(await giga_client.aget_models())
        )
        if (
            self.normalized_embeddings_model
            and include_embeddings_model
            and not any(
                _normalize_model_id(descriptor["id"])
                == self.normalized_embeddings_model
                for descriptor in descriptors
            )
        ):
            descriptors.append(
                self.mapper.build_embeddings_descriptor(self.embeddings_model)
            )
        return descriptors

    async def get_model(
        self,
        model: str,
        *,
        giga_client: ModelsUpstreamClient,
        allow_embeddings_model: bool = False,
    ) -> ModelDescriptor:
        """Return an internal descriptor for a single model."""
        if (
            self.normalized_embeddings_model
            and allow_embeddings_model
            and _normalize_model_id(model) == self.normalized_embeddings_model
        ):
            return self.mapper.build_embeddings_descriptor(model)
        return self.mapper.build_descriptor(await giga_client.aget_model(model=model))


def get_models_service_from_state(state: Any) -> Any:
    """Resolve the app-scoped models service, creating it lazily if needed."""
    services = get_runtime_services(state)
    service = services.models
    if service is not None:
        return service

    providers = get_runtime_providers(state)
    mapper = providers.models_mapper
    if mapper is None:
        mapper = GigaChatModelsMapper()
        set_runtime_provider(state, "models_mapper", mapper)

    config = getattr(state, "config", None)
    embeddings_model = ""
    if config is not None:
        embeddings_model = getattr(
            get_config_from_state(state).proxy_settings, "embeddings", ""
        )
    service = ModelsService(
        mapper,
        embeddings_model=embeddings_model,
    )
    return set_runtime_service(state, "models", service)


def _normalize_model_id(model: str) -> str:
    return model.removeprefix("models/")
