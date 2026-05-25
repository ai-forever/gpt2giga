"""Internal contracts for the models feature."""

from __future__ import annotations

from typing import Any, Protocol, TypeAlias, TypedDict, runtime_checkable


class ModelDescriptor(TypedDict):
    """Internal normalized model descriptor."""

    id: str
    object: str
    owned_by: str
    kind: str


ModelListData: TypeAlias = list[ModelDescriptor]


@runtime_checkable
class ModelsResource(Protocol):
    """GigaChat models resource surface."""

    async def list(self) -> Any:
        """Return the provider model catalog."""

    async def retrieve(self, model: str) -> Any:
        """Return a single provider model."""


@runtime_checkable
class ModelsUpstreamClient(Protocol):
    """Minimal upstream client surface required by the models feature."""

    a_models: ModelsResource


@runtime_checkable
class ModelsProviderMapper(Protocol):
    """Provider-specific model-discovery mapping surface."""

    def list_descriptors(self, response: Any) -> ModelListData:
        """Map a provider models response into internal descriptors."""

    def build_descriptor(
        self, model_obj: Any, *, kind: str = "generation"
    ) -> ModelDescriptor:
        """Map a provider model object into an internal descriptor."""

    def build_embeddings_descriptor(self, model_id: str) -> ModelDescriptor:
        """Build an internal descriptor for the configured embeddings model."""
