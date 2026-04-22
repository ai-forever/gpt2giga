"""Runtime snapshot service for the admin UI."""

from __future__ import annotations

from fastapi.routing import APIRoute
from starlette.requests import Request

from gpt2giga.app.admin_ui import is_admin_ui_enabled
from gpt2giga.app.dependencies import (
    get_config_from_state,
    get_runtime_providers,
    get_runtime_services,
    get_runtime_stores,
)
from gpt2giga.app.observability import (
    filter_operator_noise,
    get_recent_error_feed_from_state,
    get_recent_request_feed_from_state,
    query_request_events,
)
from gpt2giga.core.app_meta import get_app_version
from gpt2giga.providers import list_provider_descriptors

from gpt2giga.app._admin_runtime.shared import (
    _collect_event_filter_options,
    _normalize_optional_text,
)

_ADMIN_UI_ROUTES = (
    "/admin",
    "/admin/overview",
    "/admin/setup",
    "/admin/settings",
    "/admin/keys",
    "/admin/logs",
    "/admin/playground",
    "/admin/traffic",
    "/admin/traffic-requests",
    "/admin/traffic-errors",
    "/admin/traffic-usage",
    "/admin/providers",
    "/admin/files-batches",
    "/admin/system",
)

_ADMIN_CAPABILITIES = (
    "ui",
    "setup",
    "version",
    "config",
    "runtime",
    "routes",
    "recent_requests",
    "recent_errors",
    "usage_by_key",
    "usage_by_provider",
    "settings_application",
    "settings_gigachat",
    "settings_security",
    "settings_revisions",
    "settings_rollback",
    "keys",
    "files_batches",
    "logs",
    "logs_stream",
)

_ADMIN_API_ROUTES = (
    "/admin/api/setup",
    "/admin/api/version",
    "/admin/api/config",
    "/admin/api/runtime",
    "/admin/api/routes",
    "/admin/api/capabilities",
    "/admin/api/requests/recent",
    "/admin/api/errors/recent",
    "/admin/api/usage/keys",
    "/admin/api/usage/providers",
    "/admin/api/settings/application",
    "/admin/api/settings/gigachat",
    "/admin/api/settings/security",
    "/admin/api/settings/revisions",
    "/admin/api/settings/revisions/{revision_id}/rollback",
    "/admin/api/keys",
    "/admin/api/logs",
    "/admin/api/logs/stream",
)


