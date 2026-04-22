"""Control-plane settings service for the admin UI."""

from __future__ import annotations

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
from gpt2giga.app.runtime_backends import list_runtime_backend_descriptors
from gpt2giga.app.wiring import reload_runtime_services
from gpt2giga.core.config.control_plane import (
    build_control_plane_status,
    build_proxy_config_from_control_plane_payload,
    claim_admin_instance,
    list_control_plane_revisions,
    load_control_plane_revision_payload,
    persist_control_plane_config,
)
from gpt2giga.core.config.observability import (
    ObservabilitySettings,
    ObservabilitySettingsUpdate,
)
from gpt2giga.core.config.settings import ProxyConfig

from gpt2giga.app._admin_settings.models import (
    ApplicationSettingsUpdate,
    GigaChatSettingsUpdate,
    SecuritySettingsUpdate,
)
from gpt2giga.app._admin_settings.shared import (
    _RESTART_REQUIRED_FIELDS,
    _build_application_settings_payload,
    _build_gigachat_settings,
    _build_security_settings,
    _build_settings_diff,
    _build_updated_config,
    _collect_changed_fields,
    _get_client_ip,
)


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
        self._ensure_persistence_enabled()
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

    def build_application_payload(self) -> dict[str, Any]:
        """Return UI-facing application settings."""
        stores = get_runtime_stores(self.state)
        return {
            "section": "application",
            "values": _build_application_settings_payload(
                self.config.proxy_settings,
                active_backend=stores.backend.name
                if stores.backend is not None
                else None,
            ),
            "control_plane": self._control_summary(),
        }

    async def update_application_settings(
        self,
        payload: ApplicationSettingsUpdate,
    ) -> dict[str, Any]:
        """Persist and optionally apply application settings."""
        updates = payload.to_updates()
        requested_backend = str(updates.get("runtime_store_backend") or "").strip()
        if requested_backend and requested_backend not in {
            descriptor.name for descriptor in list_runtime_backend_descriptors()
        }:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Runtime store backend "
                    f"`{requested_backend}` is not added in this build. "
                    "Use one of the registered backends or register a custom backend first."
                ),
            )
        updated = _build_updated_config(self.config, proxy_updates=updates)
        result = await self._apply_updated_config(
            updated,
            changed_fields=set(updates),
        )
        stores = get_runtime_stores(self.state)
        return {
            "section": "application",
            "values": _build_application_settings_payload(
                updated.proxy_settings,
                active_backend=stores.backend.name
                if stores.backend is not None
                else None,
            ),
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

    async def update_gigachat_settings(
        self,
        payload: GigaChatSettingsUpdate,
    ) -> dict[str, Any]:
        """Persist and apply GigaChat settings."""
        updates = payload.to_updates()
        updated = _build_updated_config(self.config, gigachat_updates=updates)
        result = await self._apply_updated_config(
            updated,
            changed_fields=set(updates),
        )
        return {
            "section": "gigachat",
            "values": _build_gigachat_settings(updated.gigachat_settings),
            **result,
        }

    async def test_gigachat_settings(
        self,
        payload: GigaChatSettingsUpdate,
    ) -> dict[str, Any]:
        """Run a non-persistent upstream connectivity check with candidate settings."""
        updated = _build_updated_config(
            self.config,
            gigachat_updates=payload.to_updates(),
        )
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

    async def update_security_settings(
        self,
        payload: SecuritySettingsUpdate,
    ) -> dict[str, Any]:
        """Persist and optionally apply security settings."""
        updates = payload.to_updates()
        updated = _build_updated_config(self.config, proxy_updates=updates)
        result = await self._apply_updated_config(
            updated,
            changed_fields=set(updates),
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
        self._ensure_persistence_enabled()
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

    def _ensure_persistence_enabled(self) -> None:
        """Reject admin mutations when env-only config mode is enabled."""
        if not self.config.proxy_settings.disable_persist:
            return
        raise HTTPException(
            status_code=409,
            detail=(
                "Control-plane persistence is disabled. Update .env or container "
                "environment variables and restart the process."
            ),
        )

    def _build_settings_snapshot(self, config: ProxyConfig) -> dict[str, Any]:
        """Build the safe, UI-facing snapshot of all settings sections."""
        stores = get_runtime_stores(self.state)
        return {
            "application": _build_application_settings_payload(
                config.proxy_settings,
                active_backend=stores.backend.name
                if stores.backend is not None
                else None,
            ),
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
        self._ensure_persistence_enabled()
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
