"""Typed observability settings models for the control plane."""

from __future__ import annotations

from typing import Any, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


def _normalize_sink_names(value: Any) -> list[str]:
    """Normalize observability sink names from API-friendly forms."""
    if value is None:
        return []

    def _normalize_parts(parts: list[str]) -> list[str]:
        normalized = [part.strip().lower() for part in parts if part.strip()]
        if not normalized:
            return []
        if any(part in {"off", "none", "disabled"} for part in normalized):
            return []
        return list(dict.fromkeys(normalized))

    if isinstance(value, str):
        return _normalize_parts(value.split(","))

    if isinstance(value, (list, tuple, set)):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.extend(item.split(","))
            else:
                raise TypeError("observability sinks must be strings")
        return _normalize_parts(parts)

    raise TypeError("observability sinks must be a string or list of strings")


class OtlpSettings(BaseModel):
    """Typed OTLP sink settings."""

    traces_endpoint: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = 5.0
    max_pending_requests: int = 256
    service_name: str = "gpt2giga"

    def to_safe_payload(self) -> dict[str, Any]:
        """Return a safe UI-facing representation of the OTLP settings."""
        return {
            "traces_endpoint": self.traces_endpoint,
            "headers_configured": bool(self.headers),
            "header_names": sorted(self.headers),
            "timeout_seconds": self.timeout_seconds,
            "max_pending_requests": self.max_pending_requests,
            "service_name": self.service_name,
        }


class LangfuseSettings(BaseModel):
    """Typed Langfuse sink settings."""

    base_url: str | None = None
    public_key: str | None = Field(default=None, repr=False)
    secret_key: str | None = Field(default=None, repr=False)

    def to_safe_payload(self) -> dict[str, Any]:
        """Return a safe UI-facing representation of the Langfuse settings."""
        return {
            "base_url": self.base_url,
            "public_key_configured": self.public_key is not None,
            "public_key_preview": _mask_secret(self.public_key),
            "secret_key_configured": self.secret_key is not None,
            "secret_key_preview": _mask_secret(self.secret_key),
        }


class PhoenixSettings(BaseModel):
    """Typed Phoenix sink settings."""

    base_url: str | None = None
    api_key: str | None = Field(default=None, repr=False)
    project_name: str | None = None

    def to_safe_payload(self) -> dict[str, Any]:
        """Return a safe UI-facing representation of the Phoenix settings."""
        return {
            "base_url": self.base_url,
            "api_key_configured": self.api_key is not None,
            "api_key_preview": _mask_secret(self.api_key),
            "project_name": self.project_name,
        }


class ObservabilitySettings(BaseModel):
    """Typed observability settings grouped for admin/control-plane flows."""

    enable_telemetry: bool = True
    active_sinks: list[str] = Field(default_factory=lambda: ["prometheus"])
    otlp: OtlpSettings = Field(default_factory=OtlpSettings)
    langfuse: LangfuseSettings = Field(default_factory=LangfuseSettings)
    phoenix: PhoenixSettings = Field(default_factory=PhoenixSettings)

    @classmethod
    def from_proxy_settings(cls, proxy: Any) -> ObservabilitySettings:
        """Build the grouped observability settings from flat proxy settings."""
        return cls(
            enable_telemetry=bool(getattr(proxy, "enable_telemetry", True)),
            active_sinks=list(getattr(proxy, "observability_sinks", ["prometheus"])),
            otlp=OtlpSettings(
                traces_endpoint=getattr(proxy, "otlp_traces_endpoint", None),
                headers=dict(getattr(proxy, "otlp_headers", {}) or {}),
                timeout_seconds=float(
                    getattr(proxy, "otlp_timeout_seconds", 5.0) or 5.0
                ),
                max_pending_requests=int(
                    getattr(proxy, "otlp_max_pending_requests", 256) or 256
                ),
                service_name=str(
                    getattr(proxy, "otlp_service_name", "gpt2giga") or "gpt2giga"
                ),
            ),
            langfuse=LangfuseSettings(
                base_url=getattr(proxy, "langfuse_base_url", None),
                public_key=getattr(proxy, "langfuse_public_key", None),
                secret_key=getattr(proxy, "langfuse_secret_key", None),
            ),
            phoenix=PhoenixSettings(
                base_url=getattr(proxy, "phoenix_base_url", None),
                api_key=getattr(proxy, "phoenix_api_key", None),
                project_name=getattr(proxy, "phoenix_project_name", None),
            ),
        )

    @property
    def metrics_enabled(self) -> bool:
        """Return whether Prometheus metrics are effectively enabled."""
        return self.enable_telemetry and "prometheus" in set(self.active_sinks)

    def to_safe_payload(self) -> dict[str, Any]:
        """Return a safe UI-facing representation of grouped observability settings."""
        otlp_payload = self.otlp.to_safe_payload()
        langfuse_payload = self.langfuse.to_safe_payload()
        phoenix_payload = self.phoenix.to_safe_payload()
        return {
            "enable_telemetry": self.enable_telemetry,
            "active_sinks": list(self.active_sinks),
            "metrics_enabled": self.metrics_enabled,
            "otlp": otlp_payload,
            "langfuse": langfuse_payload,
            "phoenix": phoenix_payload,
            "sinks": [
                {
                    "id": "prometheus",
                    "label": "Prometheus",
                    "enabled": "prometheus" in set(self.active_sinks),
                    "configured": True,
                    "live_apply": True,
                    "restart_required": False,
                    "required_fields": [],
                    "missing_fields": [],
                    "settings": {
                        "metrics_endpoint": "/metrics",
                        "admin_metrics_endpoint": "/admin/api/metrics",
                    },
                },
                {
                    "id": "otlp",
                    "label": "OTLP/HTTP",
                    "enabled": "otlp" in set(self.active_sinks),
                    "configured": bool(self.otlp.traces_endpoint),
                    "live_apply": True,
                    "restart_required": False,
                    "required_fields": ["traces_endpoint"],
                    "missing_fields": (
                        [] if self.otlp.traces_endpoint else ["traces_endpoint"]
                    ),
                    "settings": otlp_payload,
                },
                {
                    "id": "langfuse",
                    "label": "Langfuse",
                    "enabled": "langfuse" in set(self.active_sinks),
                    "configured": bool(
                        self.langfuse.base_url
                        and self.langfuse.public_key
                        and self.langfuse.secret_key
                    ),
                    "live_apply": True,
                    "restart_required": False,
                    "required_fields": ["base_url", "public_key", "secret_key"],
                    "missing_fields": [
                        field
                        for field, value in {
                            "base_url": self.langfuse.base_url,
                            "public_key": self.langfuse.public_key,
                            "secret_key": self.langfuse.secret_key,
                        }.items()
                        if not value
                    ],
                    "settings": langfuse_payload,
                },
                {
                    "id": "phoenix",
                    "label": "Phoenix",
                    "enabled": "phoenix" in set(self.active_sinks),
                    "configured": bool(self.phoenix.base_url),
                    "live_apply": True,
                    "restart_required": False,
                    "required_fields": ["base_url"],
                    "missing_fields": [] if self.phoenix.base_url else ["base_url"],
                    "settings": phoenix_payload,
                },
            ],
        }


