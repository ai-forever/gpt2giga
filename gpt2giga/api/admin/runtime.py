"""Runtime and capability endpoints for the admin layer."""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.routing import APIRoute
from starlette.requests import Request

from gpt2giga.api.admin.logs import verify_logs_ip_allowlist
from gpt2giga.api.system.metrics import build_metrics_response
from gpt2giga.app.observability import (
    get_recent_error_feed_from_state,
    get_recent_request_feed_from_state,
    query_request_events,
)
from gpt2giga.app.dependencies import (
    get_config_from_state,
    get_runtime_observability,
    get_runtime_providers,
    get_runtime_services,
    get_runtime_stores,
)
from gpt2giga.core.app_meta import get_app_version
from gpt2giga.core.errors import exceptions_handler
from gpt2giga.providers import list_provider_descriptors

admin_runtime_api_router = APIRouter(tags=["Admin"])


def _normalize_optional_text(value: str | None) -> str | None:
    """Normalize empty query-string values into ``None``."""
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _collect_event_filter_options(
    events: list[dict[str, object]],
) -> dict[str, list[object]]:
    """Collect available filter values from recent event payloads."""
    options: dict[str, list[object]] = {}
    for key in ("provider", "endpoint", "method", "status_code", "model", "error_type"):
        values = {
            event.get(key) for event in events if event.get(key) not in (None, "")
        }
        options[key] = sorted(values, key=lambda item: str(item))
    return options


def _build_config_summary(proxy: object) -> dict[str, dict[str, object]]:
    """Build grouped config sections for the admin UI."""
    return {
        "network": {
            "mode": proxy.mode,
            "bind": f"{proxy.host}:{proxy.port}",
            "https_enabled": proxy.use_https,
            "api_key_auth": proxy.enable_api_key_auth,
            "admin_enabled": proxy.mode != "PROD",
        },
        "providers": {
            "enabled_providers": list(proxy.enabled_providers),
            "gigachat_api_mode": proxy.gigachat_api_mode,
            "telemetry_enabled": proxy.enable_telemetry,
            "observability_sinks": list(proxy.observability_sinks),
            "runtime_store_backend": proxy.runtime_store_backend,
            "runtime_store_namespace": proxy.runtime_store_namespace,
        },
        "features": {
            "pass_model": proxy.pass_model,
            "pass_token": proxy.pass_token,
            "enable_reasoning": proxy.enable_reasoning,
            "enable_images": proxy.enable_images,
        },
        "limits": {
            "max_request_body_bytes": proxy.max_request_body_bytes,
            "max_audio_file_size_bytes": proxy.max_audio_file_size_bytes,
            "max_image_file_size_bytes": proxy.max_image_file_size_bytes,
            "max_text_file_size_bytes": proxy.max_text_file_size_bytes,
            "max_audio_image_total_size_bytes": proxy.max_audio_image_total_size_bytes,
            "recent_requests_max_items": proxy.recent_requests_max_items,
            "recent_errors_max_items": proxy.recent_errors_max_items,
        },
        "logging": {
            "log_level": proxy.log_level,
            "log_filename": proxy.log_filename,
            "log_max_size": proxy.log_max_size,
            "log_redact_sensitive": proxy.log_redact_sensitive,
            "logs_ip_allowlist_enabled": bool(proxy.logs_ip_allowlist),
        },
    }


