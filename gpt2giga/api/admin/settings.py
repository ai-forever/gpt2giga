"""Control-plane settings and API-key endpoints for the admin UI."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.requests import Request

from gpt2giga.api.admin.logs import get_client_ip, verify_logs_ip_allowlist
from gpt2giga.app.dependencies import (
    ensure_runtime_dependencies,
    get_config_from_state,
    get_logger_from_state,
    get_runtime_providers,
    get_runtime_stores,
)
from gpt2giga.app.wiring import reload_runtime_services
from gpt2giga.core.config.control_plane import (
    build_proxy_config_from_control_plane_payload,
    build_control_plane_status,
    claim_admin_instance,
    list_control_plane_revisions,
    load_control_plane_revision_payload,
    persist_control_plane_config,
)
from gpt2giga.core.config.observability import (
    ObservabilitySettings,
    ObservabilitySettingsUpdate,
)
from gpt2giga.core.config.settings import GigaChatCLI, ProxyConfig, ProxySettings
from gpt2giga.core.errors import exceptions_handler

admin_settings_api_router = APIRouter(tags=["Admin"])

_APPLICATION_FIELDS = {
    "mode",
    "host",
    "port",
    "use_https",
    "https_key_file",
    "https_cert_file",
    "enabled_providers",
    "gigachat_api_mode",
    "runtime_store_backend",
    "runtime_store_dsn",
    "runtime_store_namespace",
    "enable_telemetry",
    "observability_sinks",
    "recent_requests_max_items",
    "recent_errors_max_items",
    "embeddings",
    "pass_model",
    "pass_token",
    "enable_reasoning",
    "enable_images",
    "max_request_body_bytes",
    "max_audio_file_size_bytes",
    "max_image_file_size_bytes",
    "max_text_file_size_bytes",
    "max_audio_image_total_size_bytes",
    "log_level",
    "log_filename",
    "log_max_size",
    "log_redact_sensitive",
}
_GIGACHAT_FIELDS = {
    "access_token",
    "auth_url",
    "base_url",
    "ca_bundle_file",
    "cert_file",
    "credentials",
    "flags",
    "key_file",
    "key_file_password",
    "max_connections",
    "max_retries",
    "model",
    "password",
    "profanity_check",
    "retry_backoff_factor",
    "retry_on_status_codes",
    "scope",
    "timeout",
    "token_expiry_buffer_ms",
    "user",
    "verify_ssl_certs",
}
_SECURITY_FIELDS = {
    "enable_api_key_auth",
    "api_key",
    "scoped_api_keys",
    "governance_limits",
    "cors_allow_origins",
    "cors_allow_methods",
    "cors_allow_headers",
    "logs_ip_allowlist",
}
_RESTART_REQUIRED_FIELDS = {
    "mode",
    "host",
    "port",
    "use_https",
    "https_key_file",
    "https_cert_file",
    "enabled_providers",
    "runtime_store_backend",
    "runtime_store_dsn",
    "runtime_store_namespace",
    "pass_token",
    "max_request_body_bytes",
    "log_level",
    "log_filename",
    "log_max_size",
    "enable_api_key_auth",
    "cors_allow_origins",
    "cors_allow_methods",
    "cors_allow_headers",
}
_SECTION_FIELDS = {
    "application": _APPLICATION_FIELDS,
    "gigachat": _GIGACHAT_FIELDS,
    "security": _SECURITY_FIELDS,
}
_SECRET_FIELDS = {
    "api_key",
    "scoped_api_keys",
    "access_token",
    "credentials",
    "password",
    "key_file_password",
}


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


class ClaimInstanceRequest(BaseModel):
    """Capture optional operator context for the first-run claim step."""

    operator_label: str | None = Field(default=None, min_length=1)


def _mask_secret(value: str | None) -> str | None:
    """Return a short masked preview for a secret string."""
    if hasattr(value, "get_secret_value"):
        value = value.get_secret_value()
    if not value:
        return None
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _control_summary(request: Request) -> dict[str, Any]:
    config = get_config_from_state(request.app.state)
    return build_control_plane_status(config)


def _build_application_settings(proxy: ProxySettings) -> dict[str, Any]:
    return {
        "mode": proxy.mode,
        "host": proxy.host,
        "port": proxy.port,
        "use_https": proxy.use_https,
        "https_key_file": proxy.https_key_file,
        "https_cert_file": proxy.https_cert_file,
        "enabled_providers": list(proxy.enabled_providers),
        "gigachat_api_mode": proxy.gigachat_api_mode,
        "runtime_store_backend": proxy.runtime_store_backend,
        "runtime_store_dsn_configured": proxy.runtime_store_dsn is not None,
        "runtime_store_namespace": proxy.runtime_store_namespace,
        "enable_telemetry": proxy.enable_telemetry,
        "observability_sinks": list(proxy.observability_sinks),
        "recent_requests_max_items": proxy.recent_requests_max_items,
        "recent_errors_max_items": proxy.recent_errors_max_items,
        "embeddings": proxy.embeddings,
        "pass_model": proxy.pass_model,
        "pass_token": proxy.pass_token,
        "enable_reasoning": proxy.enable_reasoning,
        "enable_images": proxy.enable_images,
        "max_request_body_bytes": proxy.max_request_body_bytes,
        "max_audio_file_size_bytes": proxy.max_audio_file_size_bytes,
        "max_image_file_size_bytes": proxy.max_image_file_size_bytes,
        "max_text_file_size_bytes": proxy.max_text_file_size_bytes,
        "max_audio_image_total_size_bytes": proxy.max_audio_image_total_size_bytes,
        "log_level": proxy.log_level,
        "log_filename": proxy.log_filename,
        "log_max_size": proxy.log_max_size,
        "log_redact_sensitive": proxy.log_redact_sensitive,
    }


def _build_gigachat_settings(gigachat: GigaChatCLI) -> dict[str, Any]:
    return {
        "base_url": gigachat.base_url,
        "auth_url": gigachat.auth_url,
        "scope": gigachat.scope,
        "model": gigachat.model,
        "user": gigachat.user,
        "verify_ssl_certs": gigachat.verify_ssl_certs,
        "cert_file": gigachat.cert_file,
        "key_file": gigachat.key_file,
        "ca_bundle_file": gigachat.ca_bundle_file,
        "timeout": gigachat.timeout,
        "max_connections": gigachat.max_connections,
        "max_retries": gigachat.max_retries,
        "retry_backoff_factor": gigachat.retry_backoff_factor,
        "retry_on_status_codes": gigachat.retry_on_status_codes,
        "token_expiry_buffer_ms": gigachat.token_expiry_buffer_ms,
        "profanity_check": gigachat.profanity_check,
        "flags": gigachat.flags,
        "credentials_configured": gigachat.credentials is not None,
        "credentials_preview": _mask_secret(gigachat.credentials),
        "access_token_configured": gigachat.access_token is not None,
        "access_token_preview": _mask_secret(gigachat.access_token),
        "password_configured": gigachat.password is not None,
        "key_file_password_configured": gigachat.key_file_password is not None,
    }


def _build_security_settings(proxy: ProxySettings) -> dict[str, Any]:
    return {
        "enable_api_key_auth": proxy.enable_api_key_auth,
        "global_api_key_configured": proxy.api_key is not None,
        "global_api_key_preview": _mask_secret(proxy.api_key),
        "scoped_api_keys_configured": len(proxy.scoped_api_keys),
        "governance_limits": [
            rule.model_dump() if hasattr(rule, "model_dump") else dict(rule)
            for rule in proxy.governance_limits
        ],
        "cors_allow_origins": list(proxy.cors_allow_origins),
        "cors_allow_methods": list(proxy.cors_allow_methods),
        "cors_allow_headers": list(proxy.cors_allow_headers),
        "logs_ip_allowlist": list(proxy.logs_ip_allowlist),
    }


def _build_keys_payload(request: Request) -> dict[str, Any]:
    config = get_config_from_state(request.app.state)
    proxy = config.proxy_settings
    usage = get_runtime_stores(request.app.state).usage_by_api_key
    scoped = []
    for scoped_key in proxy.scoped_api_keys:
        key_data = (
            scoped_key.model_dump()
            if hasattr(scoped_key, "model_dump")
            else dict(scoped_key)
        )
        name = key_data.get("name") or "scoped"
        scoped.append(
            {
                "name": name,
                "key_preview": _mask_secret(key_data.get("key")),
                "providers": key_data.get("providers"),
                "endpoints": key_data.get("endpoints"),
                "models": key_data.get("models"),
                "usage": usage.get(name, {}),
            }
        )
    return {
        "global": {
            "configured": proxy.api_key is not None,
            "key_preview": _mask_secret(proxy.api_key),
            "usage": usage.get("global", {}),
        },
        "scoped": sorted(scoped, key=lambda item: item["name"]),
    }


def _normalize_compare_value(value: Any) -> Any:
    """Normalize settings values for stable equality checks."""
    if hasattr(value, "get_secret_value"):
        return value.get_secret_value()
    if isinstance(value, dict):
        return {
            str(key): _normalize_compare_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, list):
        return [_normalize_compare_value(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_compare_value(item) for item in value]
    return value


def _validate_known_fields(payload: dict[str, Any], section: str) -> None:
    unknown = sorted(set(payload) - _SECTION_FIELDS[section])
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown {section} setting fields: {', '.join(unknown)}",
        )


def _build_updated_config(
    current: ProxyConfig,
    *,
    proxy_updates: dict[str, Any] | None = None,
    gigachat_updates: dict[str, Any] | None = None,
) -> ProxyConfig:
    proxy_payload = current.proxy_settings.model_dump()
    gigachat_payload = current.gigachat_settings.model_dump()
    if proxy_updates:
        proxy_payload.update(proxy_updates)
    if gigachat_updates:
        gigachat_payload.update(gigachat_updates)

    proxy = ProxySettings.model_validate(proxy_payload)
    gigachat = GigaChatCLI.model_validate(gigachat_payload)
    return ProxyConfig(
        proxy=proxy.model_dump(),
        gigachat=gigachat.model_dump(),
        env_path=current.env_path,
    )


def _resolve_gigachat_factory(request: Request):
    """Resolve the active GigaChat client factory for admin test calls."""
    providers = get_runtime_providers(request.app.state)
    factory_getter = providers.gigachat_factory_getter
    if callable(factory_getter):
        return factory_getter()
    return providers.gigachat_factory


def _build_settings_snapshot(config: ProxyConfig) -> dict[str, Any]:
    """Build the safe, UI-facing snapshot of all settings sections."""
    return {
        "application": _build_application_settings(config.proxy_settings),
        "observability": ObservabilitySettings.from_proxy_settings(
            config.proxy_settings
        ).to_safe_payload(),
        "gigachat": _build_gigachat_settings(config.gigachat_settings),
        "security": _build_security_settings(config.proxy_settings),
    }


def _field_value_for_section(
    config: ProxyConfig,
    *,
    section: str,
    field: str,
) -> Any:
    """Return the raw setting value for a section field."""
    if section == "gigachat":
        return _normalize_compare_value(
            config.gigachat_settings.model_dump().get(field)
        )
    return _normalize_compare_value(config.proxy_settings.model_dump().get(field))


def _display_diff_value(section: str, field: str, value: Any) -> Any:
    """Return a safe display value for settings diffs."""
    if field not in _SECRET_FIELDS:
        return value

    if field == "scoped_api_keys":
        items = value or []
        names = sorted(
            str(item.get("name"))
            for item in items
            if isinstance(item, dict) and item.get("name")
        )
        return {"count": len(items), "names": names}

    if field in {"api_key", "credentials", "access_token"}:
        return {
            "configured": value not in (None, ""),
            "preview": _mask_secret(value),
        }

    return {"configured": value not in (None, "")}


def _build_section_diff(
    current: ProxyConfig,
    target: ProxyConfig,
    *,
    section: str,
) -> list[dict[str, Any]]:
    """Return the per-field diff for a settings section."""
    entries: list[dict[str, Any]] = []
    for field in sorted(_SECTION_FIELDS[section]):
        current_value = _field_value_for_section(current, section=section, field=field)
        target_value = _field_value_for_section(target, section=section, field=field)
        if current_value == target_value:
            continue
        entries.append(
            {
                "field": field,
                "current": _display_diff_value(section, field, current_value),
                "target": _display_diff_value(section, field, target_value),
            }
        )
    return entries


def _build_settings_diff(
    current: ProxyConfig,
    target: ProxyConfig,
) -> dict[str, list[dict[str, Any]]]:
    """Return a safe per-section diff between two runtime configs."""
    return {
        section: _build_section_diff(current, target, section=section)
        for section in _SECTION_FIELDS
    }


def _collect_changed_fields(
    current: ProxyConfig,
    target: ProxyConfig,
) -> set[str]:
    """Collect all changed settings fields between two configs."""
    changed_fields: set[str] = set()
    for section_diffs in _build_settings_diff(current, target).values():
        changed_fields.update(entry["field"] for entry in section_diffs)
    return changed_fields


def _build_revision_entry(
    current: ProxyConfig,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Build a safe revision entry with a diff against the current config."""
    target = build_proxy_config_from_control_plane_payload(
        payload,
        env_path=current.env_path,
    )
    diff = _build_settings_diff(current, target)
    changed_fields = payload.get("change", {}).get("changed_fields") or sorted(
        _collect_changed_fields(current, target)
    )
    sections = [section for section, entries in diff.items() if entries]
    return {
        "revision_id": payload.get("revision_id"),
        "updated_at": payload.get("updated_at"),
        "changed_fields": changed_fields,
        "restored_from_revision_id": payload.get("change", {}).get(
            "restored_from_revision_id"
        ),
        "sections": sections,
        "snapshot": _build_settings_snapshot(target),
        "diff": diff,
    }


