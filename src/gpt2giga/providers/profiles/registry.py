"""Exact public-model alias resolution for loaded provider profiles."""

from __future__ import annotations

from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Any

from gpt2giga.providers.profiles.errors import (
    ProviderAliasError,
    ProviderProfileError,
)
from gpt2giga.providers.profiles.loader import LoadedProviderProfileSet
from gpt2giga.providers.profiles.models import (
    ProviderKind,
    ProviderModelAlias,
    ProviderProfile,
    ProviderSupportStatus,
)


BRIDGE_MODELS_SCHEMA_VERSION = "gpt2giga.bridge-models.v1"
EXECUTION_CONTEXT_SCHEMA_VERSION = "gpt2giga.execution-context.v1"
_REVISION = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class ResolvedProviderRoute:
    """Exact secret-free route selected before admission and provider I/O."""

    config_revision: str
    profile_revision: str
    profile_id: str
    public_alias: str
    provider_kind: ProviderKind
    upstream_model: str
    capability_profile: str
    loss_matrix_revision: str
    support_status: ProviderSupportStatus
    deprecated: bool

    def execution_context(self) -> dict[str, str]:
        """Project the frozen execution-context v1 contract."""
        return {
            "schema_version": EXECUTION_CONTEXT_SCHEMA_VERSION,
            "config_revision": self.config_revision,
            "profile_revision": self.profile_revision,
            "profile_id": self.profile_id,
            "public_alias": self.public_alias,
            "provider_kind": self.provider_kind.value,
            "upstream_model": self.upstream_model,
            "capability_profile": self.capability_profile,
            "loss_matrix_revision": self.loss_matrix_revision,
        }


class ProviderRegistry:
    """Immutable and deterministic authority for public model aliases."""

    schema_version = "gpt2giga.provider-profiles.v1"
    immutable = True

    def __init__(
        self,
        loaded: LoadedProviderProfileSet,
        *,
        loss_matrix_revision: str,
    ) -> None:
        if not _REVISION.fullmatch(loss_matrix_revision):
            raise ProviderProfileError(
                "invalid_profile_schema",
                "Loss matrix revision must be a canonical SHA-256 revision.",
            )
        entries: dict[str, tuple[ProviderProfile, ProviderModelAlias]] = {}
        for profile in loaded.config.profiles:
            for model in profile.models:
                if model.public_alias in entries:
                    raise ProviderProfileError(
                        "duplicate_model_alias",
                        "Public model aliases must be globally unique.",
                    )
                entries[model.public_alias] = (profile, model)
        self._loaded = loaded
        self._loss_matrix_revision = loss_matrix_revision
        self._entries = MappingProxyType(entries)

    @property
    def config_revision(self) -> str:
        """Return the exact loaded configuration revision."""
        return self._loaded.revision

    @property
    def loss_matrix_revision(self) -> str:
        """Return the matrix revision bound to every resolution."""
        return self._loss_matrix_revision

    def resolve(self, public_alias: str) -> ResolvedProviderRoute:
        """Resolve only an exact, enabled public alias without fallback."""
        if not isinstance(public_alias, str):
            raise ProviderAliasError("alias_not_string")
        entry = self._entries.get(public_alias)
        if entry is None:
            raise ProviderAliasError("alias_unknown")
        profile, model = entry
        if not model.enabled:
            raise ProviderAliasError("alias_disabled")
        return ResolvedProviderRoute(
            config_revision=self.config_revision,
            profile_revision=profile.revision,
            profile_id=profile.profile_id,
            public_alias=model.public_alias,
            provider_kind=profile.provider_kind,
            upstream_model=model.upstream_model,
            capability_profile=model.capability_profile,
            loss_matrix_revision=self.loss_matrix_revision,
            support_status=model.support_status,
            deprecated=model.deprecated,
        )

    def credential_for(self, route: ResolvedProviderRoute) -> str:
        """Resolve a credential only after an exact route has been selected."""
        current = self.resolve(route.public_alias)
        if current != route:
            raise ProviderAliasError("route_revision_mismatch")
        return self._loaded.credential_for(route.profile_id)

    def public_aliases(self) -> tuple[str, ...]:
        """Return enabled aliases in deterministic lexical order."""
        return tuple(
            sorted(
                alias for alias, (_, model) in self._entries.items() if model.enabled
            )
        )

    def models_manifest(self) -> dict[str, Any]:
        """Return deterministic content-free data for `/bridge/models`."""
        models: list[dict[str, object]] = []
        for alias in self.public_aliases():
            route = self.resolve(alias)
            models.append(
                {
                    "public_alias": route.public_alias,
                    "provider_kind": route.provider_kind.value,
                    "capability_profile": route.capability_profile,
                    "support_status": route.support_status.value,
                    "deprecated": route.deprecated,
                    "profile_revision": route.profile_revision,
                }
            )
        return {
            "schema_version": BRIDGE_MODELS_SCHEMA_VERSION,
            "config_revision": self.config_revision,
            "matrix_revision": self.loss_matrix_revision,
            "models": models,
        }