def _build_capability_matrix(
    config: object, *, metrics_enabled: bool
) -> dict[str, object]:
    """Build a compact capability matrix for admin UI rendering."""
    enabled_providers = set(config.proxy_settings.enabled_providers)
    rows = [
        {
            "name": descriptor.name,
            "display_name": descriptor.display_name,
            "surface": "provider",
            "enabled": descriptor.name in enabled_providers,
            "capabilities": list(descriptor.capabilities),
            "routes": list(descriptor.routes),
            "route_count": len(descriptor.routes),
        }
        for descriptor in list_provider_descriptors()
    ]
    rows.extend(
        [
            {
                "name": "system",
                "display_name": "System",
                "surface": "system",
                "enabled": True,
                "capabilities": [
                    "health",
                    "ping",
                    *([] if not metrics_enabled else ["metrics"]),
                ],
                "routes": [
                    "/health",
                    "/ping",
                    *([] if not metrics_enabled else ["/metrics"]),
                ],
                "route_count": 2 + int(metrics_enabled),
            },
            {
                "name": "admin",
                "display_name": "Admin",
                "surface": "admin",
                "enabled": config.proxy_settings.mode != "PROD",
                "capabilities": [
                    "ui",
                    "version",
                    "config",
                    "runtime",
                    "routes",
                    "recent_requests",
                    "recent_errors",
                    *([] if not metrics_enabled else ["metrics"]),
                    "logs",
                    "logs_stream",
                ],
                "routes": [
                    "/admin",
                    "/admin/api/version",
                    "/admin/api/config",
                    "/admin/api/runtime",
                    "/admin/api/routes",
                    "/admin/api/capabilities",
                    "/admin/api/requests/recent",
                    "/admin/api/errors/recent",
                    *([] if not metrics_enabled else ["/admin/api/metrics"]),
                    "/admin/api/logs",
                    "/admin/api/logs/stream",
                ],
                "route_count": 10 + int(metrics_enabled),
            },
        ]
    )
    return {
        "columns": ["surface", "enabled", "capabilities", "route_count"],
        "rows": rows,
    }


def _collect_state_status(request: Request) -> dict[str, dict[str, bool | int | None]]:
    """Return a coarse runtime snapshot of typed app-state containers."""
    services = get_runtime_services(request.app.state)
    providers = get_runtime_providers(request.app.state)
    stores = get_runtime_stores(request.app.state)
    return {
        "services": {
            "chat": services.chat is not None,
            "responses": services.responses is not None,
            "embeddings": services.embeddings is not None,
            "models": services.models is not None,
            "files": services.files is not None,
            "batches": services.batches is not None,
        },
        "providers": {
            "gigachat_client": providers.gigachat_client is not None,
            "gigachat_factory": providers.gigachat_factory is not None,
            "request_transformer": providers.request_transformer is not None,
            "response_processor": providers.response_processor is not None,
            "chat_mapper": providers.chat_mapper is not None,
            "embeddings_mapper": providers.embeddings_mapper is not None,
            "models_mapper": providers.models_mapper is not None,
        },
        "stores": {
            "backend": stores.backend.name if stores.backend is not None else None,
            "files": len(stores.files),
            "batches": len(stores.batches),
            "responses": len(stores.responses),
            "recent_requests": len(
                get_recent_request_feed_from_state(request.app.state)
            ),
            "recent_errors": len(get_recent_error_feed_from_state(request.app.state)),
        },
    }


def _serialize_routes(request: Request) -> list[dict[str, object]]:
    """List mounted API routes for operator inspection."""
    route_entries: list[dict[str, object]] = []
    for route in request.app.routes:
        if not isinstance(route, APIRoute):
            continue
        methods = sorted(
            method for method in (route.methods or set()) if method != "HEAD"
        )
        route_entries.append(
            {
                "path": route.path,
                "methods": methods,
                "name": route.name,
                "tags": list(route.tags or []),
                "include_in_schema": route.include_in_schema,
            }
        )
    return sorted(route_entries, key=lambda entry: (str(entry["path"]), entry["name"]))


def _runtime_summary(request: Request) -> dict[str, object]:
    """Build a sanitized runtime summary for the admin API."""
    config = get_config_from_state(request.app.state)
    proxy = config.proxy_settings
    is_prod_mode = proxy.mode == "PROD"
    auth_required = proxy.enable_api_key_auth or is_prod_mode
    metrics_enabled = proxy.metrics_enabled
    return {
        "app_version": request.app.version or get_app_version(),
        "mode": proxy.mode,
        "auth_required": auth_required,
        "docs_enabled": request.app.docs_url is not None,
        "redoc_enabled": request.app.redoc_url is not None,
        "openapi_enabled": request.app.openapi_url is not None,
        "enabled_providers": list(proxy.enabled_providers),
        "gigachat_api_mode": proxy.gigachat_api_mode,
        "runtime_store_backend": proxy.runtime_store_backend,
        "runtime_store_namespace": proxy.runtime_store_namespace,
        "telemetry_enabled": proxy.enable_telemetry,
        "observability_sinks": list(proxy.observability_sinks),
        "metrics_enabled": metrics_enabled,
        "pass_model": proxy.pass_model,
        "pass_token": proxy.pass_token,
        "enable_reasoning": proxy.enable_reasoning,
        "enable_images": proxy.enable_images,
        "logs_ip_allowlist_enabled": bool(proxy.logs_ip_allowlist),
        "log_redact_sensitive": proxy.log_redact_sensitive,
        "admin_enabled": not is_prod_mode,
        "state": _collect_state_status(request),
    }


