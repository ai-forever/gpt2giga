"""Consolidated security configuration model.

Groups all security-related parameters from ProxySettings into a single
view-model so that security posture can be inspected and validated in one place.
"""

from typing import Optional

from pydantic import BaseModel, Field

from gpt2giga.constants import (
    DEFAULT_MAX_AUDIO_FILE_SIZE_BYTES,
    DEFAULT_MAX_AUDIO_IMAGE_TOTAL_SIZE_BYTES,
    DEFAULT_MAX_IMAGE_FILE_SIZE_BYTES,
    DEFAULT_MAX_TEXT_FILE_SIZE_BYTES,
    DEFAULT_MAX_REQUEST_BODY_BYTES,
)


class SecuritySettings(BaseModel):
    """Read-only view of all security-related proxy settings.

    Constructed from ``ProxySettings.security`` property so that security
    posture can be reviewed, logged, or validated in a single object without
    touching transport / feature-flag fields.
    """

    # --- Authentication ---
    enable_api_key_auth: bool = Field(
        default=False,
        description="Require API key on all endpoints.",
    )
    api_key: Optional[str] = Field(
        default=None,
        description="API key value (masked in repr).",
        repr=False,
    )

    # --- CORS ---
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["*"])
    cors_allow_methods: list[str] = Field(default_factory=lambda: ["*"])
    cors_allow_headers: list[str] = Field(default_factory=lambda: ["*"])

    # --- Logs access ---
    logs_ip_allowlist: list[str] = Field(default_factory=list)
    log_redact_sensitive: bool = Field(default=True)

    # --- Request / attachment size limits ---
    max_request_body_bytes: int = Field(
        default=DEFAULT_MAX_REQUEST_BODY_BYTES,
        description="Global limit for raw HTTP request body (before JSON parse).",
    )
    max_audio_file_size_bytes: int = Field(
        default=DEFAULT_MAX_AUDIO_FILE_SIZE_BYTES,
    )
    max_image_file_size_bytes: int = Field(
        default=DEFAULT_MAX_IMAGE_FILE_SIZE_BYTES,
    )
    max_text_file_size_bytes: int = Field(
        default=DEFAULT_MAX_TEXT_FILE_SIZE_BYTES,
    )
    max_audio_image_total_size_bytes: int = Field(
        default=DEFAULT_MAX_AUDIO_IMAGE_TOTAL_SIZE_BYTES,
    )

    # --- Runtime mode ---
    mode: str = Field(default="DEV")

    # --- Derived helpers ---
    @property
    def is_prod(self) -> bool:
        """Return True when running in PROD mode."""
        return self.mode == "PROD"

    @property
    def auth_required(self) -> bool:
        """Return True when API-key auth must be enforced."""
        return self.enable_api_key_auth or self.is_prod

    @property
    def has_wildcard_cors(self) -> bool:
        """Return True if CORS origins contain a wildcard."""
        return "*" in self.cors_allow_origins

    def summary(self) -> dict:
        """Return a safe-to-log dictionary (no secrets)."""
        return {
            "mode": self.mode,
            "auth_required": self.auth_required,
            "api_key_configured": self.api_key is not None,
            "cors_allow_origins": self.cors_allow_origins,
            "has_wildcard_cors": self.has_wildcard_cors,
            "log_redact_sensitive": self.log_redact_sensitive,
            "logs_ip_allowlist": self.logs_ip_allowlist,
            "max_request_body_bytes": self.max_request_body_bytes,
            "max_audio_file_size_bytes": self.max_audio_file_size_bytes,
            "max_image_file_size_bytes": self.max_image_file_size_bytes,
            "max_text_file_size_bytes": self.max_text_file_size_bytes,
            "max_audio_image_total_size_bytes": self.max_audio_image_total_size_bytes,
        }
