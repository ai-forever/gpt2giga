"""Shared helpers for admin control-plane settings services."""

from __future__ import annotations

from typing import Any, Protocol, cast

from starlette.requests import Request

from gpt2giga.app.runtime_backends import list_runtime_backend_descriptors
from gpt2giga.core.config.settings import GigaChatCLI, ProxyConfig, ProxySettings

_APPLICATION_FIELDS = {
    "mode",
    "host",
    "port",
    "use_https",
    "https_key_file",
    "https_cert_file",
    "enabled_providers",
    "gigachat_api_mode",
    "gigachat_responses_api_mode",
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

_RUNTIME_STORE_BACKEND_LABELS = {
    "memory": "Memory",
    "sqlite": "SQLite",
    "redis": "Redis",
    "postgres": "Postgres",
    "s3": "S3",
}
_RUNTIME_STORE_BACKEND_DESCRIPTIONS = {
    "memory": "Process-local dictionaries and recent-event buffers.",
    "sqlite": "SQLite-backed runtime stores and recent-event feeds.",
    "redis": "Redis-backed runtime stores and recent-event feeds.",
    "postgres": "Postgres-backed runtime stores and recent-event feeds.",
    "s3": "Object-storage-backed runtime snapshots and feeds.",
}
_RUNTIME_STORE_BACKEND_ORDER = ("memory", "sqlite", "redis", "postgres", "s3")


class _SecretValue(Protocol):
    def get_secret_value(self) -> str: ...


def _mask_secret(value: object) -> str | None:
    """Return a short masked preview for a secret string."""
    if hasattr(value, "get_secret_value"):
        value = cast(_SecretValue, value).get_secret_value()
    if value is not None and not isinstance(value, str):
        raise TypeError("secret preview expects a string-like value")
    if not value:
        return None
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _get_client_ip(request: Request) -> str:
    """Extract client IP from X-Forwarded-For or request.client."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return ""


def _build_application_settings(proxy: ProxySettings) -> dict[str, Any]:
    """Build a safe application settings payload for the admin UI."""
    runtime_store = proxy.runtime_store
    observability = proxy.observability
    return {
        "mode": proxy.mode,
        "host": proxy.host,
        "port": proxy.port,
        "use_https": proxy.use_https,
        "https_key_file": proxy.https_key_file,
        "https_cert_file": proxy.https_cert_file,
        "enabled_providers": list(proxy.enabled_providers),
        "gigachat_api_mode": proxy.gigachat_api_mode,
        "gigachat_responses_api_mode": proxy.gigachat_responses_api_mode,
        "runtime_store_backend": runtime_store.backend,
        "runtime_store_dsn_configured": runtime_store.dsn_configured,
        "runtime_store_namespace": runtime_store.namespace,
        "enable_telemetry": observability.enable_telemetry,
        "observability_sinks": list(observability.active_sinks),
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


def _build_runtime_store_catalog(
    *,
    configured_backend: str,
    active_backend: str | None,
) -> list[dict[str, Any]]:
    """Build a UI-facing runtime store catalog with configured and active state."""
    registered = {
        descriptor.name: descriptor for descriptor in list_runtime_backend_descriptors()
    }
    ordered_names = list(_RUNTIME_STORE_BACKEND_ORDER)
    ordered_names.extend(
        name for name in sorted(registered) if name not in _RUNTIME_STORE_BACKEND_ORDER
    )

    catalog: list[dict[str, Any]] = []
    for name in ordered_names:
        descriptor = registered.get(name)
        catalog.append(
            {
                "name": name,
                "label": _RUNTIME_STORE_BACKEND_LABELS.get(name, name),
                "description": (
                    descriptor.description
                    if descriptor is not None
                    else _RUNTIME_STORE_BACKEND_DESCRIPTIONS.get(
                        name,
                        "Custom runtime store backend.",
                    )
                ),
                "registered": descriptor is not None,
                "configured": name == configured_backend,
                "active": name == active_backend,
            }
        )
    return catalog


def _build_application_settings_payload(
    proxy: ProxySettings,
    *,
    active_backend: str | None,
) -> dict[str, Any]:
    """Build application settings plus runtime store catalog state."""
    payload = _build_application_settings(proxy)
    payload["runtime_store_active_backend"] = active_backend
    payload["runtime_store_catalog"] = _build_runtime_store_catalog(
        configured_backend=str(payload.get("runtime_store_backend") or ""),
        active_backend=active_backend,
    )
    payload["runtime_store_registered_backends"] = [
        item["name"]
        for item in payload["runtime_store_catalog"]
        if item.get("registered")
    ]
    return payload


def _build_gigachat_settings(gigachat: GigaChatCLI) -> dict[str, Any]:
    """Build a safe GigaChat settings payload for the admin UI."""
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
        "password_preview": _mask_secret(gigachat.password),
        "key_file_password_configured": gigachat.key_file_password is not None,
    }


def _build_security_settings(proxy: ProxySettings) -> dict[str, Any]:
    """Build a safe security settings payload for the admin UI."""
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


def _normalize_compare_value(value: Any) -> Any:
    """Normalize settings values for stable equality checks."""
    if hasattr(value, "get_secret_value"):
        return value.get_secret_value()
    if isinstance(value, dict):
        return {
            str(key): _normalize_compare_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_compare_value(item) for item in value]
    return value


def _build_updated_config(
    current: ProxyConfig,
    *,
    proxy_updates: dict[str, Any] | None = None,
    gigachat_updates: dict[str, Any] | None = None,
) -> ProxyConfig:
    """Build a validated config snapshot with candidate updates applied."""
    proxy_payload = current.proxy_settings.model_dump()
    gigachat_payload = current.gigachat_settings.model_dump()
    if proxy_updates:
        proxy_payload.update(proxy_updates)
    if gigachat_updates:
        gigachat_payload.update(gigachat_updates)

    proxy = ProxySettings.model_validate(proxy_payload)
    gigachat = GigaChatCLI.model_validate(gigachat_payload)
    return ProxyConfig(
        proxy=proxy,
        gigachat=gigachat,
        env_path=current.env_path,
    )


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


def _display_diff_value(field: str, value: Any) -> Any:
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
                "current": _display_diff_value(field, current_value),
                "target": _display_diff_value(field, target_value),
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
