"""Control-plane settings and API-key endpoints for the admin UI."""

from __future__ import annotations

from fastapi import APIRouter, Body, Query
from pydantic import BaseModel, Field
from starlette.requests import Request

from gpt2giga.api.admin.access import verify_admin_ip_allowlist
from gpt2giga.app._admin_settings.models import (
    ApplicationSettingsUpdate,
    ClaimInstanceRequest,
    GigaChatSettingsUpdate,
    SecuritySettingsUpdate,
)
from gpt2giga.app.admin_settings import (
    AdminControlPlaneSettingsService,
    AdminKeyManagementService,
)
from gpt2giga.core.config.observability import ObservabilitySettingsUpdate
from gpt2giga.core.errors import exceptions_handler

admin_settings_api_router = APIRouter(tags=["Admin"])


class GlobalKeyRotateRequest(BaseModel):
    """Create or rotate the global gateway API key."""

    value: str | None = Field(default=None, min_length=1)


class ScopedKeyCreateRequest(BaseModel):
    """Create a scoped gateway API key."""

    name: str = Field(min_length=1)
    key: str | None = Field(default=None, min_length=1)
    providers: list[str] | None = None
    endpoints: list[str] | None = None
    models: list[str] | None = None


class ScopedKeyRotateRequest(BaseModel):
    """Rotate a scoped key in place."""

    key: str | None = Field(default=None, min_length=1)


@admin_settings_api_router.get("/admin/api/setup")
@exceptions_handler
async def get_admin_setup_status(request: Request):
    """Return first-run and persisted-config status for the console."""
    verify_admin_ip_allowlist(request)
    return AdminControlPlaneSettingsService(request).build_setup_status_payload()


@admin_settings_api_router.post("/admin/api/setup/claim")
@exceptions_handler
async def claim_admin_setup_instance(
    request: Request,
    payload: ClaimInstanceRequest | None = Body(default=None),
):
    """Record the operator claim for the current bootstrap session."""
    verify_admin_ip_allowlist(request)
    return AdminControlPlaneSettingsService(request).claim_setup_instance(
        payload.operator_label if payload else None
    )


@admin_settings_api_router.get("/admin/api/settings/application")
@exceptions_handler
async def get_application_settings(request: Request):
    """Return UI-facing application settings."""
    verify_admin_ip_allowlist(request)
    return AdminControlPlaneSettingsService(request).build_application_payload()


@admin_settings_api_router.put("/admin/api/settings/application")
@exceptions_handler
async def update_application_settings(
    request: Request,
    payload: ApplicationSettingsUpdate,
):
    """Persist and optionally apply application settings."""
    verify_admin_ip_allowlist(request)
    return await AdminControlPlaneSettingsService(request).update_application_settings(
        payload
    )


@admin_settings_api_router.get("/admin/api/settings/observability")
@exceptions_handler
async def get_observability_settings(request: Request):
    """Return UI-facing grouped observability settings."""
    verify_admin_ip_allowlist(request)
    return AdminControlPlaneSettingsService(request).build_observability_payload()


@admin_settings_api_router.put("/admin/api/settings/observability")
@exceptions_handler
async def update_observability_settings(
    request: Request,
    payload: ObservabilitySettingsUpdate,
):
    """Persist and apply grouped observability settings."""
    verify_admin_ip_allowlist(request)
    return await AdminControlPlaneSettingsService(
        request
    ).update_observability_settings(payload)


@admin_settings_api_router.get("/admin/api/settings/gigachat")
@exceptions_handler
async def get_gigachat_settings(request: Request):
    """Return UI-facing GigaChat settings with masked secrets."""
    verify_admin_ip_allowlist(request)
    return AdminControlPlaneSettingsService(request).build_gigachat_payload()


@admin_settings_api_router.put("/admin/api/settings/gigachat")
@exceptions_handler
async def update_gigachat_settings(
    request: Request,
    payload: GigaChatSettingsUpdate,
):
    """Persist and apply GigaChat settings."""
    verify_admin_ip_allowlist(request)
    return await AdminControlPlaneSettingsService(request).update_gigachat_settings(
        payload
    )


