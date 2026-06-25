"""Application lifecycle setup."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from gpt2giga.app.settings import load_app_config, setup_app_logger
from gpt2giga.common.model_concurrency import ModelConcurrencyLimiter
from gpt2giga.models.lar1 import LAR1Settings
from gpt2giga.protocol import AttachmentProcessor, RequestTransformer, ResponseProcessor
from gpt2giga.protocols.gemini import GeminiProtocolAdapter
from gpt2giga.protocols.openai import OpenAIProtocolAdapter
from gpt2giga.providers.gigachat.client import (
    close_gigachat_client,
    create_gigachat_client,
)
from gpt2giga.sinks.logs.factory import create_traffic_log_sink, flush_traffic_log_sink
from gpt2giga.sinks.logs.query import (
    close_traffic_log_query_store,
    create_traffic_log_query_store,
)
from gpt2giga.sinks.logs.retention import (
    start_traffic_log_retention_task,
    stop_traffic_log_retention_task,
)
from gpt2giga.sinks.metrics.factory import create_metrics_sink, flush_metrics_sink
from gpt2giga.sinks.observability.factory import (
    create_observability_sink,
    flush_observability_sink,
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
    app.state.lar1_settings = LAR1Settings()
    if not hasattr(app.state, "openai_protocol_adapter"):
        app.state.openai_protocol_adapter = OpenAIProtocolAdapter()
    if not hasattr(app.state, "gemini_protocol_adapter"):
        app.state.gemini_protocol_adapter = GeminiProtocolAdapter()
    if not hasattr(app.state, "traffic_log_sink"):
        app.state.traffic_log_sink = create_traffic_log_sink(
            config.proxy_settings, logger=logger
        )
    if not hasattr(app.state, "traffic_log_query_store"):
        app.state.traffic_log_query_store = create_traffic_log_query_store(
            config.proxy_settings, logger=logger
        )
    if not hasattr(app.state, "observability_sink"):
        app.state.observability_sink = create_observability_sink(
            config.proxy_settings, logger=logger
        )
    if not hasattr(app.state, "metrics_sink"):
        app.state.metrics_sink = create_metrics_sink(config.proxy_settings)
    app.state.traffic_log_retention_task = start_traffic_log_retention_task(
        config.proxy_settings,
        app.state.traffic_log_query_store,
        logger=logger,
    )
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
    await flush_metrics_sink(getattr(app.state, "metrics_sink", None), logger=logger)
    await flush_observability_sink(
        getattr(app.state, "observability_sink", None), logger=logger
    )
    await flush_traffic_log_sink(
        getattr(app.state, "traffic_log_sink", None), logger=logger
    )
    await stop_traffic_log_retention_task(
        getattr(app.state, "traffic_log_retention_task", None), logger=logger
    )
    await close_traffic_log_query_store(
        getattr(app.state, "traffic_log_query_store", None), logger=logger
    )
    await close_gigachat_client(getattr(app.state, "gigachat_client", None), logger)
    await attachment_processor.close()
