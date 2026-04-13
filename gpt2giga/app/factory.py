"""FastAPI application factory and HTTP wiring."""

from fastapi import Depends, FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import RedirectResponse

from gpt2giga.api.admin import admin_api_router, admin_router, legacy_logs_router
from gpt2giga.api.dependencies.auth import build_api_key_verifier
from gpt2giga.api.dependencies.governance import build_governance_verifier
from gpt2giga.api.gemini.request import GeminiAPIError
from gpt2giga.api.gemini.response import gemini_error_response
from gpt2giga.api.middleware.pass_token import PassTokenMiddleware
from gpt2giga.api.middleware.observability import ObservabilityMiddleware
from gpt2giga.api.middleware.path_normalizer import PathNormalizationMiddleware
from gpt2giga.api.middleware.request_validation import RequestValidationMiddleware
from gpt2giga.api.middleware.rquid_context import RquidMiddleware
from gpt2giga.api.system import metrics_router, system_router
from gpt2giga.api.tags import OPENAPI_TAGS
from gpt2giga.api.translate import router as translate_router
from gpt2giga.app.cli import load_config
from gpt2giga.app.dependencies import ensure_runtime_dependencies
from gpt2giga.app.lifespan import lifespan
from gpt2giga.core.app_meta import get_app_version
from gpt2giga.providers import iter_enabled_provider_descriptors


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
            "upload",
            "v1",
            "v1beta",
            "chat",
            "models",
            "embeddings",
            "responses",
            "messages",
            "translate",
            "model",
            "files",
            "batches",
            "admin",
            "metrics",
        ],
    )
    app.add_middleware(RquidMiddleware)
    app.add_middleware(
        RequestValidationMiddleware,
        max_body_bytes=config.proxy_settings.max_request_body_bytes,
    )

    if config.proxy_settings.pass_token:
        app.add_middleware(PassTokenMiddleware)

    # Keep observability outermost so it sees the final status of the whole stack.
    app.add_middleware(ObservabilityMiddleware)


def _register_root_redirect(app: FastAPI, *, is_prod_mode: bool) -> None:
    """Register the root redirect or health-like response."""

    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    async def docs_redirect():
        if is_prod_mode:
            return {"status": "ok", "mode": "PROD"}
        return RedirectResponse(url="/docs")


def _register_routes(app: FastAPI, *, auth_required: bool, is_prod_mode: bool) -> None:
    """Mount all API routers with the current auth policy."""
    config = app.state.config
    api_dependencies = (
        [Depends(build_api_key_verifier(allow_scoped_keys=False))]
        if auth_required
        else []
    )

    for descriptor in iter_enabled_provider_descriptors(
        config.proxy_settings.enabled_providers
    ):
        for mount in descriptor.mounts:
            auth_dependency = build_api_key_verifier(
                provider_name=descriptor.name,
                gemini_style=mount.auth_policy == "gemini",
                allow_scoped_keys=True,
            )
            governance_dependency = build_governance_verifier(
                provider_name=descriptor.name,
                gemini_style=mount.auth_policy == "gemini",
            )
            provider_dependencies = []
            if auth_required:
                provider_dependencies.append(Depends(auth_dependency))
            provider_dependencies.append(Depends(governance_dependency))
            include_kwargs = {
                "dependencies": provider_dependencies,
            }
            if mount.prefix:
                include_kwargs["prefix"] = mount.prefix
            if mount.tags:
                include_kwargs["tags"] = list(mount.tags)
            app.include_router(
                mount.router_factory(),
                **include_kwargs,
            )

    app.include_router(system_router)
    app.include_router(translate_router, dependencies=api_dependencies)
    app.include_router(translate_router, prefix="/v1", dependencies=api_dependencies)
    app.include_router(metrics_router, dependencies=api_dependencies)
    app.include_router(admin_api_router, dependencies=api_dependencies)
    app.include_router(admin_router, dependencies=api_dependencies)

    if not is_prod_mode:
        app.include_router(legacy_logs_router, dependencies=api_dependencies)


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
        openapi_tags=OPENAPI_TAGS,
        redirect_slashes=False,
        docs_url=None if is_prod_mode else "/docs",
        redoc_url=None if is_prod_mode else "/redoc",
        openapi_url=None if is_prod_mode else "/openapi.json",
    )

    ensure_runtime_dependencies(app.state, config=config)
    app.state.config_loader = config_loader
    if logger_factory is not None:
        app.state.logger_factory = logger_factory

    _register_exception_handlers(app)
    _register_middlewares(app, config)
    _register_root_redirect(app, is_prod_mode=is_prod_mode)
    _register_routes(app, auth_required=auth_required, is_prod_mode=is_prod_mode)
    return app
