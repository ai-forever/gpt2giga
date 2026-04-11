"""Gemini-compatible provider adapters and descriptor."""

from gpt2giga.providers.gemini.capabilities import (
    GEMINI_PROVIDER_DESCRIPTOR,
    gemini_provider_adapters,
)

__all__ = ["GEMINI_PROVIDER_DESCRIPTOR", "gemini_provider_adapters"]
