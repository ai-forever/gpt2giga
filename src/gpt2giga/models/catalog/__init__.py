"""Dynamic provider model catalog contracts."""

from gpt2giga.models.catalog.contracts import (
    MODEL_CATALOG_SCHEMA_VERSION,
    CatalogSource,
    ModelCatalog,
    ModelCatalogSnapshot,
    ModelDescriptor,
    ModelDiscoveryContext,
    ModelNotFoundError,
)
from gpt2giga.models.catalog.selection import (
    ModelSelection,
    ModelSelectionPolicy,
    ModelSelectionSource,
)

__all__ = [
    "MODEL_CATALOG_SCHEMA_VERSION",
    "CatalogSource",
    "ModelCatalog",
    "ModelCatalogSnapshot",
    "ModelDescriptor",
    "ModelDiscoveryContext",
    "ModelNotFoundError",
    "ModelSelection",
    "ModelSelectionPolicy",
    "ModelSelectionSource",
]
