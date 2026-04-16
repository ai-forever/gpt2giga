"""Typed runtime-store settings models for internal config grouping."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class RuntimeStoreSettings(BaseModel):
    """Grouped runtime-store settings derived from flat proxy fields."""

    backend: str = "memory"
    dsn: str | None = None
    namespace: str = "gpt2giga"

    @classmethod
    def from_proxy_settings(cls, proxy: Any) -> RuntimeStoreSettings:
        """Build the grouped runtime-store settings from flat proxy settings."""
        return cls(
            backend=str(getattr(proxy, "runtime_store_backend", "memory") or "memory"),
            dsn=getattr(proxy, "runtime_store_dsn", None),
            namespace=str(
                getattr(proxy, "runtime_store_namespace", "gpt2giga") or "gpt2giga"
            ),
        )

    @property
    def dsn_configured(self) -> bool:
        """Return whether an explicit runtime-store DSN is configured."""
        return self.dsn is not None

    @property
    def durable(self) -> bool:
        """Return whether the backend persists state outside process memory."""
        return self.backend != "memory"
