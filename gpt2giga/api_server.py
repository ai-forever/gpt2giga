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
from gpt2giga.routers import api_router, logs_router
from gpt2giga.routers import system_router


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
        )

    app.state.config = config
    app.state.logger = logger
    app.state.gigachat_client = GigaChat(**config.gigachat_settings.dict())

    attachment_processor = AttachmentProcessor(
        app.state.gigachat_client, app.state.logger
    )
    app.state.request_transformer = RequestTransformer(
        config, app.state.logger, attachment_processor
    )
    app.state.response_processor = ResponseProcessor(app.state.logger)
    yield


def create_app(config=None) -> FastAPI:
    app = FastAPI(lifespan=lifespan, title="Gpt2Giga converter proxy")
    if config is None:
        config = load_config()

    app.state.config = config

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # /some_prefix/another_prefix/v1/... -> /v1/...
    # /api/v1/embeddings -> /v1/embeddings/
    app.add_middleware(
        PathNormalizationMiddleware,
        valid_roots=["v1", "chat", "models", "embeddings", "responses"],
    )
    app.add_middleware(RquidMiddleware)

    if config.proxy_settings.pass_token:
        app.add_middleware(PassTokenMiddleware)

    @app.get("/", include_in_schema=False)
    async def docs_redirect():
        return RedirectResponse(url="/docs")

    dependencies = (
        [Depends(verify_api_key)] if config.proxy_settings.enable_api_key_auth else []
    )
    app.include_router(api_router, dependencies=dependencies)
    app.include_router(api_router, prefix="/v1", tags=["V1"], dependencies=dependencies)
    app.include_router(system_router, dependencies=dependencies)
    app.include_router(logs_router)
    return app


def run():
    config = load_config()
    proxy_settings = config.proxy_settings
    logger = setup_logger(
        log_level=proxy_settings.log_level,
        log_file=proxy_settings.log_filename,
        max_bytes=proxy_settings.log_max_size,
    )

    app = create_app(config)
    app.state.logger = logger

    logger.info("Starting Gpt2Giga proxy server...")
    logger.info(f"Proxy settings: {proxy_settings}")
    logger.info(
        f"GigaChat settings: {config.gigachat_settings.dict(exclude={'password', 'credentials', 'access_token'})}"
    )
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