class OtlpSettingsUpdate(BaseModel):
    """Partial OTLP settings update."""

    model_config = ConfigDict(extra="forbid")

    traces_endpoint: str | None = None
    headers: dict[str, str] | None = None
    timeout_seconds: float | None = None
    max_pending_requests: int | None = None
    service_name: str | None = None

    def to_proxy_updates(self) -> dict[str, Any]:
        """Convert the partial update into flat proxy settings."""
        values = self.model_dump(exclude_unset=True)
        field_map = {
            "traces_endpoint": "otlp_traces_endpoint",
            "headers": "otlp_headers",
            "timeout_seconds": "otlp_timeout_seconds",
            "max_pending_requests": "otlp_max_pending_requests",
            "service_name": "otlp_service_name",
        }
        return {field_map[key]: value for key, value in values.items()}


class LangfuseSettingsUpdate(BaseModel):
    """Partial Langfuse settings update."""

    model_config = ConfigDict(extra="forbid")

    base_url: str | None = None
    public_key: str | None = None
    secret_key: str | None = None

    def to_proxy_updates(self) -> dict[str, Any]:
        """Convert the partial update into flat proxy settings."""
        values = self.model_dump(exclude_unset=True)
        field_map = {
            "base_url": "langfuse_base_url",
            "public_key": "langfuse_public_key",
            "secret_key": "langfuse_secret_key",
        }
        return {field_map[key]: value for key, value in values.items()}


class PhoenixSettingsUpdate(BaseModel):
    """Partial Phoenix settings update."""

    model_config = ConfigDict(extra="forbid")

    base_url: str | None = None
    api_key: str | None = None
    project_name: str | None = None

    def to_proxy_updates(self) -> dict[str, Any]:
        """Convert the partial update into flat proxy settings."""
        values = self.model_dump(exclude_unset=True)
        field_map = {
            "base_url": "phoenix_base_url",
            "api_key": "phoenix_api_key",
            "project_name": "phoenix_project_name",
        }
        return {field_map[key]: value for key, value in values.items()}


class ObservabilitySettingsUpdate(BaseModel):
    """Partial grouped observability settings update."""

    model_config = ConfigDict(extra="forbid")

    enable_telemetry: bool | None = None
    active_sinks: list[str] | None = None
    otlp: OtlpSettingsUpdate | None = None
    langfuse: LangfuseSettingsUpdate | None = None
    phoenix: PhoenixSettingsUpdate | None = None

    @field_validator("active_sinks", mode="before")
    @classmethod
    def normalize_active_sinks(cls, value: Any) -> list[str] | None:
        """Normalize sink names for API updates."""
        if value is None:
            return None
        return _normalize_sink_names(value)

    def to_proxy_updates(self) -> dict[str, Any]:
        """Convert the grouped update into flat proxy settings."""
        updates: dict[str, Any] = {}
        if "enable_telemetry" in self.model_fields_set:
            updates["enable_telemetry"] = self.enable_telemetry
        if "active_sinks" in self.model_fields_set:
            updates["observability_sinks"] = list(self.active_sinks or [])
        if self.otlp is not None:
            updates.update(self.otlp.to_proxy_updates())
        if self.langfuse is not None:
            updates.update(self.langfuse.to_proxy_updates())
        if self.phoenix is not None:
            updates.update(self.phoenix.to_proxy_updates())
        return updates
