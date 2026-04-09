"""Runtime service wiring for the FastAPI application."""

from fastapi import FastAPI

from gpt2giga.providers.gigachat import (
    AttachmentProcessor,
    RequestTransformer,
    ResponseProcessor,
)
from gpt2giga.providers.gigachat.client import (
    close_app_gigachat_client,
    create_app_gigachat_client,
)


def wire_runtime_services(app: FastAPI, *, config, logger) -> None:
    """Initialize app-scoped runtime services on ``app.state``."""
    create_app_gigachat_client(app, settings=config.gigachat_settings)

    attachment_processor = AttachmentProcessor(
        logger,
        max_audio_file_size_bytes=config.proxy_settings.max_audio_file_size_bytes,
        max_image_file_size_bytes=config.proxy_settings.max_image_file_size_bytes,
        max_text_file_size_bytes=config.proxy_settings.max_text_file_size_bytes,
    )
    app.state.attachment_processor = attachment_processor
    app.state.request_transformer = RequestTransformer(
        config,
        logger,
        attachment_processor,
    )
    app.state.response_processor = ResponseProcessor(
        logger,
        mode=config.proxy_settings.mode,
    )


async def close_runtime_services(app: FastAPI, *, logger) -> None:
    """Close app-scoped runtime services initialized during startup."""
    await close_app_gigachat_client(app, logger=logger)

    attachment_processor = getattr(app.state, "attachment_processor", None)
    if attachment_processor is not None:
        await attachment_processor.close()