@admin_settings_api_router.post("/admin/api/settings/gigachat/test")
@exceptions_handler
async def test_gigachat_settings(
    request: Request,
    payload: GigaChatSettingsUpdate,
):
    """Test candidate GigaChat settings without persisting them."""
    verify_admin_ip_allowlist(request)
    return await AdminControlPlaneSettingsService(request).test_gigachat_settings(
        payload
    )


@admin_settings_api_router.get("/admin/api/settings/security")
@exceptions_handler
async def get_security_settings(request: Request):
    """Return UI-facing security settings."""
    verify_admin_ip_allowlist(request)
    return AdminControlPlaneSettingsService(request).build_security_payload()


@admin_settings_api_router.put("/admin/api/settings/security")
@exceptions_handler
async def update_security_settings(
    request: Request,
    payload: SecuritySettingsUpdate,
):
    """Persist and optionally apply security settings."""
    verify_admin_ip_allowlist(request)
    return await AdminControlPlaneSettingsService(request).update_security_settings(
        payload
    )


@admin_settings_api_router.get("/admin/api/settings/revisions")
@exceptions_handler
async def get_settings_revisions(
    request: Request,
    limit: int = Query(default=6, ge=1, le=20),
):
    """Return recent control-plane revisions with safe diffs."""
    verify_admin_ip_allowlist(request)
    return AdminControlPlaneSettingsService(request).build_revisions_payload(
        limit=limit
    )


@admin_settings_api_router.post("/admin/api/settings/revisions/{revision_id}/rollback")
@exceptions_handler
async def rollback_settings_revision(
    request: Request,
    revision_id: str,
):
    """Rollback runtime settings to a previous persisted revision."""
    verify_admin_ip_allowlist(request)
    return await AdminControlPlaneSettingsService(request).rollback_revision(
        revision_id
    )


@admin_settings_api_router.get("/admin/api/keys")
@exceptions_handler
async def get_admin_keys(request: Request):
    """Return global and scoped API-key metadata for the admin console."""
    verify_admin_ip_allowlist(request)
    return AdminKeyManagementService(request).build_payload()


@admin_settings_api_router.post("/admin/api/keys/global/rotate")
@exceptions_handler
async def rotate_global_key(
    request: Request,
    payload: GlobalKeyRotateRequest,
):
    """Create or rotate the global API key."""
    verify_admin_ip_allowlist(request)
    return await AdminKeyManagementService(request).rotate_global_key(
        value=payload.value
    )


@admin_settings_api_router.post("/admin/api/keys/scoped")
@exceptions_handler
async def create_scoped_key(
    request: Request,
    payload: ScopedKeyCreateRequest,
):
    """Create a scoped API key with provider/endpoint/model filters."""
    verify_admin_ip_allowlist(request)
    return await AdminKeyManagementService(request).create_scoped_key(
        name=payload.name,
        key=payload.key,
        providers=payload.providers,
        endpoints=payload.endpoints,
        models=payload.models,
    )


@admin_settings_api_router.post("/admin/api/keys/scoped/{name}/rotate")
@exceptions_handler
async def rotate_scoped_key(
    request: Request,
    name: str,
    payload: ScopedKeyRotateRequest,
):
    """Rotate an existing scoped API key and return the new value once."""
    verify_admin_ip_allowlist(request)
    return await AdminKeyManagementService(request).rotate_scoped_key(
        name=name,
        key=payload.key,
    )


@admin_settings_api_router.delete("/admin/api/keys/scoped/{name}")
@exceptions_handler
async def delete_scoped_key(request: Request, name: str):
    """Delete a scoped API key by its UI-visible name."""
    verify_admin_ip_allowlist(request)
    return await AdminKeyManagementService(request).delete_scoped_key(name=name)
