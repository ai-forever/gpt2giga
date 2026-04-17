"""Runtime and capability endpoints for the admin layer."""

from __future__ import annotations

from fastapi import APIRouter, Query
from starlette.requests import Request

from gpt2giga.api.admin.logs import verify_logs_ip_allowlist
from gpt2giga.api.system.metrics import build_metrics_response
from gpt2giga.app.admin_runtime import AdminRuntimeSnapshotService, AdminUsageReporter
from gpt2giga.app.dependencies import get_runtime_observability
from gpt2giga.core.errors import exceptions_handler

admin_runtime_api_router = APIRouter(tags=["Admin"])


@admin_runtime_api_router.get("/admin/api/version")
@exceptions_handler
async def get_admin_version(request: Request):
    """Return application version metadata for admin tooling."""
    verify_logs_ip_allowlist(request)
    return AdminRuntimeSnapshotService(request).build_version_payload()


@admin_runtime_api_router.get("/admin/api/config")
@exceptions_handler
async def get_admin_config(request: Request):
    """Return a sanitized config summary for admin tooling."""
    verify_logs_ip_allowlist(request)
    return AdminRuntimeSnapshotService(request).build_config_payload()


@admin_runtime_api_router.get("/admin/api/runtime")
@exceptions_handler
async def get_admin_runtime(request: Request):
    """Return effective runtime status for the admin layer."""
    verify_logs_ip_allowlist(request)
    return AdminRuntimeSnapshotService(request).build_runtime_payload()


@admin_runtime_api_router.get("/admin/api/routes")
@exceptions_handler
async def get_admin_routes(request: Request):
    """Return mounted routes so operators can inspect active surface area."""
    verify_logs_ip_allowlist(request)
    return AdminRuntimeSnapshotService(request).build_routes_payload()


@admin_runtime_api_router.get("/admin/api/capabilities")
@exceptions_handler
async def get_admin_capabilities(request: Request):
    """Return enabled provider groups and operator capabilities."""
    verify_logs_ip_allowlist(request)
    return AdminRuntimeSnapshotService(request).build_capabilities_payload()


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
    include_noise: bool = Query(default=False),
    request_id: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    endpoint: str | None = Query(default=None),
    method: str | None = Query(default=None),
    status_code: int | None = Query(default=None, ge=100, le=599),
    model: str | None = Query(default=None),
    error_type: str | None = Query(default=None),
):
    """Return recent structured request events for the admin UI."""
    verify_logs_ip_allowlist(request)
    return AdminRuntimeSnapshotService(request).build_recent_events_payload(
        kind="requests",
        limit=limit,
        request_id=request_id,
        provider=provider,
        endpoint=endpoint,
        method=method,
        status_code=status_code,
        model=model,
        error_type=error_type,
        include_noise=include_noise,
    )


@admin_runtime_api_router.get("/admin/api/errors/recent")
@exceptions_handler
async def get_admin_recent_errors(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    include_noise: bool = Query(default=False),
    request_id: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    endpoint: str | None = Query(default=None),
    method: str | None = Query(default=None),
    status_code: int | None = Query(default=None, ge=100, le=599),
    model: str | None = Query(default=None),
    error_type: str | None = Query(default=None),
):
    """Return recent structured error events for the admin UI."""
    verify_logs_ip_allowlist(request)
    return AdminRuntimeSnapshotService(request).build_recent_events_payload(
        kind="errors",
        limit=limit,
        request_id=request_id,
        provider=provider,
        endpoint=endpoint,
        method=method,
        status_code=status_code,
        model=model,
        error_type=error_type,
        include_noise=include_noise,
    )


@admin_runtime_api_router.get("/admin/api/usage/keys")
@exceptions_handler
async def get_admin_usage_by_key(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    provider: str | None = Query(default=None),
    model: str | None = Query(default=None),
    source: str | None = Query(default=None),
):
    """Return aggregated usage counters grouped by authenticated API key."""
    verify_logs_ip_allowlist(request)
    return AdminUsageReporter(request).build_payload(
        kind="keys",
        limit=limit,
        provider=provider,
        model=model,
        source=source,
    )


@admin_runtime_api_router.get("/admin/api/usage/providers")
@exceptions_handler
async def get_admin_usage_by_provider(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    provider: str | None = Query(default=None),
    model: str | None = Query(default=None),
    api_key_name: str | None = Query(default=None),
):
    """Return aggregated usage counters grouped by external provider."""
    verify_logs_ip_allowlist(request)
    return AdminUsageReporter(request).build_payload(
        kind="providers",
        limit=limit,
        provider=provider,
        model=model,
        api_key_name=api_key_name,
    )
