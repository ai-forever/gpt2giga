"""Typed runtime dependency containers and accessors."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, TypeAlias, cast

from gpt2giga.app._runtime_backends import (
    EventFeed,
    RuntimeStateBackend,
    create_runtime_backend,
    provision_runtime_resources,
)
from gpt2giga.app._telemetry.hub import ObservabilityHub
from gpt2giga.app._telemetry.registry import create_observability_hub
from gpt2giga.core.config.settings import ProxyConfig
from gpt2giga.features.batches.contracts import BatchMetadata
from gpt2giga.features.files.contracts import FileMetadata

if TYPE_CHECKING:
    from gpt2giga.features.batches.service import BatchesService
    from gpt2giga.features.chat.service import ChatService
    from gpt2giga.features.embeddings.service import EmbeddingsService
    from gpt2giga.features.files.service import FilesService
    from gpt2giga.features.files_batches.service import FilesBatchesService
    from gpt2giga.features.models.service import ModelsService
    from gpt2giga.features.responses.service import ResponsesService
    from gpt2giga.providers.gigachat.attachments import AttachmentProcessor
    from gpt2giga.providers.gigachat.chat_mapper import GigaChatChatMapper
    from gpt2giga.providers.gigachat.embeddings_mapper import (
        GigaChatEmbeddingsMapper,
    )
    from gpt2giga.providers.gigachat.models_mapper import GigaChatModelsMapper

RuntimeStoreEntry: TypeAlias = dict[str, Any]
RuntimeFilesMetadataStore: TypeAlias = MutableMapping[str, FileMetadata]
RuntimeBatchesMetadataStore: TypeAlias = MutableMapping[str, BatchMetadata]
RuntimeResponsesMetadataStore: TypeAlias = MutableMapping[str, RuntimeStoreEntry]
RuntimeBatchInputBytesStore: TypeAlias = MutableMapping[str, bytes]
RuntimeValidationReportStore: TypeAlias = MutableMapping[str, RuntimeStoreEntry]
RuntimeUploadsStore: TypeAlias = MutableMapping[str, dict[str, Any]]
RuntimeUsageStore: TypeAlias = MutableMapping[str, RuntimeStoreEntry]
RuntimeGovernanceStore: TypeAlias = MutableMapping[str, RuntimeStoreEntry]


class RuntimeGigaChatClient(Protocol):
    """Minimal combined runtime client surface stored in app state."""

    async def aclose(self) -> None:
        """Close the app-scoped client when supported."""


RuntimeGigaChatFactory: TypeAlias = Callable[..., RuntimeGigaChatClient]


class LoggerLike(Protocol):
    """Minimal logger surface used across runtime helpers."""

    def bind(self, **kwargs: Any) -> "LoggerLike":
        """Return a logger with bound context."""

    def debug(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Emit a debug log message."""

    def info(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Emit an info log message."""

    def warning(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Emit a warning log message."""

    def error(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Emit an error log message."""

    def exception(self, message: str, *args: Any, **kwargs: Any) -> None:
        """Emit an exception log message."""


class RuntimeRequestTransformer(Protocol):
    """Combined request-transformer surface used across runtime features."""

    async def prepare_chat_completion(
        self,
        data: object,
        giga_client: RuntimeGigaChatClient | None = None,
    ) -> object:
        """Prepare a legacy chat-completions payload."""

    async def prepare_chat_completion_v2(
        self,
        data: object,
        giga_client: RuntimeGigaChatClient | None = None,
    ) -> object:
        """Prepare a native chat-v2 payload."""

    async def prepare_response(
        self,
        data: object,
        giga_client: RuntimeGigaChatClient | None = None,
    ) -> object:
        """Prepare a legacy Responses payload."""

    async def prepare_response_v2(
        self,
        data: object,
        giga_client: RuntimeGigaChatClient | None = None,
        response_store: RuntimeResponsesMetadataStore | None = None,
    ) -> object:
        """Prepare a native Responses v2 payload."""


class RuntimeResponseProcessor(Protocol):
    """Combined response-processor surface used across runtime features."""

    def process_response(
        self,
        giga_resp: object,
        gpt_model: str,
        response_id: str,
        request_data: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Process a chat-completions response."""

    def process_response_v2(
        self,
        giga_resp: object,
        gpt_model: str,
        response_id: str,
        request_data: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Process a chat-v2 response."""

    def process_response_api(
        self,
        data: object,
        giga_resp: object,
        gpt_model: str,
        response_id: str,
    ) -> dict[str, object]:
        """Process a legacy Responses API payload."""

    def process_response_api_v2(
        self,
        data: object,
        giga_resp: object,
        gpt_model: str,
        response_id: str,
        response_store: RuntimeResponsesMetadataStore | None = None,
    ) -> dict[str, object]:
        """Process a native Responses API payload."""


@dataclass(slots=True)
class RuntimeServices:
    """App-scoped feature services."""

    chat: ChatService | None = None
    responses: ResponsesService | None = None
    embeddings: EmbeddingsService | None = None
    models: ModelsService | None = None
    files: FilesService | None = None
    batches: BatchesService | None = None
    files_batches: FilesBatchesService | None = None


@dataclass(slots=True)
class RuntimeStores:
    """App-scoped stateful runtime resources."""

    backend: RuntimeStateBackend | None = None
    files: RuntimeFilesMetadataStore = field(default_factory=dict)
    batches: RuntimeBatchesMetadataStore = field(default_factory=dict)
    batch_input_bytes: RuntimeBatchInputBytesStore = field(default_factory=dict)
    batch_validation_reports: RuntimeValidationReportStore = field(default_factory=dict)
    gemini_uploads: RuntimeUploadsStore = field(default_factory=dict)
    responses: RuntimeResponsesMetadataStore = field(default_factory=dict)
    usage_by_api_key: RuntimeUsageStore = field(default_factory=dict)
    usage_by_provider: RuntimeUsageStore = field(default_factory=dict)
    governance_counters: RuntimeGovernanceStore = field(default_factory=dict)
    recent_requests: EventFeed | None = None
    recent_errors: EventFeed | None = None


@dataclass(slots=True)
class RuntimeProviders:
    """App-scoped provider clients and provider-owned helpers."""

    gigachat_client: RuntimeGigaChatClient | None = None
    gigachat_factory: RuntimeGigaChatFactory | None = None
    gigachat_factory_getter: Callable[[], RuntimeGigaChatFactory] | None = None
    attachment_processor: AttachmentProcessor | None = None
    request_transformer: RuntimeRequestTransformer | None = None
    response_processor: RuntimeResponseProcessor | None = None
    chat_mapper: GigaChatChatMapper | None = None
    embeddings_mapper: GigaChatEmbeddingsMapper | None = None
    models_mapper: GigaChatModelsMapper | None = None


@dataclass(slots=True)
class RuntimeObservability:
    """App-scoped observability hubs and exporters."""

    hub: ObservabilityHub | None = None
    telemetry_enabled: bool = True
    configured: bool = False


class MutableRuntimeState(Protocol):
    """Typed mutable app.state view used by runtime helpers."""

    config: ProxyConfig | None
    logger: LoggerLike | None
    services: RuntimeServices
    stores: RuntimeStores
    providers: RuntimeProviders
    observability: RuntimeObservability


def _as_runtime_state(state: object) -> MutableRuntimeState:
    """Cast a generic app state object into the mutable runtime protocol."""
    return cast(MutableRuntimeState, state)


def ensure_runtime_dependencies(
    state: object,
    *,
    config: ProxyConfig | None = None,
    logger: LoggerLike | None = None,
) -> None:
    """Ensure the typed runtime containers exist on app state."""
    runtime_state = _as_runtime_state(state)
    if config is not None:
        runtime_state.config = config
    if logger is not None:
        runtime_state.logger = logger

    get_runtime_services(state)
    configure_runtime_stores(state, config=config, logger=logger)
    get_runtime_providers(state)
    configure_runtime_observability(state, config=config, logger=logger)


def get_runtime_services(state: object) -> RuntimeServices:
    """Return the typed services container for app state."""
    runtime_state = _as_runtime_state(state)
    services = getattr(runtime_state, "services", None)
    if not isinstance(services, RuntimeServices):
        services = RuntimeServices()
        runtime_state.services = services
    return services


def get_runtime_stores(state: object) -> RuntimeStores:
    """Return the typed stores container for app state."""
    runtime_state = _as_runtime_state(state)
    stores = getattr(runtime_state, "stores", None)
    if not isinstance(stores, RuntimeStores):
        stores = RuntimeStores()
        runtime_state.stores = stores
    if (
        stores.backend is None
        or stores.recent_requests is None
        or stores.recent_errors is None
    ):
        configure_runtime_stores(
            state,
            config=getattr(runtime_state, "config", None),
            logger=getattr(runtime_state, "logger", None),
        )
    return stores


def configure_runtime_stores(
    state: object,
    *,
    config: ProxyConfig | None = None,
    logger: LoggerLike | None = None,
) -> RuntimeStores:
    """Provision runtime stores and feeds through the configured backend."""
    runtime_state = _as_runtime_state(state)
    stores = getattr(runtime_state, "stores", None)
    if not isinstance(stores, RuntimeStores):
        stores = RuntimeStores()
        runtime_state.stores = stores

    proxy_settings = getattr(config, "proxy_settings", None)
    runtime_store = getattr(proxy_settings, "runtime_store", None)
    backend_name = getattr(
        runtime_store,
        "backend",
        getattr(proxy_settings, "runtime_store_backend", "memory"),
    )
    current_backend = stores.backend
    if current_backend is not None and current_backend.name == backend_name:
        return stores

    backend = create_runtime_backend(backend_name, config=config, logger=logger)
    resources = provision_runtime_resources(backend, config=config)
    stores.backend = backend
    stores.files = resources["files"]
    stores.batches = resources["batches"]
    stores.responses = resources["responses"]
    stores.usage_by_api_key = resources["usage_by_api_key"]
    stores.usage_by_provider = resources["usage_by_provider"]
    stores.governance_counters = resources["governance_counters"]
    stores.recent_requests = resources["recent_requests"]
    stores.recent_errors = resources["recent_errors"]
    return stores


def get_runtime_providers(state: object) -> RuntimeProviders:
    """Return the typed providers container for app state."""
    runtime_state = _as_runtime_state(state)
    providers = getattr(runtime_state, "providers", None)
    if not isinstance(providers, RuntimeProviders):
        providers = RuntimeProviders()
        runtime_state.providers = providers
    return providers


def get_runtime_observability(state: object) -> RuntimeObservability:
    """Return the typed observability container for app state."""
    runtime_state = _as_runtime_state(state)
    observability = getattr(runtime_state, "observability", None)
    if not isinstance(observability, RuntimeObservability):
        observability = RuntimeObservability()
        runtime_state.observability = observability
    if not observability.configured:
        configure_runtime_observability(
            state,
            config=getattr(runtime_state, "config", None),
            logger=getattr(runtime_state, "logger", None),
        )
    return observability


def configure_runtime_observability(
    state: object,
    *,
    config: ProxyConfig | None = None,
    logger: LoggerLike | None = None,
) -> RuntimeObservability:
    """Provision configured observability sinks."""
    runtime_state = _as_runtime_state(state)
    observability = getattr(runtime_state, "observability", None)
    if not isinstance(observability, RuntimeObservability):
        observability = RuntimeObservability()
        runtime_state.observability = observability

    proxy_settings = getattr(config, "proxy_settings", None)
    grouped_settings = getattr(proxy_settings, "observability", None)
    telemetry_enabled = bool(
        getattr(
            grouped_settings,
            "enable_telemetry",
            getattr(proxy_settings, "enable_telemetry", True),
        )
    )
    sink_names = list(
        getattr(
            grouped_settings,
            "active_sinks",
            getattr(proxy_settings, "observability_sinks", ["prometheus"]),
        )
    )
    current_hub = observability.hub
    if not telemetry_enabled:
        observability.hub = None
        observability.telemetry_enabled = False
        observability.configured = True
        return observability

    if (
        current_hub is not None
        and observability.telemetry_enabled
        and current_hub.enabled_sink_names == sink_names
    ):
        observability.configured = True
        return observability

    observability.hub = create_observability_hub(
        sink_names,
        config=config,
        logger=logger,
    )
    observability.telemetry_enabled = True
    observability.configured = True
    return observability


def set_runtime_service(state: object, name: str, value: object) -> object:
    """Store a feature service in the typed runtime container."""
    services = get_runtime_services(state)
    setattr(services, name, value)
    return value


def set_runtime_provider(state: object, name: str, value: object) -> object:
    """Store a provider helper in the typed runtime container."""
    providers = get_runtime_providers(state)
    setattr(providers, name, value)
    return value


def get_config_from_state(state: object) -> ProxyConfig:
    """Return the configured proxy config from app state."""
    config = getattr(_as_runtime_state(state), "config", None)
    if config is None:
        raise RuntimeError("Application config is not configured.")
    return config


def get_logger_from_state(state: object) -> LoggerLike | None:
    """Return the configured logger from app state when present."""
    return getattr(_as_runtime_state(state), "logger", None)


def get_request_transformer_from_state(state: object) -> RuntimeRequestTransformer:
    """Return the configured request transformer from app state."""
    transformer = get_runtime_providers(state).request_transformer
    if transformer is None:
        raise RuntimeError("Request transformer is not configured.")
    return transformer


def get_response_processor_from_state(state: object) -> RuntimeResponseProcessor:
    """Return the configured response processor from app state."""
    processor = get_runtime_providers(state).response_processor
    if processor is None:
        raise RuntimeError("Response processor is not configured.")
    return processor
