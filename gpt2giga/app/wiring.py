"""Runtime service wiring for the FastAPI application."""

from fastapi import FastAPI
from gigachat import GigaChat

from gpt2giga.protocol import AttachmentProcessor, RequestTransformer, ResponseProcessor


def _resolve_gigachat_factory(app: FastAPI):
    """Resolve the configured GigaChat client factory for this app instance."""
    factory_getter = getattr(app.state, "gigachat_factory_getter", None)
    if callable(factory_getter):
        return factory_getter()
    return getattr(app.state, "gigachat_factory", GigaChat)


def wire_runtime_services(app: FastAPI, *, config, logger) -> None:
    """Initialize app-scoped runtime services on ``app.state``."""
    gigachat_factory = _resolve_gigachat_factory(app)

    app.state.gigachat_client = gigachat_factory(
        **config.gigachat_settings.model_dump()
    )

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
    gigachat_client = getattr(app.state, "gigachat_client", None)
    if gigachat_client is not None:
        try:
            await gigachat_client.aclose()
            logger.info("GigaChat client closed")
        except Exception as exc:
            logger.warning(f"Error closing GigaChat client: {exc}")

    attachment_processor = getattr(app.state, "attachment_processor", None)
    if attachment_processor is not None:
        await attachment_processor.close()
