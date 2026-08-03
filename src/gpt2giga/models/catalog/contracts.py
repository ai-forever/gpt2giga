"""Immutable contracts for dynamic provider model inventories."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

MODEL_CATALOG_SCHEMA_VERSION = "gpt2giga.model-catalog.v1"
_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"


class CatalogSource(str, Enum):
    """Identify how a catalog snapshot was obtained."""

    PROVIDER_API = "provider_api"
    STALE_CACHE = "stale_cache"


class ModelDiscoveryContext(BaseModel):
    """Identify one provider profile and credential scope without secrets."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_profile_id: str = Field(min_length=1)
    credential_scope_digest: str = Field(pattern=_SHA256_PATTERN)


class ModelDescriptor(BaseModel):
    """Describe one credential-visible provider model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    provider_kind: str = Field(min_length=1)
    provider_profile_id: str = Field(min_length=1)
    owned_by: str | None = None
    model_type: str | None = None
    available: bool = True
    deprecated: bool = False
    discovered_at: datetime
    stale: bool = False
    inventory_revision: str = Field(pattern=_SHA256_PATTERN)
    provider_metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_aware_discovery_time(self) -> ModelDescriptor:
        """Reject local or ambiguous inventory timestamps."""
        _require_aware(self.discovered_at, field_name="discovered_at")
        return self


class ModelCatalogSnapshot(BaseModel):
    """Represent one immutable, credential-scoped inventory observation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = MODEL_CATALOG_SCHEMA_VERSION
    provider_profile_id: str = Field(min_length=1)
    credential_scope_digest: str = Field(pattern=_SHA256_PATTERN)
    models: tuple[ModelDescriptor, ...]
    inventory_revision: str = Field(pattern=_SHA256_PATTERN)
    discovered_at: datetime
    expires_at: datetime
    stale: bool = False
    source: CatalogSource
    provider_metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_snapshot(self) -> ModelCatalogSnapshot:
        """Keep snapshot identity and lifetime internally consistent."""
        _require_aware(self.discovered_at, field_name="discovered_at")
        _require_aware(self.expires_at, field_name="expires_at")
        if self.expires_at < self.discovered_at:
            raise ValueError("expires_at must not precede discovered_at")
        if any(
            model.provider_profile_id != self.provider_profile_id
            for model in self.models
        ):
            raise ValueError("all models must belong to the snapshot provider profile")
        if any(
            model.inventory_revision != self.inventory_revision for model in self.models
        ):
            raise ValueError("all models must carry the snapshot inventory revision")
        if any(model.stale != self.stale for model in self.models):
            raise ValueError("all models must carry the snapshot stale state")
        return self


class ModelNotFoundError(LookupError):
    """Report a model missing from the current credential-visible inventory."""

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        super().__init__(f"Model {model_id!r} is not present in the catalog")


class ModelCatalog(Protocol):
    """Expose a shared asynchronous model inventory owner."""

    async def list_models(
        self,
        context: ModelDiscoveryContext,
        *,
        refresh: bool = False,
    ) -> ModelCatalogSnapshot:
        """Return the current inventory snapshot for one credential scope."""

    async def get_model(
        self,
        model_id: str,
        context: ModelDiscoveryContext,
        *,
        refresh: bool = False,
    ) -> ModelDescriptor:
        """Return one model from the same catalog used by list_models."""


def _require_aware(value: datetime, *, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
