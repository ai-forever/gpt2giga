"""Registry of mountable external provider adapters."""

from __future__ import annotations

from collections.abc import Collection, Iterable

from gpt2giga.providers.descriptors import ProviderDescriptor


_PROVIDERS: dict[str, ProviderDescriptor] = {}


def register_provider(descriptor: ProviderDescriptor) -> None:
    """Register or replace a provider descriptor."""
    _PROVIDERS[descriptor.name] = descriptor


def list_provider_descriptors() -> tuple[ProviderDescriptor, ...]:
    """Return registered provider descriptors in registration order."""
    return tuple(_PROVIDERS.values())


def get_provider_descriptor(name: str) -> ProviderDescriptor:
    """Return a registered provider descriptor by name."""
    try:
        return _PROVIDERS[name]
    except KeyError as exc:
        raise KeyError(f"Unknown provider descriptor: {name}") from exc


def iter_enabled_provider_descriptors(
    enabled_providers: Collection[str],
) -> Iterable[ProviderDescriptor]:
    """Iterate over provider descriptors enabled by the current config."""
    enabled = set(enabled_providers)
    for descriptor in list_provider_descriptors():
        if descriptor.is_enabled(enabled):
            yield descriptor


def _register_builtin_providers() -> None:
    """Bootstrap built-in provider descriptors once."""
    if _PROVIDERS:
        return

    from gpt2giga.providers.anthropic import ANTHROPIC_PROVIDER_DESCRIPTOR
    from gpt2giga.providers.gemini import GEMINI_PROVIDER_DESCRIPTOR
    from gpt2giga.providers.openai import OPENAI_PROVIDER_DESCRIPTOR

    for descriptor in (
        OPENAI_PROVIDER_DESCRIPTOR,
        ANTHROPIC_PROVIDER_DESCRIPTOR,
        GEMINI_PROVIDER_DESCRIPTOR,
    ):
        register_provider(descriptor)


_register_builtin_providers()
