"""Application lifespan management."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from gpt2giga.app.cli import load_config
from gpt2giga.app.wiring import close_runtime_services, wire_runtime_services
from gpt2giga.logger import setup_logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and tear down runtime services for the application."""
    config = getattr(app.state, "config", None)
    if config is None:
        config_loader = getattr(app.state, "config_loader", load_config)
        config = config_loader()

    logger = getattr(app.state, "logger", None)
    if logger is None:
        logger_factory = getattr(app.state, "logger_factory", setup_logger)
        logger = logger_factory(
            log_level=config.proxy_settings.log_level,
            log_file=config.proxy_settings.log_filename,
            max_bytes=config.proxy_settings.log_max_size,
            enable_redaction=config.proxy_settings.log_redact_sensitive,
        )

    app.state.config = config
    app.state.logger = logger

    wire_runtime_services(app, config=config, logger=logger)
    logger.info("Application startup complete")

    try:
        yield
    finally:
        logger.info("Application shutdown initiated")
        await close_runtime_services(app, logger=logger)
