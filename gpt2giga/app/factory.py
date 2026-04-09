"""FastAPI application factory and HTTP wiring."""

from fastapi import Depends, FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import RedirectResponse

from gpt2giga.api.anthropic import router as anthropic_router
from gpt2giga.api.dependencies.auth import verify_api_key, verify_api_key_gemini
from gpt2giga.api.gemini import router as gemini_router
from gpt2giga.api.litellm import router as litellm_router
from gpt2giga.api.middleware.pass_token import PassTokenMiddleware
from gpt2giga.api.middleware.path_normalizer import PathNormalizationMiddleware
from gpt2giga.api.middleware.request_validation import RequestValidationMiddleware
from gpt2giga.api.middleware.rquid_context import RquidMiddleware
from gpt2giga.api.openai import router as openai_router
from gpt2giga.api.system import logs_api_router, logs_router, system_router
from gpt2giga.app.cli import load_config
from gpt2giga.app.lifespan import lifespan
from gpt2giga.core.app_meta import get_app_version
from gpt2giga.protocol.gemini.response import GeminiAPIError, gemini_error_response


def _build_cors_options(config) -> tuple[list[str], list[str], list[str], bool]:
    """Build CORS configuration, hardening it automatically in PROD mode."""
    is_prod_mode = config.proxy_settings.mode == "PROD"
    allow_origins = config.proxy_settings.cors_allow_origins
    allow_methods = config.proxy_settings.cors_allow_methods
    allow_headers = config.proxy_settings.cors_allow_headers
    allow_credentials = True

    if is_prod_mode:
        allow_origins = [origin for origin in allow_origins if origin != "*"]
        allow_methods = [method for method in allow_methods if method != "*"]
        allow_headers = [header for header in allow_headers if header != "*"]
        if not allow_methods:
            allow_methods = ["GET", "POST", "OPTIONS"]
        if not allow_headers:
            allow_headers = ["authorization", "content-type", "x-api-key"]
        allow_credentials = False

    return allow_origins, allow_methods, allow_headers, allow_credentials


def _register_exception_handlers(app: FastAPI) -> None:
    """Register application-specific exception handlers."""

    @app.exception_handler(GeminiAPIError)
    async def _handle_gemini_api_error(_, exc: GeminiAPIError):
        return gemini_error_response(
            status_code=exc.status_code,
            status=exc.status,
            message=exc.message,
            details=exc.details,
        )


def _register_middlewares(app: FastAPI, config) -> None:
    """Register application middlewares in the required order."""
    allow_origins, allow_methods, allow_headers, allow_credentials = (
        _build_cors_options(config)
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=allow_credentials,
        allow_methods=allow_methods,
        allow_headers=allow_headers,
    )
    app.add_middleware(
        PathNormalizationMiddleware,
        valid_roots=[
            "v1",
            "v1beta",
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


def _register_root_redirect(app: FastAPI, *, is_prod_mode: bool) -> None:
    """Register the root redirect or health-like response."""

    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    async def docs_redirect():
        if is_prod_mode:
            return {"status": "ok", "mode": "PROD"}
        return RedirectResponse(url="/docs")


def _register_routes(app: FastAPI, *, auth_required: bool, is_prod_mode: bool) -> None:
    """Mount all API routers with the current auth policy."""
    api_dependencies = [Depends(verify_api_key)] if auth_required else []
    gemini_dependencies = [Depends(verify_api_key_gemini)] if auth_required else []

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
    app.include_router(
        gemini_router,
        prefix="/v1beta",
        tags=["V1beta Gemini"],
        dependencies=gemini_dependencies,
    )
    app.include_router(system_router)

    if not is_prod_mode:
        app.include_router(logs_api_router, dependencies=api_dependencies)
        app.include_router(logs_router, dependencies=api_dependencies)


def create_app(
    config=None,
    *,
    config_loader=load_config,
    logger_factory=None,
    app_version_getter=get_app_version,
) -> FastAPI:
    """Create and configure the FastAPI application."""
    if config is None:
        config = config_loader()

    is_prod_mode = config.proxy_settings.mode == "PROD"
    auth_required = config.proxy_settings.enable_api_key_auth or is_prod_mode

    if auth_required and not config.proxy_settings.api_key:
        raise RuntimeError(
            "API key must be configured when auth is enabled or MODE=PROD "
            "(set GPT2GIGA_API_KEY / --proxy.api-key)."
        )

    app = FastAPI(
        lifespan=lifespan,
        title="Gpt2Giga converter proxy",
        version=app_version_getter(),
        redirect_slashes=False,
        docs_url=None if is_prod_mode else "/docs",
        redoc_url=None if is_prod_mode else "/redoc",
        openapi_url=None if is_prod_mode else "/openapi.json",
    )

    app.state.config = config
    app.state.config_loader = config_loader
    if logger_factory is not None:
        app.state.logger_factory = logger_factory

    _register_exception_handlers(app)
    _register_middlewares(app, config)
    _register_root_redirect(app, is_prod_mode=is_prod_mode)
    _register_routes(app, auth_required=auth_required, is_prod_mode=is_prod_mode)
    return app
