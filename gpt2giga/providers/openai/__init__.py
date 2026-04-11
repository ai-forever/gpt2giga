"""OpenAI-compatible provider adapters and descriptor."""

from gpt2giga.providers.openai.capabilities import (
    OPENAI_PROVIDER_DESCRIPTOR,
    openai_provider_adapters,
)

__all__ = ["OPENAI_PROVIDER_DESCRIPTOR", "openai_provider_adapters"]
