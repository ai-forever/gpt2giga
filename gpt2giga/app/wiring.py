"""Runtime service wiring for the FastAPI application."""

from fastapi import FastAPI

from gpt2giga.app.dependencies import (
    configure_runtime_observability,
    configure_runtime_stores,
    ensure_runtime_dependencies,
    get_runtime_observability,
    get_runtime_providers,
    get_runtime_services,
    get_runtime_stores,
    sync_runtime_aliases,
)
from gpt2giga.features.batches import BatchesService
from gpt2giga.features.chat import ChatService
from gpt2giga.features.embeddings import EmbeddingsService
from gpt2giga.features.files import FilesService
from gpt2giga.features.files_batches import FilesBatchesService
from gpt2giga.features.models import ModelsService
from gpt2giga.features.responses import ResponsesService
from gpt2giga.providers.gigachat import (
    AttachmentProcessor,
    GigaChatChatMapper,
    GigaChatEmbeddingsMapper,
    GigaChatModelsMapper,
    RequestTransformer,
    ResponseProcessor,
)
from gpt2giga.providers.gigachat.client import (
    close_app_gigachat_client,
    create_app_gigachat_client,
)


def wire_runtime_services(app: FastAPI, *, config, logger) -> None:
    """Initialize app-scoped runtime services on ``app.state``."""
    ensure_runtime_dependencies(app.state, config=config, logger=logger)
    services = get_runtime_services(app.state)
    get_runtime_stores(app.state)
    providers = get_runtime_providers(app.state)
    chat_backend_mode = config.proxy_settings.chat_backend_mode
    responses_backend_mode = config.proxy_settings.responses_backend_mode

    create_app_gigachat_client(app, settings=config.gigachat_settings)

    attachment_processor = AttachmentProcessor(
        logger,
        max_audio_file_size_bytes=config.proxy_settings.max_audio_file_size_bytes,
        max_image_file_size_bytes=config.proxy_settings.max_image_file_size_bytes,
        max_text_file_size_bytes=config.proxy_settings.max_text_file_size_bytes,
    )
    providers.attachment_processor = attachment_processor
    providers.request_transformer = RequestTransformer(
        config,
        logger,
        attachment_processor,
    )
    providers.response_processor = ResponseProcessor(
        logger,
        mode=config.proxy_settings.mode,
    )
    providers.chat_mapper = GigaChatChatMapper(
        request_transformer=providers.request_transformer,
        response_processor=providers.response_processor,
        backend_mode=chat_backend_mode,
    )
    services.chat = ChatService(providers.chat_mapper)
    providers.embeddings_mapper = GigaChatEmbeddingsMapper()
    services.embeddings = EmbeddingsService(
        providers.embeddings_mapper,
        embeddings_model=config.proxy_settings.embeddings,
    )
    providers.models_mapper = GigaChatModelsMapper()
    services.models = ModelsService(
        providers.models_mapper,
        embeddings_model=config.proxy_settings.embeddings,
    )
    services.files = FilesService()
    services.batches = BatchesService(
        providers.request_transformer,
        embeddings_model=config.proxy_settings.embeddings,
        gigachat_api_mode=chat_backend_mode,
    )
    services.files_batches = FilesBatchesService()
    services.responses = ResponsesService(
        providers.request_transformer,
        providers.response_processor,
        backend_mode=responses_backend_mode,
    )
    sync_runtime_aliases(app.state)


async def close_runtime_services(app: FastAPI, *, logger) -> None:
    """Close app-scoped runtime services initialized during startup."""
    await close_app_gigachat_client(app, logger=logger)

    providers = get_runtime_providers(app.state)
    attachment_processor = providers.attachment_processor
    if attachment_processor is not None:
        await attachment_processor.close()
        providers.attachment_processor = None
        app.state.attachment_processor = None

    stores = get_runtime_stores(app.state)
    if stores.backend is not None:
        await stores.backend.close()

    observability = get_runtime_observability(app.state)
    if observability.hub is not None:
        await observability.hub.close()


async def reload_runtime_services(app: FastAPI, *, config, logger) -> None:
    """Reload runtime services after a live-safe config update."""
    await close_runtime_services(app, logger=logger)

    ensure_runtime_dependencies(app.state, config=config, logger=logger)
    stores = configure_runtime_stores(app.state, config=config, logger=logger)
    if stores.backend is not None:
        await stores.backend.open()

    observability = configure_runtime_observability(
        app.state,
        config=config,
        logger=logger,
    )
    if observability.hub is not None:
        await observability.hub.open()

    wire_runtime_services(app, config=config, logger=logger)
