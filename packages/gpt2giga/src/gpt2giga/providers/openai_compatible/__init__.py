"""OpenAI-compatible normalized upstream adapter."""

from gpt2giga.providers.openai_compatible.adapter import (
    DEFAULT_MAX_RESPONSE_BYTES,
    OPENAI_CHAT_COMPLETIONS_DIALECT,
    OPENAI_CHAT_EXECUTION_OWNER,
    OPENAI_COMPATIBLE_UPSTREAM_SCHEMA_VERSION,
    OpenAICompatibleNetworkAuthorization,
    OpenAICompatibleNetworkAuthorizer,
    OpenAICompatibleNetworkIntent,
    OpenAICompatibleProtocolError,
    OpenAICompatibleProviderAdapter,
    OpenAICompatibleUpstreamError,
    OpenAICompatibleUpstreamProfile,
    normalized_chat_to_openai_compatible_payload,
    openai_compatible_profile,
    openai_compatible_response_to_normalized,
    parse_openai_compatible_models,
)

__all__ = [
    "DEFAULT_MAX_RESPONSE_BYTES",
    "OPENAI_CHAT_COMPLETIONS_DIALECT",
    "OPENAI_CHAT_EXECUTION_OWNER",
    "OPENAI_COMPATIBLE_UPSTREAM_SCHEMA_VERSION",
    "OpenAICompatibleNetworkAuthorization",
    "OpenAICompatibleNetworkAuthorizer",
    "OpenAICompatibleNetworkIntent",
    "OpenAICompatibleProtocolError",
    "OpenAICompatibleProviderAdapter",
    "OpenAICompatibleUpstreamError",
    "OpenAICompatibleUpstreamProfile",
    "normalized_chat_to_openai_compatible_payload",
    "openai_compatible_profile",
    "openai_compatible_response_to_normalized",
    "parse_openai_compatible_models",
]
