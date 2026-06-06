"""FastAPI application factory."""

from fastapi import Depends, FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import RedirectResponse

from gpt2giga.app.lifecycle import lifespan
from gpt2giga.app.settings import (
    build_cors_settings,
    is_auth_required,
    is_prod_mode,
    load_app_config,
    validate_app_config,
)
from gpt2giga.api.anthropic import router as anthropic_router
from gpt2giga.api.openai import router as openai_router
from gpt2giga.auth import verify_api_key
from gpt2giga.common.app_meta import get_app_version
from gpt2giga.middlewares.pass_token import PassTokenMiddleware
from gpt2giga.middlewares.path_normalizer import PathNormalizationMiddleware
from gpt2giga.middlewares.request_validation import RequestValidationMiddleware
from gpt2giga.middlewares.rquid_context import RquidMiddleware
from gpt2giga.models.config import ProxyConfig
from gpt2giga.routers.litellm import router as litellm_router
from gpt2giga.routers.logs_router import logs_api_router, logs_router
from gpt2giga.routers.system_router import system_router
from gpt2giga.sinks.logs.factory import create_traffic_log_sink
from gpt2giga.sinks.observability.factory import create_observability_sink


def create_app(config: ProxyConfig | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    config = load_app_config(config)
    validate_app_config(config)

    prod_mode = is_prod_mode(config)
    auth_required = is_auth_required(config)
    cors_settings = build_cors_settings(config)

    app = FastAPI(
        lifespan=lifespan,
        title="Gpt2Giga converter proxy",
        version=get_app_version(),
        redirect_slashes=False,
        docs_url=None if prod_mode else "/docs",
        redoc_url=None if prod_mode else "/redoc",
        openapi_url=None if prod_mode else "/openapi.json",
    )
    app.state.config = config
    app.state.traffic_log_sink = create_traffic_log_sink(config.proxy_settings)
    app.state.observability_sink = create_observability_sink(config.proxy_settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_settings.allow_origins,
        allow_credentials=cors_settings.allow_credentials,
        allow_methods=cors_settings.allow_methods,
        allow_headers=cors_settings.allow_headers,
    )
    # /some_prefix/another_prefix/v1/... -> /v1/...
    # /api/v1/embeddings -> /v1/embeddings/
    app.add_middleware(
        PathNormalizationMiddleware,
        valid_roots=[
            "v1",
            "chat",
            "models",
            "embeddings",
            "responses",
            "messages",
            "model",
            "files",
            "batches",
        ],
    )
    app.add_middleware(RquidMiddleware)
    app.add_middleware(
        RequestValidationMiddleware,
        max_body_bytes=config.proxy_settings.max_request_body_bytes,
    )

    if config.proxy_settings.pass_token:
        app.add_middleware(PassTokenMiddleware)

    @app.get("/", include_in_schema=False)
    async def docs_redirect():
        if prod_mode:
            return {"status": "ok", "mode": "PROD"}
        return RedirectResponse(url="/docs")

    api_dependencies = [Depends(verify_api_key)] if auth_required else []
    app.include_router(openai_router, dependencies=api_dependencies)
    app.include_router(
        openai_router,
        prefix="/v1",
        tags=["V1"],
        dependencies=api_dependencies,
    )
    app.include_router(
        anthropic_router,
        prefix="/v1",
        tags=["V1 Anthropic"],
        dependencies=api_dependencies,
    )
    app.include_router(anthropic_router, dependencies=api_dependencies)
    app.include_router(
        litellm_router,
        prefix="/v1",
        tags=["V1 LiteLLM"],
        dependencies=api_dependencies,
    )
    app.include_router(litellm_router, dependencies=api_dependencies)
    app.include_router(system_router)
    if not prod_mode:
        app.include_router(logs_api_router, dependencies=api_dependencies)
        app.include_router(logs_router, dependencies=api_dependencies)
    return app
