"""Domain services for admin control-plane settings and key management."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import HTTPException
from starlette.requests import Request

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


def _mask_secret(value: str | None) -> str | None:
    """Return a short masked preview for a secret string."""
    if hasattr(value, "get_secret_value"):
        value = value.get_secret_value()
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
        proxy=proxy.model_dump(),
        gigachat=gigachat.model_dump(),
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


class AdminControlPlaneSettingsService:
    """Build control-plane payloads and persist admin settings mutations."""

    def __init__(self, request: Request) -> None:
        self.request = request
        self.app = request.app
        self.state = request.app.state
        self.config = get_config_from_state(self.state)

    def build_setup_status_payload(self) -> dict[str, Any]:
        """Return first-run and persisted-config status for the console."""
        return self._control_summary()

    def claim_setup_instance(self, operator_label: str | None) -> dict[str, Any]:
        """Record operator metadata for the first-run claim step."""
        control_plane = self._control_summary()
        if not control_plane["bootstrap"]["required"]:
            raise HTTPException(
                status_code=409,
                detail="Claim flow is available only during PROD bootstrap.",
            )

        claim = claim_admin_instance(
            operator_label=operator_label,
            claimed_via="admin_setup",
            claimed_from=_get_client_ip(self.request) or None,
        )
        return {
            "claimed": True,
            "claim": claim,
            "control_plane": build_control_plane_status(self.config),
        }

    def validate_section_payload(self, section: str, payload: dict[str, Any]) -> None:
        """Validate that a settings payload contains only known fields."""
        unknown = sorted(set(payload) - _SECTION_FIELDS[section])
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown {section} setting fields: {', '.join(unknown)}",
            )

    def build_application_payload(self) -> dict[str, Any]:
        """Return UI-facing application settings."""
        return {
            "section": "application",
            "values": _build_application_settings(self.config.proxy_settings),
            "control_plane": self._control_summary(),
        }

    async def update_application_settings(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Persist and optionally apply application settings."""
        self.validate_section_payload("application", payload)
        updated = _build_updated_config(self.config, proxy_updates=payload)
        result = await self._apply_updated_config(
            updated,
            changed_fields=set(payload),
        )
        return {
            "section": "application",
            "values": _build_application_settings(updated.proxy_settings),
            **result,
        }

    def build_observability_payload(self) -> dict[str, Any]:
        """Return UI-facing grouped observability settings."""
        return {
            "section": "observability",
            "values": ObservabilitySettings.from_proxy_settings(
                self.config.proxy_settings
            ).to_safe_payload(),
            "control_plane": self._control_summary(),
        }

    async def update_observability_settings(
        self,
        payload: ObservabilitySettingsUpdate,
    ) -> dict[str, Any]:
        """Persist and apply grouped observability settings."""
        proxy_updates = payload.to_proxy_updates()
        updated = _build_updated_config(self.config, proxy_updates=proxy_updates)
        result = await self._apply_updated_config(
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

    def build_gigachat_payload(self) -> dict[str, Any]:
        """Return UI-facing GigaChat settings with masked secrets."""
        return {
            "section": "gigachat",
            "values": _build_gigachat_settings(self.config.gigachat_settings),
            "control_plane": self._control_summary(),
        }

    async def update_gigachat_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Persist and apply GigaChat settings."""
        self.validate_section_payload("gigachat", payload)
        updated = _build_updated_config(self.config, gigachat_updates=payload)
        result = await self._apply_updated_config(
            updated,
            changed_fields=set(payload),
        )
        return {
            "section": "gigachat",
            "values": _build_gigachat_settings(updated.gigachat_settings),
            **result,
        }

    async def test_gigachat_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run a non-persistent upstream connectivity check with candidate settings."""
        self.validate_section_payload("gigachat", payload)
        updated = _build_updated_config(self.config, gigachat_updates=payload)
        logger = get_logger_from_state(self.state)
        gigachat_factory = self._resolve_gigachat_factory()
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
                "gigachat_api_mode": self.config.proxy_settings.gigachat_api_mode,
            }
        except Exception as exc:  # pragma: no cover - exercised in integration tests
            if logger is not None:
                logger.warning(f"GigaChat connection test failed: {exc}")
            return {
                "ok": False,
                "error_type": exc.__class__.__name__,
                "error": str(exc),
                "gigachat_api_mode": self.config.proxy_settings.gigachat_api_mode,
            }
        finally:
            close = getattr(client, "aclose", None)
            if callable(close):
                await close()

    def build_security_payload(self) -> dict[str, Any]:
        """Return UI-facing security settings."""
        return {
            "section": "security",
            "values": _build_security_settings(self.config.proxy_settings),
            "control_plane": self._control_summary(),
        }

    async def update_security_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Persist and optionally apply security settings."""
        self.validate_section_payload("security", payload)
        updated = _build_updated_config(self.config, proxy_updates=payload)
        result = await self._apply_updated_config(
            updated,
            changed_fields=set(payload),
        )
        return {
            "section": "security",
            "values": _build_security_settings(updated.proxy_settings),
            **result,
        }

    def build_revisions_payload(self, *, limit: int) -> dict[str, Any]:
        """Return recent control-plane revisions with safe diffs."""
        revisions = [
            self._build_revision_entry(payload)
            for payload in list_control_plane_revisions(limit=limit)
        ]
        return {
            "current": self._build_settings_snapshot(self.config),
            "revisions": revisions,
            "control_plane": self._control_summary(),
        }

    async def rollback_revision(self, revision_id: str) -> dict[str, Any]:
        """Rollback runtime settings to a previous persisted revision."""
        try:
            payload = load_control_plane_revision_payload(revision_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Revision not found") from exc

        updated = build_proxy_config_from_control_plane_payload(
            payload,
            env_path=self.config.env_path,
        )
        diff = _build_settings_diff(self.config, updated)
        changed_fields = _collect_changed_fields(self.config, updated)
        result = await self._apply_updated_config(
            updated,
            changed_fields=changed_fields,
            restored_from_revision_id=revision_id,
        )
        return {
            "rolled_back_revision_id": revision_id,
            "values": self._build_settings_snapshot(updated),
            "diff": diff,
            **result,
        }

    async def apply_updated_config(
        self,
        updated_config: ProxyConfig,
        *,
        changed_fields: set[str],
        restored_from_revision_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist the candidate config and apply live-safe changes."""
        return await self._apply_updated_config(
            updated_config,
            changed_fields=changed_fields,
            restored_from_revision_id=restored_from_revision_id,
        )

    def _control_summary(self) -> dict[str, Any]:
        """Return the current control-plane status summary."""
        return build_control_plane_status(self.config)

    def _build_settings_snapshot(self, config: ProxyConfig) -> dict[str, Any]:
        """Build the safe, UI-facing snapshot of all settings sections."""
        return {
            "application": _build_application_settings(config.proxy_settings),
            "observability": ObservabilitySettings.from_proxy_settings(
                config.proxy_settings
            ).to_safe_payload(),
            "gigachat": _build_gigachat_settings(config.gigachat_settings),
            "security": _build_security_settings(config.proxy_settings),
        }

    def _build_revision_entry(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Build a safe revision entry with a diff against the current config."""
        target = build_proxy_config_from_control_plane_payload(
            payload,
            env_path=self.config.env_path,
        )
        diff = _build_settings_diff(self.config, target)
        changed_fields = payload.get("change", {}).get("changed_fields") or sorted(
            _collect_changed_fields(self.config, target)
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
            "snapshot": self._build_settings_snapshot(target),
            "diff": diff,
        }

    async def _apply_updated_config(
        self,
        updated_config: ProxyConfig,
        *,
        changed_fields: set[str],
        restored_from_revision_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist the candidate config and apply live-safe changes."""
        logger = get_logger_from_state(self.state)
        persist_path = persist_control_plane_config(
            updated_config,
            changed_fields=changed_fields,
            restored_from_revision_id=restored_from_revision_id,
        )
        ensure_runtime_dependencies(self.state, config=updated_config, logger=logger)

        restart_required = bool(changed_fields & _RESTART_REQUIRED_FIELDS)
        if not restart_required and logger is not None:
            await reload_runtime_services(
                self.app,
                config=updated_config,
                logger=logger,
            )

        self.config = updated_config
        return {
            "persisted_path": str(persist_path),
            "restart_required": restart_required,
            "applied_runtime": not restart_required,
            "changed_fields": sorted(changed_fields),
        }

    def _resolve_gigachat_factory(self):
        """Resolve the active GigaChat client factory for admin test calls."""
        providers = get_runtime_providers(self.state)
        factory_getter = providers.gigachat_factory_getter
        if callable(factory_getter):
            return factory_getter()
        return providers.gigachat_factory


class AdminKeyManagementService:
    """Manage global and scoped gateway API keys for the admin UI."""

    def __init__(self, request: Request) -> None:
        self.request = request
        self.state = request.app.state
        self.control_plane = AdminControlPlaneSettingsService(request)

    def build_payload(self) -> dict[str, Any]:
        """Return global and scoped API-key metadata for the admin console."""
        config = get_config_from_state(self.state)
        proxy = config.proxy_settings
        usage = get_runtime_stores(self.state).usage_by_api_key
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

    async def rotate_global_key(self, *, value: str | None) -> dict[str, Any]:
        """Create or rotate the global API key."""
        key_value = value or secrets.token_urlsafe(24)
        current = get_config_from_state(self.state)
        updated = _build_updated_config(current, proxy_updates={"api_key": key_value})
        result = await self.control_plane.apply_updated_config(
            updated,
            changed_fields={"api_key"},
        )
        return {
            "global": {
                "value": key_value,
                "key_preview": _mask_secret(key_value),
            },
            "keys": self.build_payload(),
            **result,
        }

    async def create_scoped_key(
        self,
        *,
        name: str,
        key: str | None,
        providers: list[str] | None,
        endpoints: list[str] | None,
        models: list[str] | None,
    ) -> dict[str, Any]:
        """Create a scoped API key with provider, endpoint, and model filters."""
        current = get_config_from_state(self.state)
        scoped_api_keys = [
            item.model_dump() if hasattr(item, "model_dump") else dict(item)
            for item in current.proxy_settings.scoped_api_keys
        ]
        existing_names = {str(item.get("name")) for item in scoped_api_keys}
        if name in existing_names:
            raise HTTPException(
                status_code=409,
                detail=f"Scoped API key `{name}` already exists",
            )

        key_value = key or secrets.token_urlsafe(24)
        scoped_api_keys.append(
            {
                "name": name,
                "key": key_value,
                "providers": providers,
                "endpoints": endpoints,
                "models": models,
            }
        )
        updated = _build_updated_config(
            current,
            proxy_updates={"scoped_api_keys": scoped_api_keys},
        )
        result = await self.control_plane.apply_updated_config(
            updated,
            changed_fields={"scoped_api_keys"},
        )
        return {
            "scoped_key": {
                "name": name,
                "value": key_value,
                "key_preview": _mask_secret(key_value),
            },
            "keys": self.build_payload(),
            **result,
        }

    async def rotate_scoped_key(
        self,
        *,
        name: str,
        key: str | None,
    ) -> dict[str, Any]:
        """Rotate an existing scoped API key and return the new value once."""
        current = get_config_from_state(self.state)
        key_value = key or secrets.token_urlsafe(24)
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
        result = await self.control_plane.apply_updated_config(
            updated,
            changed_fields={"scoped_api_keys"},
        )
        return {
            "scoped_key": {
                "name": name,
                "value": key_value,
                "key_preview": _mask_secret(key_value),
            },
            "keys": self.build_payload(),
            **result,
        }

    async def delete_scoped_key(self, *, name: str) -> dict[str, Any]:
        """Delete a scoped API key by its UI-visible name."""
        current = get_config_from_state(self.state)
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
        result = await self.control_plane.apply_updated_config(
            updated,
            changed_fields={"scoped_api_keys"},
        )
        return {
            "deleted": name,
            "keys": self.build_payload(),
            **result,
        }
