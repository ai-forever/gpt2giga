"""Provider adapter registry accessors."""


def list_provider_descriptors():
    """Return registered provider descriptors."""
    from gpt2giga.providers.registry import list_provider_descriptors as _list

    return _list()


def get_provider_descriptor(name: str):
    """Return a provider descriptor by name."""
    from gpt2giga.providers.registry import get_provider_descriptor as _get

    return _get(name)


def iter_enabled_provider_descriptors(enabled_providers):
    """Iterate over enabled provider descriptors."""
    from gpt2giga.providers.registry import (
        iter_enabled_provider_descriptors as _iter,
    )

    return _iter(enabled_providers)


def register_provider(descriptor):
    """Register a provider descriptor."""
    from gpt2giga.providers.registry import register_provider as _register

    return _register(descriptor)


def __getattr__(name: str):
    if name not in {"ProviderDescriptor", "ProviderMountSpec"}:
        raise AttributeError(name)

    from gpt2giga.providers.descriptors import ProviderDescriptor, ProviderMountSpec

    exported = {
        "ProviderDescriptor": ProviderDescriptor,
        "ProviderMountSpec": ProviderMountSpec,
    }
    return exported[name]


__all__ = [
    "ProviderDescriptor",
    "ProviderMountSpec",
    "get_provider_descriptor",
    "iter_enabled_provider_descriptors",
    "list_provider_descriptors",
    "register_provider",
]
