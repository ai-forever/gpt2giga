"""Compatibility wrapper for core security configuration."""

from gpt2giga.core.config.security import SecuritySettings
from gpt2giga.core.constants import DEFAULT_MAX_REQUEST_BODY_BYTES

__all__ = ["DEFAULT_MAX_REQUEST_BODY_BYTES", "SecuritySettings"]