@admin_runtime_api_router.get("/admin/api/version")
@exceptions_handler
async def get_admin_version(request: Request):
    """Return application version metadata for admin tooling."""
    verify_logs_ip_allowlist(request)
    return {"version": request.app.version or get_app_version()}


@admin_runtime_api_router.get("/admin/api/config")
@exceptions_handler
async def get_admin_config(request: Request):
    """Return a sanitized config summary for admin tooling."""
    verify_logs_ip_allowlist(request)
    config = get_config_from_state(request.app.state)
    proxy = config.proxy_settings
    return {
        "mode": proxy.mode,
        "host": proxy.host,
        "port": proxy.port,
        "enabled_providers": list(proxy.enabled_providers),
        "gigachat_api_mode": proxy.gigachat_api_mode,
        "runtime_store_backend": proxy.runtime_store_backend,
        "runtime_store_namespace": proxy.runtime_store_namespace,
        "enable_telemetry": proxy.enable_telemetry,
        "observability_sinks": list(proxy.observability_sinks),
        "runtime_store_dsn_configured": proxy.runtime_store_dsn is not None,
        "recent_requests_max_items": proxy.recent_requests_max_items,
        "recent_errors_max_items": proxy.recent_errors_max_items,
        "max_request_body_bytes": proxy.max_request_body_bytes,
        "max_audio_file_size_bytes": proxy.max_audio_file_size_bytes,
        "max_image_file_size_bytes": proxy.max_image_file_size_bytes,
        "max_text_file_size_bytes": proxy.max_text_file_size_bytes,
        "max_audio_image_total_size_bytes": proxy.max_audio_image_total_size_bytes,
        "enable_api_key_auth": proxy.enable_api_key_auth,
        "pass_model": proxy.pass_model,
        "pass_token": proxy.pass_token,
        "enable_reasoning": proxy.enable_reasoning,
        "enable_images": proxy.enable_images,
        "log_level": proxy.log_level,
        "log_filename": proxy.log_filename,
        "log_max_size": proxy.log_max_size,
        "log_redact_sensitive": proxy.log_redact_sensitive,
        "logs_ip_allowlist_enabled": bool(proxy.logs_ip_allowlist),
        "cors_allow_origins": list(proxy.cors_allow_origins),
        "cors_allow_methods": list(proxy.cors_allow_methods),
        "cors_allow_headers": list(proxy.cors_allow_headers),
        "summary": _build_config_summary(proxy),
    }


@admin_runtime_api_router.get("/admin/api/runtime")
@exceptions_handler
async def get_admin_runtime(request: Request):
    """Return effective runtime status for the admin layer."""
    verify_logs_ip_allowlist(request)
    return _runtime_summary(request)


@admin_runtime_api_router.get("/admin/api/routes")
@exceptions_handler
async def get_admin_routes(request: Request):
    """Return mounted routes so operators can inspect active surface area."""
    verify_logs_ip_allowlist(request)
    return {"routes": _serialize_routes(request)}