class AdminRuntimeSnapshotService:
    """Build runtime and control-plane inspection payloads for admin endpoints."""

    def __init__(self, request: Request) -> None:
        self.request = request
        self.config = get_config_from_state(request.app.state)
        self.proxy = self.config.proxy_settings

    def build_version_payload(self) -> dict[str, str]:
        """Return application version metadata for admin tooling."""
        return {"version": self.request.app.version or get_app_version()}

    def build_config_payload(self) -> dict[str, object]:
        """Return a sanitized config summary for admin tooling."""
        proxy = self.proxy
        runtime_store = proxy.runtime_store
        observability = proxy.observability
        return {
            "mode": proxy.mode,
            "host": proxy.host,
            "port": proxy.port,
            "enabled_providers": list(proxy.enabled_providers),
            "gigachat_api_mode": proxy.gigachat_api_mode,
            "gigachat_responses_api_mode": proxy.gigachat_responses_api_mode,
            "chat_backend_mode": proxy.chat_backend_mode,
            "responses_backend_mode": proxy.responses_backend_mode,
            "runtime_store_backend": runtime_store.backend,
            "runtime_store_namespace": runtime_store.namespace,
            "enable_telemetry": observability.enable_telemetry,
            "observability_sinks": list(observability.active_sinks),
            "runtime_store_dsn_configured": runtime_store.dsn_configured,
            "recent_requests_max_items": proxy.recent_requests_max_items,
            "recent_errors_max_items": proxy.recent_errors_max_items,
            "max_request_body_bytes": proxy.max_request_body_bytes,
            "max_audio_file_size_bytes": proxy.max_audio_file_size_bytes,
            "max_image_file_size_bytes": proxy.max_image_file_size_bytes,
            "max_text_file_size_bytes": proxy.max_text_file_size_bytes,
            "max_audio_image_total_size_bytes": proxy.max_audio_image_total_size_bytes,
            "enable_api_key_auth": proxy.enable_api_key_auth,
            "disable_ui": proxy.disable_ui,
            "scoped_api_keys_configured": len(proxy.scoped_api_keys),
            "governance_limits_configured": len(proxy.governance_limits),
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
            "summary": self._build_config_summary(),
        }

    def build_runtime_payload(self) -> dict[str, object]:
        """Return effective runtime status for the admin layer."""
        proxy = self.proxy
        runtime_store = proxy.runtime_store
        observability = proxy.observability
        is_prod_mode = proxy.mode == "PROD"
        auth_required = proxy.enable_api_key_auth or is_prod_mode
        metrics_enabled = observability.metrics_enabled
        ui_enabled = is_admin_ui_enabled(self.config)
        return {
            "app_version": self.request.app.version or get_app_version(),
            "mode": proxy.mode,
            "auth_required": auth_required,
            "scoped_api_keys_configured": len(proxy.scoped_api_keys),
            "docs_enabled": self.request.app.docs_url is not None,
            "redoc_enabled": self.request.app.redoc_url is not None,
            "openapi_enabled": self.request.app.openapi_url is not None,
            "enabled_providers": list(proxy.enabled_providers),
            "gigachat_api_mode": proxy.gigachat_api_mode,
            "gigachat_responses_api_mode": proxy.gigachat_responses_api_mode,
            "gigachat_model": self.config.gigachat_settings.model,
            "chat_backend_mode": proxy.chat_backend_mode,
            "responses_backend_mode": proxy.responses_backend_mode,
            "runtime_store_backend": runtime_store.backend,
            "runtime_store_namespace": runtime_store.namespace,
            "telemetry_enabled": observability.enable_telemetry,
            "observability_sinks": list(observability.active_sinks),
            "metrics_enabled": metrics_enabled,
            "governance_limits_configured": len(proxy.governance_limits),
            "governance_enabled": bool(proxy.governance_limits),
            "pass_model": proxy.pass_model,
            "pass_token": proxy.pass_token,
            "enable_reasoning": proxy.enable_reasoning,
            "enable_images": proxy.enable_images,
            "logs_ip_allowlist_enabled": bool(proxy.logs_ip_allowlist),
            "log_redact_sensitive": proxy.log_redact_sensitive,
            "admin_enabled": True,
            "admin_ui_enabled": ui_enabled,
            "disable_ui": proxy.disable_ui,
            "state": self._collect_state_status(),
        }

    def build_routes_payload(self) -> dict[str, object]:
        """Return mounted routes so operators can inspect active surface area."""
        return {"routes": self._serialize_routes()}

    def build_capabilities_payload(self) -> dict[str, object]:
        """Return enabled provider groups and operator capabilities."""
        enabled_providers = set(self.proxy.enabled_providers)
        runtime_store = self.proxy.runtime_store
        observability = self.proxy.observability
        metrics_enabled = observability.metrics_enabled
        capability_matrix = self._build_capability_matrix(
            metrics_enabled=metrics_enabled
        )
        ui_enabled = is_admin_ui_enabled(self.config)
        return {
            "backend": {
                "gigachat_api_mode": self.proxy.gigachat_api_mode,
                "chat_backend_mode": self.proxy.chat_backend_mode,
                "responses_backend_mode": self.proxy.responses_backend_mode,
                "runtime_store_backend": runtime_store.backend,
                "telemetry_enabled": observability.enable_telemetry,
                "observability_sinks": list(observability.active_sinks),
                "governance_enabled": bool(self.proxy.governance_limits),
                "governance_limits_configured": len(self.proxy.governance_limits),
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
                "enabled": True,
                "capabilities": self._admin_capability_list(
                    metrics_enabled=metrics_enabled,
                    ui_enabled=ui_enabled,
                ),
                "routes": self._admin_route_list(
                    metrics_enabled=metrics_enabled,
                    ui_enabled=ui_enabled,
                ),
                "legacy_routes": [],
            },
        }

    def build_recent_events_payload(
        self,
        *,
        kind: str,
        limit: int,
        request_id: str | None,
        provider: str | None,
        endpoint: str | None,
        method: str | None,
        status_code: int | None,
        model: str | None,
        error_type: str | None,
        include_noise: bool,
    ) -> dict[str, object]:
        """Build a filtered recent-events payload for admin tooling."""
        feed = (
            get_recent_request_feed_from_state(self.request.app.state)
            if kind == "requests"
            else get_recent_error_feed_from_state(self.request.app.state)
        )
        recent_events = list(feed.recent(limit=None))
        if not include_noise:
            recent_events = filter_operator_noise(recent_events)
        events = query_request_events(
            feed,
            limit=limit,
            request_id=_normalize_optional_text(request_id),
            provider=_normalize_optional_text(provider),
            endpoint=_normalize_optional_text(endpoint),
            method=_normalize_optional_text(method),
            status_code=status_code,
            model=_normalize_optional_text(model),
            error_type=_normalize_optional_text(error_type),
            exclude_noise=not include_noise,
        )
        return {
            "events": events,
            "count": len(events),
            "kind": kind,
            "limit": limit,
            "filters": {
                "request_id": _normalize_optional_text(request_id),
                "provider": _normalize_optional_text(provider),
                "endpoint": _normalize_optional_text(endpoint),
                "method": _normalize_optional_text(method),
                "status_code": status_code,
                "model": _normalize_optional_text(model),
                "error_type": _normalize_optional_text(error_type),
            },
            "available_filters": _collect_event_filter_options(recent_events),
        }

    def _admin_capability_list(
        self, *, metrics_enabled: bool, ui_enabled: bool
    ) -> list[str]:
        """Return the admin capability list exposed in runtime metadata."""
        return [
            *(["ui"] if ui_enabled else []),
            *_ADMIN_CAPABILITIES[1:14],
            *([] if not metrics_enabled else ["metrics"]),
            *_ADMIN_CAPABILITIES[14:],
        ]

    def _admin_route_list(
        self, *, metrics_enabled: bool, ui_enabled: bool
    ) -> list[str]:
        """Return the admin routes exposed in runtime metadata."""
        return [
            *([] if not ui_enabled else _ADMIN_UI_ROUTES),
            *_ADMIN_API_ROUTES[:14],
            *([] if not metrics_enabled else ["/admin/api/metrics"]),
            *_ADMIN_API_ROUTES[14:],
        ]

    def _build_config_summary(self) -> dict[str, dict[str, object]]:
        """Build grouped config sections for the admin UI."""
        proxy = self.proxy
        ui_enabled = is_admin_ui_enabled(proxy)
        return {
            "network": {
                "mode": proxy.mode,
                "bind": f"{proxy.host}:{proxy.port}",
                "https_enabled": proxy.use_https,
                "api_key_auth": proxy.enable_api_key_auth,
                "scoped_api_keys_configured": len(proxy.scoped_api_keys),
                "governance_limits_configured": len(proxy.governance_limits),
                "admin_enabled": True,
                "admin_ui_enabled": ui_enabled,
            },
            "providers": {
                "enabled_providers": list(proxy.enabled_providers),
                "gigachat_api_mode": proxy.gigachat_api_mode,
                "gigachat_responses_api_mode": proxy.gigachat_responses_api_mode,
                "chat_backend_mode": proxy.chat_backend_mode,
                "responses_backend_mode": proxy.responses_backend_mode,
                "telemetry_enabled": proxy.enable_telemetry,
                "observability_sinks": list(proxy.observability_sinks),
                "runtime_store_backend": proxy.runtime_store_backend,
                "runtime_store_namespace": proxy.runtime_store_namespace,
                "governance_enabled": bool(proxy.governance_limits),
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

    def _build_capability_matrix(self, *, metrics_enabled: bool) -> dict[str, object]:
        """Build a compact capability matrix for admin UI rendering."""
        enabled_providers = set(self.proxy.enabled_providers)
        ui_enabled = is_admin_ui_enabled(self.config)
        admin_routes = self._admin_route_list(
            metrics_enabled=metrics_enabled,
            ui_enabled=ui_enabled,
        )
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
                    "enabled": True,
                    "capabilities": self._admin_capability_list(
                        metrics_enabled=metrics_enabled,
                        ui_enabled=ui_enabled,
                    ),
                    "routes": admin_routes,
                    "route_count": len(admin_routes),
                },
            ]
        )
        return {
            "columns": ["surface", "enabled", "capabilities", "route_count"],
            "rows": rows,
        }

    def _collect_state_status(self) -> dict[str, dict[str, bool | int | str | None]]:
        """Return a coarse runtime snapshot of typed app-state containers."""
        services = get_runtime_services(self.request.app.state)
        providers = get_runtime_providers(self.request.app.state)
        stores = get_runtime_stores(self.request.app.state)
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
                "usage_by_api_key": len(stores.usage_by_api_key),
                "usage_by_provider": len(stores.usage_by_provider),
                "governance_counters": len(stores.governance_counters),
                "recent_requests": len(
                    get_recent_request_feed_from_state(self.request.app.state)
                ),
                "recent_errors": len(
                    get_recent_error_feed_from_state(self.request.app.state)
                ),
            },
        }

    def _serialize_routes(self) -> list[dict[str, object]]:
        """List mounted API routes for operator inspection."""
        route_entries: list[dict[str, object]] = []
        for route in self.request.app.routes:
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
        return sorted(
            route_entries,
            key=lambda entry: (str(entry["path"]), str(entry["name"])),
        )
