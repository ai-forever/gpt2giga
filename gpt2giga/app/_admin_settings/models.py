"""Typed DTOs for admin settings requests."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from gpt2giga.core.config._settings.access_control import (
    GovernanceLimitSettings,
    ScopedAPIKeySettings,
)
from gpt2giga.core.config._settings.common import GigaChatAPIMode, ProviderName


class _AdminSettingsDTO(BaseModel):
    """Base DTO with strict extra-field validation."""

    model_config = ConfigDict(extra="forbid")

    def to_updates(self) -> dict[str, object]:
        """Return only explicitly provided update fields."""
        return self.model_dump(exclude_unset=True, mode="python")


class ClaimInstanceRequest(_AdminSettingsDTO):
    """Capture optional operator context for the first-run claim step."""

    operator_label: str | None = Field(default=None, min_length=1)


class ApplicationSettingsUpdate(_AdminSettingsDTO):
    """Partial update payload for application settings."""

    mode: Literal["DEV", "PROD"] | None = None
    host: str | None = None
    port: int | None = None
    use_https: bool | None = None
    https_key_file: str | None = None
    https_cert_file: str | None = None
    enabled_providers: list[ProviderName] | None = None
    gigachat_api_mode: GigaChatAPIMode | None = None
    gigachat_responses_api_mode: GigaChatAPIMode | None = None
    runtime_store_backend: str | None = None
    runtime_store_dsn: str | None = None
    runtime_store_namespace: str | None = None
    enable_telemetry: bool | None = None
    observability_sinks: list[str] | None = None
    recent_requests_max_items: int | None = None
    recent_errors_max_items: int | None = None
    embeddings: str | None = None
    pass_model: bool | None = None
    pass_token: bool | None = None
    enable_reasoning: bool | None = None
    max_request_body_bytes: int | None = None
    max_audio_file_size_bytes: int | None = None
    max_image_file_size_bytes: int | None = None
    max_text_file_size_bytes: int | None = None
    max_audio_image_total_size_bytes: int | None = None
    log_level: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] | None = None
    log_filename: str | None = None
    log_max_size: int | None = None
    log_redact_sensitive: bool | None = None


class GigaChatSettingsUpdate(_AdminSettingsDTO):
    """Partial update payload for GigaChat settings."""

    base_url: str | None = None
    auth_url: str | None = None
    credentials: str | None = None
    scope: str | None = None
    access_token: str | None = None
    model: str | None = None
    profanity_check: bool | None = None
    user: str | None = None
    password: str | None = None
    timeout: float | None = None
    verify_ssl_certs: bool | None = None
    ca_bundle_file: str | None = None
    cert_file: str | None = None
    key_file: str | None = None
    key_file_password: str | None = None
    flags: list[str] | None = None
    max_connections: int | None = None
    max_retries: int | None = None
    retry_backoff_factor: float | None = None
    retry_on_status_codes: list[int] | None = None
    token_expiry_buffer_ms: int | None = None


class SecuritySettingsUpdate(_AdminSettingsDTO):
    """Partial update payload for security settings."""

    enable_api_key_auth: bool | None = None
    api_key: str | None = None
    scoped_api_keys: list[ScopedAPIKeySettings] | None = None
    governance_limits: list[GovernanceLimitSettings] | None = None
    cors_allow_origins: list[str] | None = None
    cors_allow_methods: list[str] | None = None
    cors_allow_headers: list[str] | None = None
    logs_ip_allowlist: list[str] | None = None
