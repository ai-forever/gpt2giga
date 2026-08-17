"""Static model-catalog projections for reviewed provider aliases."""

from __future__ import annotations

from typing import Any

from gpt2giga.protocols.normalized import BridgeFeature
from gpt2giga.providers.profiles.models import ProviderKind
from gpt2giga.providers.profiles.registry import ProviderRegistry


STATIC_REGISTRY_PROFILE_ID = "provider-registry"


def uses_static_registry_inventory(registry: ProviderRegistry) -> bool:
    """Return whether model discovery is fully owned by the loaded profiles."""
    return not any(
        profile.provider_kind is ProviderKind.GIGACHAT
        for profile in registry.config.profiles
    )


def static_registry_model_payloads(
    registry: ProviderRegistry,
) -> list[dict[str, Any]] | None:
    """Project enabled aliases without contacting an unrelated provider."""
    if not uses_static_registry_inventory(registry):
        return None

    payloads: list[dict[str, Any]] = []
    for alias in registry.public_aliases():
        route = registry.resolve(alias)
        model = registry.model_alias_for(route)
        capabilities = model.capabilities
        limits = capabilities.limits if capabilities is not None else None
        generation_methods = ["generateContent", "streamGenerateContent"]
        if (
            capabilities is not None
            and BridgeFeature.COUNT_TOKENS in capabilities.features
        ):
            generation_methods.append("countTokens")
        payloads.append(
            {
                "id": alias,
                "object": "model",
                "owned_by": route.provider_kind.value,
                "type": "chat",
                "display_name": alias,
                "description": (
                    "Reviewed model alias exposed by the gpt2giga provider registry."
                ),
                "input_token_limit": (
                    (limits.max_input_tokens or limits.context_window)
                    if limits is not None
                    else 0
                ),
                "output_token_limit": (
                    (limits.max_output_tokens or 0) if limits is not None else 0
                ),
                "supportedGenerationMethods": generation_methods,
            }
        )
    return payloads


def static_registry_catalog_snapshot(
    registry: ProviderRegistry,
) -> dict[str, Any] | None:
    """Build the content-free `/bridge/models` input for static aliases."""
    payloads = static_registry_model_payloads(registry)
    if payloads is None:
        return None
    revision = registry.config_revision
    return {
        "schema_version": "gpt2giga.model-catalog.v1",
        "provider_profile_id": STATIC_REGISTRY_PROFILE_ID,
        "inventory_revision": revision,
        "discovered_at": "process-startup",
        "expires_at": "process-restart",
        "stale": False,
        "source": "static_provider_profiles",
        "models": [
            {
                "id": payload["id"],
                "provider_kind": payload["owned_by"],
                "provider_profile_id": STATIC_REGISTRY_PROFILE_ID,
                "owned_by": payload["owned_by"],
                "model_type": payload["type"],
                "available": True,
                "deprecated": registry.resolve(payload["id"]).deprecated,
                "stale": False,
                "inventory_revision": revision,
            }
            for payload in payloads
        ],
    }
