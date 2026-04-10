"""Runtime and capability endpoints for the admin layer."""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.routing import APIRoute
from starlette.requests import Request

from gpt2giga.api.admin.logs import verify_logs_ip_allowlist
from gpt2giga.api.system.metrics import build_metrics_response
from gpt2giga.app.observability import (
    filter_request_events,
    get_recent_error_feed_from_state,
    get_recent_request_feed_from_state,
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

admin_runtime_api_router = APIRouter(tags=["Admin"])

_PROVIDER_CAPABILITIES: dict[str, dict[str, list[str]]] = {
    "openai": {
        "capabilities": [
            "models",
            "chat_completions",
            "responses",
            "embeddings",
            "files",
            "batches",
            "litellm_model_info",
        ],
        "routes": [
            "/models",
            "/chat/completions",
            "/responses",
            "/embeddings",
            "/files",
            "/batches",
            "/model/info",
            "/v1/models",
            "/v1/chat/completions",
            "/v1/responses",
            "/v1/embeddings",
            "/v1/files",
            "/v1/batches",
            "/v1/model/info",
        ],
    },
    "anthropic": {
        "capabilities": ["messages", "count_tokens", "message_batches"],
        "routes": [
            "/messages",
            "/messages/count_tokens",
            "/messages/batches",
            "/v1/messages",
            "/v1/messages/count_tokens",
            "/v1/messages/batches",
        ],
    },
    "gemini": {
        "capabilities": [
            "generate_content",
            "stream_generate_content",
            "count_tokens",
            "batch_embed_contents",
            "models",
        ],
        "routes": [
            "/v1beta/models",
            "/v1beta/models/{model}",
            "/v1beta/models/{model}:generateContent",
            "/v1beta/models/{model}:streamGenerateContent",
            "/v1beta/models/{model}:countTokens",
            "/v1beta/models/{model}:batchEmbedContents",
        ],
    },
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
    metrics_enabled = "prometheus" in set(proxy.observability_sinks)
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
        "observability_sinks": list(proxy.observability_sinks),
        "runtime_store_dsn_configured": proxy.runtime_store_dsn is not None,
        "recent_requests_max_items": proxy.recent_requests_max_items,
        "recent_errors_max_items": proxy.recent_errors_max_items,
        "enable_api_key_auth": proxy.enable_api_key_auth,
        "pass_model": proxy.pass_model,
        "pass_token": proxy.pass_token,
        "enable_reasoning": proxy.enable_reasoning,
        "enable_images": proxy.enable_images,
        "log_level": proxy.log_level,
        "log_filename": proxy.log_filename,
        "log_redact_sensitive": proxy.log_redact_sensitive,
        "logs_ip_allowlist_enabled": bool(proxy.logs_ip_allowlist),
        "cors_allow_origins": list(proxy.cors_allow_origins),
        "cors_allow_methods": list(proxy.cors_allow_methods),
        "cors_allow_headers": list(proxy.cors_allow_headers),
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
    metrics_enabled = "prometheus" in set(config.proxy_settings.observability_sinks)
    return {
        "backend": {
            "gigachat_api_mode": config.proxy_settings.gigachat_api_mode,
            "chat_backend_mode": config.proxy_settings.chat_backend_mode,
            "responses_backend_mode": config.proxy_settings.responses_backend_mode,
            "runtime_store_backend": config.proxy_settings.runtime_store_backend,
            "observability_sinks": list(config.proxy_settings.observability_sinks),
        },
        "providers": {
            provider: {
                "enabled": provider in enabled_providers,
                **details,
            }
            for provider, details in _PROVIDER_CAPABILITIES.items()
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
) -> dict[str, object]:
    """Build a filtered recent-events payload for admin tooling."""
    feed = (
        get_recent_request_feed_from_state(request.app.state)
        if kind == "requests"
        else get_recent_error_feed_from_state(request.app.state)
    )
    events = filter_request_events(
        feed.recent(limit=limit),
        provider=provider,
        endpoint=endpoint,
    )
    return {
        "events": events,
        "count": len(events),
        "kind": kind,
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
):
    """Return recent structured request events for the admin UI."""
    verify_logs_ip_allowlist(request)
    return _recent_events_payload(
        request,
        kind="requests",
        limit=limit,
        provider=provider,
        endpoint=endpoint,
    )


@admin_runtime_api_router.get("/admin/api/errors/recent")
@exceptions_handler
async def get_admin_recent_errors(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    provider: str | None = Query(default=None),
    endpoint: str | None = Query(default=None),
):
    """Return recent structured error events for the admin UI."""
    verify_logs_ip_allowlist(request)
    return _recent_events_payload(
        request,
        kind="errors",
        limit=limit,
        provider=provider,
        endpoint=endpoint,
    )
