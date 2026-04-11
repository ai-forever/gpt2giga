"""Shared provider descriptor dataclasses."""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from typing import Literal

from fastapi import APIRouter

from gpt2giga.providers.contracts import ProviderAdapterBundle

ProviderRouteAuthPolicy = Literal["default", "gemini"]


@dataclass(frozen=True, slots=True)
class ProviderMountSpec:
    """A concrete router mount owned by a provider descriptor."""

    router_factory: Callable[[], APIRouter]
    prefix: str = ""
    tags: tuple[str, ...] = ()
    auth_policy: ProviderRouteAuthPolicy = "default"


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    """Metadata required to mount and describe an external provider."""

    name: str
    display_name: str
    capabilities: tuple[str, ...]
    routes: tuple[str, ...]
    mounts: tuple[ProviderMountSpec, ...]
    adapters: ProviderAdapterBundle = field(default_factory=ProviderAdapterBundle)

    def is_enabled(self, enabled_providers: Collection[str]) -> bool:
        """Return whether the provider is enabled by the current config."""
        return self.name in enabled_providers