@admin_runtime_api_router.get("/admin/api/capabilities")
@exceptions_handler
async def get_admin_capabilities(request: Request):
    """Return enabled provider groups and operator capabilities."""
    verify_logs_ip_allowlist(request)
    config = get_config_from_state(request.app.state)
    enabled_providers = set(config.proxy_settings.enabled_providers)
    metrics_enabled = config.proxy_settings.metrics_enabled
    capability_matrix = _build_capability_matrix(
        config, metrics_enabled=metrics_enabled
    )
    return {
        "backend": {
            "gigachat_api_mode": config.proxy_settings.gigachat_api_mode,
            "chat_backend_mode": config.proxy_settings.chat_backend_mode,
            "responses_backend_mode": config.proxy_settings.responses_backend_mode,
            "runtime_store_backend": config.proxy_settings.runtime_store_backend,
            "telemetry_enabled": config.proxy_settings.enable_telemetry,
            "observability_sinks": list(config.proxy_settings.observability_sinks),
        },
        "matrix": capability_matrix,
        "providers": {
            descriptor.name: {
                "enabled": descriptor.name in enabled_providers,
                "display_name": descriptor.display_name,
                "capabilities": list(descriptor.capabilities),
                "routes": list(descriptor.routes),
            }
            for descriptor in list_provider_descriptors()
        },
        "system": {
            "enabled": True,
            "capabilities": [
                "health",
                "ping",
                *([] if not metrics_enabled else ["metrics"]),
            ],
            "routes": [
                "/health",
                "/ping",
                *([] if not metrics_enabled else ["/metrics"]),
            ],
        },
        "admin": {
            "enabled": config.proxy_settings.mode != "PROD",
            "capabilities": [
                "ui",
                "version",
                "config",
                "runtime",
                "routes",
                "recent_requests",
                "recent_errors",
                *([] if not metrics_enabled else ["metrics"]),
                "logs",
                "logs_stream",
            ],
            "routes": [
                "/admin",
                "/admin/api/version",
                "/admin/api/config",
                "/admin/api/runtime",
                "/admin/api/routes",
                "/admin/api/capabilities",
                "/admin/api/requests/recent",
                "/admin/api/errors/recent",
                *([] if not metrics_enabled else ["/admin/api/metrics"]),
                "/admin/api/logs",
                "/admin/api/logs/stream",
            ],
            "legacy_routes": ["/logs", "/logs/stream", "/logs/html"],
        },
    }


def _recent_events_payload(
    request: Request,
    *,
    kind: str,
    limit: int,
    provider: str | None,
    endpoint: str | None,
    method: str | None,
    status_code: int | None,
    model: str | None,
    error_type: str | None,
) -> dict[str, object]:
    """Build a filtered recent-events payload for admin tooling."""
    feed = (
        get_recent_request_feed_from_state(request.app.state)
        if kind == "requests"
        else get_recent_error_feed_from_state(request.app.state)
    )
    recent_events = feed.recent(limit=limit)
    events = query_request_events(
        feed,
        limit=limit,
        provider=_normalize_optional_text(provider),
        endpoint=_normalize_optional_text(endpoint),
        method=_normalize_optional_text(method),
        status_code=status_code,
        model=_normalize_optional_text(model),
        error_type=_normalize_optional_text(error_type),
    )
    return {
        "events": events,
        "count": len(events),
        "kind": kind,
        "limit": limit,
        "filters": {
            "provider": _normalize_optional_text(provider),
            "endpoint": _normalize_optional_text(endpoint),
            "method": _normalize_optional_text(method),
            "status_code": status_code,
            "model": _normalize_optional_text(model),
            "error_type": _normalize_optional_text(error_type),
        },
        "available_filters": _collect_event_filter_options(recent_events),
    }


@admin_runtime_api_router.get("/admin/api/metrics")
@exceptions_handler
async def get_admin_metrics(request: Request):
    """Expose Prometheus metrics through the admin surface."""
    verify_logs_ip_allowlist(request)
    get_runtime_observability(request.app.state)
    return build_metrics_response(request)


@admin_runtime_api_router.get("/admin/api/requests/recent")
@exceptions_handler
async def get_admin_recent_requests(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    provider: str | None = Query(default=None),
    endpoint: str | None = Query(default=None),
    method: str | None = Query(default=None),
    status_code: int | None = Query(default=None, ge=100, le=599),
    model: str | None = Query(default=None),
    error_type: str | None = Query(default=None),
):
    """Return recent structured request events for the admin UI."""
    verify_logs_ip_allowlist(request)
    return _recent_events_payload(
        request,
        kind="requests",
        limit=limit,
        provider=provider,
        endpoint=endpoint,
        method=method,
        status_code=status_code,
        model=model,
        error_type=error_type,
    )


@admin_runtime_api_router.get("/admin/api/errors/recent")
@exceptions_handler
async def get_admin_recent_errors(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    provider: str | None = Query(default=None),
    endpoint: str | None = Query(default=None),
    method: str | None = Query(default=None),
    status_code: int | None = Query(default=None, ge=100, le=599),
    model: str | None = Query(default=None),
    error_type: str | None = Query(default=None),
):
    """Return recent structured error events for the admin UI."""
    verify_logs_ip_allowlist(request)
    return _recent_events_payload(
        request,
        kind="errors",
        limit=limit,
        provider=provider,
        endpoint=endpoint,
        method=method,
        status_code=status_code,
        model=model,
        error_type=error_type,
    )
