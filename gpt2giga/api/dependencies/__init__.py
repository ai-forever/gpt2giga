"""HTTP dependency providers."""

from gpt2giga.api.dependencies.auth import verify_api_key, verify_api_key_gemini

__all__ = ["verify_api_key", "verify_api_key_gemini"]
