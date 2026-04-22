"""FastAPI application factory and HTTP wiring."""

from collections.abc import Sequence
from dataclasses import dataclass
import os
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.params import Depends as DependsMarker
from starlette.datastructures import Headers
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import FileResponse, RedirectResponse
from starlette.staticfiles import NotModifiedResponse, StaticFiles

from gpt2giga.api.admin import admin_api_router, admin_router
from gpt2giga.api.admin.access import (
    ADMIN_AUTH_COOKIE_NAME,
    build_admin_access_verifier,
)
from gpt2giga.api.batches_validation import router as batches_validation_router
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
from gpt2giga.api.tags import build_openapi_tags
from gpt2giga.api.translate import router as translate_router
from gpt2giga.app.admin_ui import get_admin_ui_resources, is_admin_ui_enabled
from gpt2giga.app.cli import load_config
from gpt2giga.app.dependencies import ensure_runtime_dependencies
from gpt2giga.app.lifespan import lifespan
from gpt2giga.core.app_meta import get_app_version
from gpt2giga.core.config.control_plane import (
    load_bootstrap_token,
    requires_admin_bootstrap,
)
from gpt2giga.providers import iter_enabled_provider_descriptors

_ADMIN_ASSETS_CACHE_CONTROL = "public, max-age=300"


@dataclass(frozen=True, slots=True)
class _AppCreationFlags:
    """Derived create_app flags that drive security and UI wiring."""

    is_prod_mode: bool
    auth_required: bool
    bootstrap_required: bool
    admin_ui_enabled: bool


class AdminStaticFiles(StaticFiles):
    """Serve admin UI assets with an explicit short-lived cache policy."""

    def file_response(
        self,
        full_path: os.PathLike[str] | str,
        stat_result: os.stat_result,
        scope,
        status_code: int = 200,
    ):
        request_headers = Headers(scope=scope)
        response = FileResponse(
            full_path,
            status_code=status_code,
            stat_result=stat_result,
            headers={"Cache-Control": _ADMIN_ASSETS_CACHE_CONTROL},
        )
        if self.is_not_modified(response.headers, request_headers):
            return NotModifiedResponse(response.headers)
        return response


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


def _mount_admin_assets(app: FastAPI, *, assets_dir: Path | None) -> None:
    """Mount static assets used by the admin console."""
    if assets_dir is None:
        return
    app.mount(
        "/admin/assets",
        AdminStaticFiles(directory=assets_dir),
        name="admin-assets",
    )


