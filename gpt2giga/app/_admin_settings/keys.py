"""API-key management service for the admin UI."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import HTTPException
from starlette.requests import Request

from gpt2giga.app.dependencies import get_config_from_state, get_runtime_stores
from gpt2giga.app._admin_settings.control_plane import (
    AdminControlPlaneSettingsService,
)
from gpt2giga.app._admin_settings.shared import _build_updated_config, _mask_secret


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
