"""Application lifecycle setup."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from gpt2giga.app.settings import load_app_config, setup_app_logger
from gpt2giga.common.model_concurrency import ModelConcurrencyLimiter
from gpt2giga.protocol import AttachmentProcessor, RequestTransformer, ResponseProcessor
from gpt2giga.providers.gigachat.client import (
    close_gigachat_client,
    create_gigachat_client,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and close application-scoped runtime dependencies."""
    config = load_app_config(getattr(app.state, "config", None))
    logger = getattr(app.state, "logger", None)
    if logger is None:
        logger = setup_app_logger(config)

    app.state.config = config
    app.state.logger = logger
    app.state.model_concurrency_limiter = ModelConcurrencyLimiter(
        limits=config.proxy_settings.model_max_connections,
        default_limit=config.proxy_settings.model_max_connections_default,
        acquire_timeout=config.proxy_settings.model_max_connections_acquire_timeout,
    )
    app.state.gigachat_client = create_gigachat_client(config.gigachat_settings)

    attachment_processor = AttachmentProcessor(
        app.state.logger,
        max_audio_file_size_bytes=config.proxy_settings.max_audio_file_size_bytes,
        max_image_file_size_bytes=config.proxy_settings.max_image_file_size_bytes,
        max_text_file_size_bytes=config.proxy_settings.max_text_file_size_bytes,
    )
    app.state.attachment_processor = attachment_processor
    app.state.request_transformer = RequestTransformer(
        config, app.state.logger, attachment_processor
    )
    app.state.response_processor = ResponseProcessor(
        app.state.logger,
        mode=config.proxy_settings.mode,
        structured_output_mode=config.proxy_settings.structured_output_mode,
    )

    logger.info("Application startup complete")
    yield

    logger.info("Application shutdown initiated")
    await close_gigachat_client(getattr(app.state, "gigachat_client", None), logger)
    await attachment_processor.close()