def _register_favicon_route(app: FastAPI, *, favicon_path: Path | None) -> None:
    """Expose the packaged favicon when UI assets are available."""
    if favicon_path is None:
        return

    @app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
    async def favicon() -> FileResponse:
        return FileResponse(
            favicon_path,
            media_type="image/x-icon",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
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


def _register_root_redirect(
    app: FastAPI,
    *,
    config,
    is_prod_mode: bool,
    ui_enabled: bool,
) -> None:
    """Register the root redirect or health-like response."""

    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    async def root_redirect():
        if is_prod_mode:
            return {"status": "ok", "mode": "PROD"}
        target = "/admin" if ui_enabled else app.docs_url
        if target is None:
            return {"status": "ok", "mode": config.proxy_settings.mode}
        if config.proxy_settings.enable_api_key_auth and config.proxy_settings.api_key:
            if target == "/admin":
                response = RedirectResponse(url=target)
                response.set_cookie(
                    ADMIN_AUTH_COOKIE_NAME,
                    config.proxy_settings.api_key,
                    httponly=True,
                    path="/",
                    samesite="lax",
                )
                return response
        return RedirectResponse(url=target)


def _register_routes(
    app: FastAPI,
    *,
    auth_required: bool,
    ui_enabled: bool,
) -> None:
    """Mount all API routers with the current auth policy."""
    api_dependencies = (
        [Depends(build_api_key_verifier(allow_scoped_keys=False))]
        if auth_required
        else []
    )
    admin_dependencies = (
        [Depends(build_admin_access_verifier())] if auth_required else []
    )

    _register_provider_routes(app, auth_required=auth_required)
    _register_shared_routes(
        app,
        api_dependencies=api_dependencies,
        admin_dependencies=admin_dependencies,
        ui_enabled=ui_enabled,
    )


def _register_provider_routes(app: FastAPI, *, auth_required: bool) -> None:
    """Register provider-owned transport routers with their auth policy."""
    config = app.state.config
    for descriptor in iter_enabled_provider_descriptors(
        config.proxy_settings.enabled_providers
    ):
        for mount in descriptor.mounts:
            provider_dependencies = _build_provider_dependencies(
                descriptor_name=descriptor.name,
                auth_policy=mount.auth_policy,
                auth_required=auth_required,
            )
            _include_provider_router(
                app,
                router=mount.router_factory(),
                prefix=mount.prefix,
                tags=mount.tags,
                dependencies=provider_dependencies,
            )


def _build_provider_dependencies(
    *,
    descriptor_name: str,
    auth_policy: str | None,
    auth_required: bool,
) -> list[DependsMarker]:
    """Build the ordered dependency stack for a provider mount."""
    gemini_style = auth_policy == "gemini"
    dependencies: list[DependsMarker] = []
    if auth_required:
        dependencies.append(
            Depends(
                build_api_key_verifier(
                    provider_name=descriptor_name,
                    gemini_style=gemini_style,
                    allow_scoped_keys=True,
                )
            )
        )
    dependencies.append(
        Depends(
            build_governance_verifier(
                provider_name=descriptor_name,
                gemini_style=gemini_style,
            )
        )
    )
    return dependencies


def _include_provider_router(
    app: FastAPI,
    *,
    router,
    prefix: str | None,
    tags: tuple[str, ...] | list[str] | None,
    dependencies: Sequence[DependsMarker],
) -> None:
    """Include a provider router without repeating optional prefix/tag branches."""
    if prefix and tags:
        app.include_router(
            router,
            prefix=prefix,
            tags=list(tags),
            dependencies=dependencies,
        )
    elif prefix:
        app.include_router(
            router,
            prefix=prefix,
            dependencies=dependencies,
        )
    elif tags:
        app.include_router(
            router,
            tags=list(tags),
            dependencies=dependencies,
        )
    else:
        app.include_router(router, dependencies=dependencies)


def _register_shared_routes(
    app: FastAPI,
    *,
    api_dependencies: Sequence[DependsMarker],
    admin_dependencies: Sequence[DependsMarker],
    ui_enabled: bool,
) -> None:
    """Register non-provider routers that share the global auth policy."""
    app.include_router(system_router)
    app.include_router(batches_validation_router, dependencies=api_dependencies)
    app.include_router(
        batches_validation_router,
        prefix="/v1",
        dependencies=api_dependencies,
    )
    app.include_router(translate_router, dependencies=api_dependencies)
    app.include_router(translate_router, prefix="/v1", dependencies=api_dependencies)
    app.include_router(metrics_router, dependencies=api_dependencies)
    app.include_router(admin_api_router, dependencies=admin_dependencies)
    if ui_enabled:
        app.include_router(admin_router, dependencies=admin_dependencies)


def _resolve_app_creation_flags(config) -> _AppCreationFlags:
    """Resolve the mode-derived flags that control create_app wiring."""
    is_prod_mode = config.proxy_settings.mode == "PROD"
    return _AppCreationFlags(
        is_prod_mode=is_prod_mode,
        auth_required=config.proxy_settings.enable_api_key_auth or is_prod_mode,
        bootstrap_required=requires_admin_bootstrap(config),
        admin_ui_enabled=is_admin_ui_enabled(config),
    )


def _validate_app_creation_flags(
    config,
    *,
    auth_required: bool,
    bootstrap_required: bool,
) -> None:
    """Validate API-key/bootstrap requirements before app creation."""
    if auth_required and not config.proxy_settings.api_key and not bootstrap_required:
        raise RuntimeError(
            "API key must be configured when auth is enabled or MODE=PROD "
            "(set GPT2GIGA_API_KEY / --proxy.api-key)."
        )


def _build_fastapi_app(
    config,
    *,
    is_prod_mode: bool,
    app_version_getter,
) -> FastAPI:
    """Construct the FastAPI app object before runtime state wiring."""
    return FastAPI(
        lifespan=lifespan,
        title="Gpt2Giga converter proxy",
        version=app_version_getter(),
        openapi_tags=build_openapi_tags(config.proxy_settings.enabled_providers),
        redirect_slashes=False,
        docs_url=None if is_prod_mode else "/docs",
        redoc_url=None if is_prod_mode else "/redoc",
        openapi_url=None if is_prod_mode else "/openapi.json",
    )


def _initialize_app_state(
    app: FastAPI,
    *,
    config,
    config_loader,
    logger_factory,
    admin_ui_enabled: bool,
    admin_ui_resources,
) -> None:
    """Initialize app.state fields consumed by lifespan and admin routes."""
    ensure_runtime_dependencies(app.state, config=config)
    app.state.config_loader = config_loader
    app.state.admin_ui_enabled = admin_ui_enabled
    app.state.admin_ui_installed = admin_ui_resources is not None
    if logger_factory is not None:
        app.state.logger_factory = logger_factory


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

    flags = _resolve_app_creation_flags(config)
    admin_ui_resources = get_admin_ui_resources()

    _validate_app_creation_flags(
        config,
        auth_required=flags.auth_required,
        bootstrap_required=flags.bootstrap_required,
    )
    if flags.bootstrap_required:
        load_bootstrap_token(create=True)

    app = _build_fastapi_app(
        config,
        is_prod_mode=flags.is_prod_mode,
        app_version_getter=app_version_getter,
    )

    _initialize_app_state(
        app,
        config=config,
        config_loader=config_loader,
        logger_factory=logger_factory,
        admin_ui_enabled=flags.admin_ui_enabled,
        admin_ui_resources=admin_ui_resources,
    )

    admin_static_dir = (
        admin_ui_resources.static_dir
        if flags.admin_ui_enabled and admin_ui_resources is not None
        else None
    )
    _mount_admin_assets(app, assets_dir=admin_static_dir)
    _register_favicon_route(
        app,
        favicon_path=admin_ui_resources.favicon_ico_path
        if admin_ui_resources
        else None,
    )
    _register_exception_handlers(app)
    _register_middlewares(app, config)
    _register_root_redirect(
        app,
        config=config,
        is_prod_mode=flags.is_prod_mode,
        ui_enabled=flags.admin_ui_enabled,
    )
    _register_routes(
        app,
        auth_required=flags.auth_required,
        ui_enabled=flags.admin_ui_enabled,
    )
    return app
