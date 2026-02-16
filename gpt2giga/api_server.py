import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Depends
from gigachat import GigaChat
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import RedirectResponse

from gpt2giga.auth import verify_api_key
from gpt2giga.cli import load_config
from gpt2giga.logger import setup_logger
from gpt2giga.middlewares.pass_token import PassTokenMiddleware
from gpt2giga.middlewares.path_normalizer import PathNormalizationMiddleware
from gpt2giga.middlewares.rquid_context import RquidMiddleware
from gpt2giga.protocol import AttachmentProcessor, RequestTransformer, ResponseProcessor
from gpt2giga.routers import anthropic_router, api_router, logs_api_router, logs_router
from gpt2giga.routers import system_router
from gpt2giga.utils import _get_app_version, _check_port_available


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = getattr(app.state, "config", None)
    logger = getattr(app.state, "logger", None)

    if not config:
        from gpt2giga.cli import load_config

        config = load_config()
    if not logger:
        from gpt2giga.logger import setup_logger

        logger = setup_logger(
            log_level=config.proxy_settings.log_level,
            log_file=config.proxy_settings.log_filename,
            max_bytes=config.proxy_settings.log_max_size,
            enable_redaction=config.proxy_settings.log_redact_sensitive,
        )

    app.state.config = config
    app.state.logger = logger
    app.state.gigachat_client = GigaChat(**config.gigachat_settings.model_dump())

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
        app.state.logger, mode=config.proxy_settings.mode
    )

    logger.info("Application startup complete")
    yield

    logger.info("Application shutdown initiated")
    gigachat_client = getattr(app.state, "gigachat_client", None)
    if gigachat_client:
        try:
            await gigachat_client.aclose()
            logger.info("GigaChat client closed")
        except Exception as exc:
            logger.warning(f"Error closing GigaChat client: {exc}")
    await attachment_processor.close()


def create_app(config=None) -> FastAPI:
    if config is None:
        config = load_config()
    is_prod_mode = config.proxy_settings.mode == "PROD"
    auth_required = config.proxy_settings.enable_api_key_auth or is_prod_mode
    if auth_required and not config.proxy_settings.api_key:
        raise RuntimeError(
            "API key must be configured when auth is enabled or MODE=PROD "
            "(set GPT2GIGA_API_KEY / --proxy.api-key)."
        )

    allow_origins = config.proxy_settings.cors_allow_origins
    allow_methods = config.proxy_settings.cors_allow_methods
    allow_headers = config.proxy_settings.cors_allow_headers
    allow_credentials = True
    if is_prod_mode:
        # In PROD, deny wildcard CORS and disable credentials to reduce browser abuse.
        allow_origins = [origin for origin in allow_origins if origin != "*"]
        allow_methods = [method for method in allow_methods if method != "*"]
        allow_headers = [header for header in allow_headers if header != "*"]
        if not allow_methods:
            allow_methods = ["GET", "POST", "OPTIONS"]
        if not allow_headers:
            allow_headers = ["authorization", "content-type", "x-api-key"]
        allow_credentials = False

    app = FastAPI(
        lifespan=lifespan,
        title="Gpt2Giga converter proxy",
        version=_get_app_version(),
        redirect_slashes=False,
        docs_url=None if is_prod_mode else "/docs",
        redoc_url=None if is_prod_mode else "/redoc",
        openapi_url=None if is_prod_mode else "/openapi.json",
    )

    app.state.config = config

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=allow_credentials,
        allow_methods=allow_methods,
        allow_headers=allow_headers,
    )
    # /some_prefix/another_prefix/v1/... -> /v1/...
    # /api/v1/embeddings -> /v1/embeddings/
    app.add_middleware(
        PathNormalizationMiddleware,
        valid_roots=["v1", "chat", "models", "embeddings", "responses", "messages"],
    )
    app.add_middleware(RquidMiddleware)

    if config.proxy_settings.pass_token:
        app.add_middleware(PassTokenMiddleware)

    @app.get("/", include_in_schema=False)
    async def docs_redirect():
        if is_prod_mode:
            return {"status": "ok", "mode": "PROD"}
        return RedirectResponse(url="/docs")

    dependencies = [Depends(verify_api_key)] if auth_required else []
    app.include_router(api_router, dependencies=dependencies)
    app.include_router(api_router, prefix="/v1", tags=["V1"], dependencies=dependencies)
    app.include_router(
        anthropic_router, prefix="/v1", tags=["V1 Anthropic"], dependencies=dependencies
    )
    app.include_router(anthropic_router, dependencies=dependencies)
    app.include_router(system_router, dependencies=dependencies)
    if not is_prod_mode:
        app.include_router(logs_api_router, dependencies=dependencies)
        app.include_router(logs_router, dependencies=dependencies)
    return app


def run():
    config = load_config()
    proxy_settings = config.proxy_settings
    logger = setup_logger(
        log_level=proxy_settings.log_level,
        log_file=proxy_settings.log_filename,
        max_bytes=proxy_settings.log_max_size,
        enable_redaction=proxy_settings.log_redact_sensitive,
    )

    app = create_app(config)
    app.state.logger = logger

    if proxy_settings.mode == "PROD" and proxy_settings.log_level == "DEBUG":
        logger.warning(
            "DEBUG log level in PROD mode may expose sensitive data. "
            "Consider using INFO or higher."
        )

    logger.info(f"Starting Gpt2Giga proxy server, version: {_get_app_version()}")
    logger.info(f"Proxy settings: {proxy_settings.model_dump(exclude={'api_key'})}")
    logger.info(
        f"GigaChat settings: {config.gigachat_settings.model_dump(exclude={'password', 'credentials', 'access_token', 'key_file_password'})}"
    )

    if not _check_port_available(proxy_settings.host, proxy_settings.port):
        logger.error(
            f"Port {proxy_settings.port} is already in use on {proxy_settings.host}. "
            f"Possible zombie process — try: fuser -k {proxy_settings.port}/tcp"
        )
        sys.exit(1)

    uvicorn.run(
        app,
        host=proxy_settings.host,
        port=proxy_settings.port,
        log_level=proxy_settings.log_level.lower(),
        ssl_keyfile=proxy_settings.https_key_file if proxy_settings.use_https else None,
        ssl_certfile=(
            proxy_settings.https_cert_file if proxy_settings.use_https else None
        ),
    )


if __name__ == "__main__":
    run()
