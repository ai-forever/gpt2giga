"""Typed runtime dependency containers and accessors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RuntimeServices:
    """App-scoped feature services."""

    chat: Any = None
    responses: Any = None
    embeddings: Any = None
    models: Any = None
    files: Any = None
    batches: Any = None


@dataclass(slots=True)
class RuntimeStores:
    """App-scoped in-memory metadata stores."""

    files: dict[str, Any] = field(default_factory=dict)
    batches: dict[str, Any] = field(default_factory=dict)
    responses: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RuntimeProviders:
    """App-scoped provider clients and provider-owned helpers."""

    gigachat_client: Any = None
    gigachat_factory: Any = None
    gigachat_factory_getter: Callable[[], Any] | None = None
    attachment_processor: Any = None
    request_transformer: Any = None
    response_processor: Any = None
    chat_mapper: Any = None
    embeddings_mapper: Any = None
    models_mapper: Any = None


_SERVICE_ALIASES = {
    "chat": "chat_service",
    "responses": "responses_service",
    "embeddings": "embeddings_service",
    "models": "models_service",
    "files": "files_service",
    "batches": "batches_service",
}

_STORE_ALIASES = {
    "files": "file_metadata_store",
    "batches": "batch_metadata_store",
    "responses": "response_metadata_store",
}

_PROVIDER_ALIASES = {
    "gigachat_client": "gigachat_client",
    "gigachat_factory": "gigachat_factory",
    "gigachat_factory_getter": "gigachat_factory_getter",
    "attachment_processor": "attachment_processor",
    "request_transformer": "request_transformer",
    "response_processor": "response_processor",
    "chat_mapper": "chat_mapper",
    "embeddings_mapper": "embeddings_mapper",
    "models_mapper": "models_mapper",
}


def ensure_runtime_dependencies(
    state: Any,
    *,
    config: Any | None = None,
    logger: Any | None = None,
) -> None:
    """Ensure the typed runtime containers exist on app state."""
    if config is not None:
        state.config = config
    if logger is not None:
        state.logger = logger

    get_runtime_services(state)
    get_runtime_stores(state)
    get_runtime_providers(state)
    sync_runtime_aliases(state)


def get_runtime_services(state: Any) -> RuntimeServices:
    """Return the typed services container for app state."""
    services = getattr(state, "services", None)
    if not isinstance(services, RuntimeServices):
        services = RuntimeServices()
        state.services = services
    _merge_runtime_aliases(state, services, _SERVICE_ALIASES, skip_none=True)
    return services


def get_runtime_stores(state: Any) -> RuntimeStores:
    """Return the typed stores container for app state."""
    stores = getattr(state, "stores", None)
    if not isinstance(stores, RuntimeStores):
        stores = RuntimeStores()
        state.stores = stores
    _merge_runtime_aliases(state, stores, _STORE_ALIASES, skip_none=False)
    return stores


def get_runtime_providers(state: Any) -> RuntimeProviders:
    """Return the typed providers container for app state."""
    providers = getattr(state, "providers", None)
    if not isinstance(providers, RuntimeProviders):
        providers = RuntimeProviders()
        state.providers = providers
    _merge_runtime_aliases(state, providers, _PROVIDER_ALIASES, skip_none=True)
    return providers


def set_runtime_service(state: Any, name: str, value: Any) -> Any:
    """Store a feature service in the typed runtime container."""
    services = get_runtime_services(state)
    setattr(services, name, value)
    sync_runtime_aliases(state)
    return value


def set_runtime_provider(state: Any, name: str, value: Any) -> Any:
    """Store a provider helper in the typed runtime container."""
    providers = get_runtime_providers(state)
    setattr(providers, name, value)
    sync_runtime_aliases(state)
    return value


def sync_runtime_aliases(state: Any) -> None:
    """Mirror typed runtime containers onto legacy flat state aliases."""
    _sync_runtime_aliases(
        state,
        get_runtime_services(state),
        _SERVICE_ALIASES,
        skip_none=True,
    )
    _sync_runtime_aliases(
        state,
        get_runtime_stores(state),
        _STORE_ALIASES,
        skip_none=False,
    )
    _sync_runtime_aliases(
        state,
        get_runtime_providers(state),
        _PROVIDER_ALIASES,
        skip_none=True,
    )


def get_config_from_state(state: Any) -> Any:
    """Return the configured proxy config from app state."""
    config = getattr(state, "config", None)
    if config is None:
        raise RuntimeError("Application config is not configured.")
    return config


def get_logger_from_state(state: Any) -> Any:
    """Return the configured logger from app state when present."""
    return getattr(state, "logger", None)


def get_request_transformer_from_state(state: Any) -> Any:
    """Return the configured request transformer from app state."""
    transformer = get_runtime_providers(state).request_transformer
    if transformer is None:
        raise RuntimeError("Request transformer is not configured.")
    return transformer


def get_response_processor_from_state(state: Any) -> Any:
    """Return the configured response processor from app state."""
    processor = get_runtime_providers(state).response_processor
    if processor is None:
        raise RuntimeError("Response processor is not configured.")
    return processor


def _merge_runtime_aliases(
    state: Any,
    container: Any,
    aliases: dict[str, str],
    *,
    skip_none: bool,
) -> None:
    for field_name, alias_name in aliases.items():
        if hasattr(state, alias_name):
            legacy_value = getattr(state, alias_name)
            if not skip_none or legacy_value is not None:
                setattr(container, field_name, legacy_value)

        value = getattr(container, field_name)
        if skip_none and value is None:
            continue
        setattr(state, alias_name, value)


def _sync_runtime_aliases(
    state: Any,
    container: Any,
    aliases: dict[str, str],
    *,
    skip_none: bool,
) -> None:
    for field_name, alias_name in aliases.items():
        value = getattr(container, field_name)
        if skip_none and value is None:
            continue
        setattr(state, alias_name, value)