async def _test_gigachat_settings(
    request: Request,
    *,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Run a non-persistent upstream connectivity check with candidate settings."""
    current = get_config_from_state(request.app.state)
    updated = _build_updated_config(current, gigachat_updates=payload)
    logger = get_logger_from_state(request.app.state)
    gigachat_factory = _resolve_gigachat_factory(request)
    if gigachat_factory is None:
        from gigachat import GigaChat

        gigachat_factory = GigaChat

    client = gigachat_factory(**updated.gigachat_settings.model_dump())
    try:
        models_response = await client.aget_models()
        raw_models = list(getattr(models_response, "data", []) or [])
        sample_models: list[str] = []
        for model in raw_models[:5]:
            model_id = getattr(model, "id", None) or getattr(model, "name", None)
            if model_id is not None:
                sample_models.append(str(model_id))
        return {
            "ok": True,
            "model_count": len(raw_models),
            "sample_models": sample_models,
            "gigachat_api_mode": current.proxy_settings.gigachat_api_mode,
        }
    except Exception as exc:  # pragma: no cover - exercised in integration tests
        if logger is not None:
            logger.warning(f"GigaChat connection test failed: {exc}")
        return {
            "ok": False,
            "error_type": exc.__class__.__name__,
            "error": str(exc),
            "gigachat_api_mode": current.proxy_settings.gigachat_api_mode,
        }
    finally:
        close = getattr(client, "aclose", None)
        if callable(close):
            await close()


async def _apply_updated_config(
    request: Request,
    updated_config: ProxyConfig,
    *,
    changed_fields: set[str],
    restored_from_revision_id: str | None = None,
) -> dict[str, Any]:
    app = request.app
    logger = get_logger_from_state(app.state)
    persist_path = persist_control_plane_config(
        updated_config,
        changed_fields=changed_fields,
        restored_from_revision_id=restored_from_revision_id,
    )
    ensure_runtime_dependencies(app.state, config=updated_config, logger=logger)

    restart_required = bool(changed_fields & _RESTART_REQUIRED_FIELDS)
    if not restart_required and logger is not None:
        await reload_runtime_services(app, config=updated_config, logger=logger)

    return {
        "persisted_path": str(persist_path),
        "restart_required": restart_required,
        "applied_runtime": not restart_required,
        "changed_fields": sorted(changed_fields),
    }


@admin_settings_api_router.get("/admin/api/setup")
@exceptions_handler
async def get_admin_setup_status(request: Request):
    """Return first-run and persisted-config status for the console."""
    verify_logs_ip_allowlist(request)
    return _control_summary(request)


@admin_settings_api_router.post("/admin/api/setup/claim")
@exceptions_handler
async def claim_admin_setup_instance(
    request: Request,
    payload: ClaimInstanceRequest | None = Body(default=None),
):
    """Record the operator claim for the current bootstrap session."""
    verify_logs_ip_allowlist(request)
    config = get_config_from_state(request.app.state)
    control_plane = _control_summary(request)

    if not control_plane["bootstrap"]["required"]:
        raise HTTPException(
            status_code=409,
            detail="Claim flow is available only during PROD bootstrap.",
        )

    claim = claim_admin_instance(
        operator_label=payload.operator_label if payload else None,
        claimed_via="admin_setup",
        claimed_from=get_client_ip(request) or None,
    )
    return {
        "claimed": True,
        "claim": claim,
        "control_plane": build_control_plane_status(config),
    }


@admin_settings_api_router.get("/admin/api/settings/application")
@exceptions_handler
async def get_application_settings(request: Request):
    """Return UI-facing application settings."""
    verify_logs_ip_allowlist(request)
    proxy = get_config_from_state(request.app.state).proxy_settings
    return {
        "section": "application",
        "values": _build_application_settings(proxy),
        "control_plane": _control_summary(request),
    }


@admin_settings_api_router.put("/admin/api/settings/application")
@exceptions_handler
async def update_application_settings(
    request: Request,
    payload: dict[str, Any] = Body(...),
):
    """Persist and optionally apply application settings."""
    verify_logs_ip_allowlist(request)
    _validate_known_fields(payload, "application")
    current = get_config_from_state(request.app.state)
    updated = _build_updated_config(current, proxy_updates=payload)
    result = await _apply_updated_config(
        request,
        updated,
        changed_fields=set(payload),
    )
    return {
        "section": "application",
        "values": _build_application_settings(updated.proxy_settings),
        **result,
    }


@admin_settings_api_router.get("/admin/api/settings/observability")
@exceptions_handler
async def get_observability_settings(request: Request):
    """Return UI-facing grouped observability settings."""
    verify_logs_ip_allowlist(request)
    proxy = get_config_from_state(request.app.state).proxy_settings
    return {
        "section": "observability",
        "values": ObservabilitySettings.from_proxy_settings(proxy).to_safe_payload(),
        "control_plane": _control_summary(request),
    }


@admin_settings_api_router.put("/admin/api/settings/observability")
@exceptions_handler
async def update_observability_settings(
    request: Request,
    payload: ObservabilitySettingsUpdate,
):
    """Persist and apply grouped observability settings."""
    verify_logs_ip_allowlist(request)
    proxy_updates = payload.to_proxy_updates()
    current = get_config_from_state(request.app.state)
    updated = _build_updated_config(current, proxy_updates=proxy_updates)
    result = await _apply_updated_config(
        request,
        updated,
        changed_fields=set(proxy_updates),
    )
    return {
        "section": "observability",
        "values": ObservabilitySettings.from_proxy_settings(
            updated.proxy_settings
        ).to_safe_payload(),
        **result,
    }


@admin_settings_api_router.get("/admin/api/settings/gigachat")
@exceptions_handler
async def get_gigachat_settings(request: Request):
    """Return UI-facing GigaChat settings with masked secrets."""
    verify_logs_ip_allowlist(request)
    gigachat = get_config_from_state(request.app.state).gigachat_settings
    return {
        "section": "gigachat",
        "values": _build_gigachat_settings(gigachat),
        "control_plane": _control_summary(request),
    }


@admin_settings_api_router.put("/admin/api/settings/gigachat")
@exceptions_handler
async def update_gigachat_settings(
    request: Request,
    payload: dict[str, Any] = Body(...),
):
    """Persist and apply GigaChat settings."""
    verify_logs_ip_allowlist(request)
    _validate_known_fields(payload, "gigachat")
    current = get_config_from_state(request.app.state)
    updated = _build_updated_config(current, gigachat_updates=payload)
    result = await _apply_updated_config(
        request,
        updated,
        changed_fields=set(payload),
    )
    return {
        "section": "gigachat",
        "values": _build_gigachat_settings(updated.gigachat_settings),
        **result,
    }


@admin_settings_api_router.post("/admin/api/settings/gigachat/test")
@exceptions_handler
async def test_gigachat_settings(
    request: Request,
    payload: dict[str, Any] = Body(...),
):
    """Test candidate GigaChat settings without persisting them."""
    verify_logs_ip_allowlist(request)
    _validate_known_fields(payload, "gigachat")
    return await _test_gigachat_settings(request, payload=payload)


@admin_settings_api_router.get("/admin/api/settings/security")
@exceptions_handler
async def get_security_settings(request: Request):
    """Return UI-facing security settings."""
    verify_logs_ip_allowlist(request)
    proxy = get_config_from_state(request.app.state).proxy_settings
    return {
        "section": "security",
        "values": _build_security_settings(proxy),
        "control_plane": _control_summary(request),
    }


@admin_settings_api_router.put("/admin/api/settings/security")
@exceptions_handler
async def update_security_settings(
    request: Request,
    payload: dict[str, Any] = Body(...),
):
    """Persist and optionally apply security settings."""
    verify_logs_ip_allowlist(request)
    _validate_known_fields(payload, "security")
    current = get_config_from_state(request.app.state)
    updated = _build_updated_config(current, proxy_updates=payload)
    result = await _apply_updated_config(
        request,
        updated,
        changed_fields=set(payload),
    )
    return {
        "section": "security",
        "values": _build_security_settings(updated.proxy_settings),
        **result,
    }


@admin_settings_api_router.get("/admin/api/settings/revisions")
@exceptions_handler
async def get_settings_revisions(
    request: Request,
    limit: int = Query(default=6, ge=1, le=20),
):
    """Return recent control-plane revisions with safe diffs."""
    verify_logs_ip_allowlist(request)
    current = get_config_from_state(request.app.state)
    revisions = [
        _build_revision_entry(current, payload)
        for payload in list_control_plane_revisions(limit=limit)
    ]
    return {
        "current": _build_settings_snapshot(current),
        "revisions": revisions,
        "control_plane": _control_summary(request),
    }


@admin_settings_api_router.post("/admin/api/settings/revisions/{revision_id}/rollback")
@exceptions_handler
async def rollback_settings_revision(
    request: Request,
    revision_id: str,
):
    """Rollback runtime settings to a previous persisted revision."""
    verify_logs_ip_allowlist(request)
    current = get_config_from_state(request.app.state)
    try:
        payload = load_control_plane_revision_payload(revision_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Revision not found") from exc

    updated = build_proxy_config_from_control_plane_payload(
        payload,
        env_path=current.env_path,
    )
    diff = _build_settings_diff(current, updated)
    changed_fields = _collect_changed_fields(current, updated)
    result = await _apply_updated_config(
        request,
        updated,
        changed_fields=changed_fields,
        restored_from_revision_id=revision_id,
    )
    return {
        "rolled_back_revision_id": revision_id,
        "values": _build_settings_snapshot(updated),
        "diff": diff,
        **result,
    }


@admin_settings_api_router.get("/admin/api/keys")
@exceptions_handler
async def get_admin_keys(request: Request):
    """Return global and scoped API-key metadata for the admin console."""
    verify_logs_ip_allowlist(request)
    return _build_keys_payload(request)


@admin_settings_api_router.post("/admin/api/keys/global/rotate")
@exceptions_handler
async def rotate_global_key(
    request: Request,
    payload: GlobalKeyRotateRequest,
):
    """Create or rotate the global API key."""
    verify_logs_ip_allowlist(request)
    key_value = payload.value or secrets.token_urlsafe(24)
    current = get_config_from_state(request.app.state)
    updated = _build_updated_config(current, proxy_updates={"api_key": key_value})
    result = await _apply_updated_config(
        request,
        updated,
        changed_fields={"api_key"},
    )
    return {
        "global": {
            "value": key_value,
            "key_preview": _mask_secret(key_value),
        },
        "keys": _build_keys_payload(request),
        **result,
    }


@admin_settings_api_router.post("/admin/api/keys/scoped")
@exceptions_handler
async def create_scoped_key(
    request: Request,
    payload: ScopedKeyCreateRequest,
):
    """Create a scoped API key with provider/endpoint/model filters."""
    verify_logs_ip_allowlist(request)
    current = get_config_from_state(request.app.state)
    scoped_api_keys = [
        item.model_dump() if hasattr(item, "model_dump") else dict(item)
        for item in current.proxy_settings.scoped_api_keys
    ]
    existing_names = {str(item.get("name")) for item in scoped_api_keys}
    if payload.name in existing_names:
        raise HTTPException(
            status_code=409,
            detail=f"Scoped API key `{payload.name}` already exists",
        )

    key_value = payload.key or secrets.token_urlsafe(24)
    scoped_api_keys.append(
        {
            "name": payload.name,
            "key": key_value,
            "providers": payload.providers,
            "endpoints": payload.endpoints,
            "models": payload.models,
        }
    )
    updated = _build_updated_config(
        current,
        proxy_updates={"scoped_api_keys": scoped_api_keys},
    )
    result = await _apply_updated_config(
        request,
        updated,
        changed_fields={"scoped_api_keys"},
    )
    return {
        "scoped_key": {
            "name": payload.name,
            "value": key_value,
            "key_preview": _mask_secret(key_value),
        },
        "keys": _build_keys_payload(request),
        **result,
    }


@admin_settings_api_router.post("/admin/api/keys/scoped/{name}/rotate")
@exceptions_handler
async def rotate_scoped_key(
    request: Request,
    name: str,
    payload: ScopedKeyRotateRequest,
):
    """Rotate an existing scoped API key and return the new value once."""
    verify_logs_ip_allowlist(request)
    current = get_config_from_state(request.app.state)
    key_value = payload.key or secrets.token_urlsafe(24)
    found = False
    scoped_api_keys = []
    for item in current.proxy_settings.scoped_api_keys:
        raw_item = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        if raw_item.get("name") == name:
            raw_item["key"] = key_value
            found = True
        scoped_api_keys.append(raw_item)

    if not found:
        raise HTTPException(
            status_code=404, detail=f"Scoped API key `{name}` not found"
        )

    updated = _build_updated_config(
        current,
        proxy_updates={"scoped_api_keys": scoped_api_keys},
    )
    result = await _apply_updated_config(
        request,
        updated,
        changed_fields={"scoped_api_keys"},
    )
    return {
        "scoped_key": {
            "name": name,
            "value": key_value,
            "key_preview": _mask_secret(key_value),
        },
        "keys": _build_keys_payload(request),
        **result,
    }


@admin_settings_api_router.delete("/admin/api/keys/scoped/{name}")
@exceptions_handler
async def delete_scoped_key(request: Request, name: str):
    """Delete a scoped API key by its UI-visible name."""
    verify_logs_ip_allowlist(request)
    current = get_config_from_state(request.app.state)
    scoped_api_keys = []
    removed = False
    for item in current.proxy_settings.scoped_api_keys:
        raw_item = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        if raw_item.get("name") == name:
            removed = True
            continue
        scoped_api_keys.append(raw_item)

    if not removed:
        raise HTTPException(
            status_code=404, detail=f"Scoped API key `{name}` not found"
        )

    updated = _build_updated_config(
        current,
        proxy_updates={"scoped_api_keys": scoped_api_keys},
    )
    result = await _apply_updated_config(
        request,
        updated,
        changed_fields={"scoped_api_keys"},
    )
    return {
        "deleted": name,
        "keys": _build_keys_payload(request),
        **result,
    }
