"""Shared OpenAPI tag names and ordering."""

from __future__ import annotations

from collections.abc import Collection

TAG_CHAT = "Chat"
TAG_RESPONSES = "Responses"
TAG_EMBEDDINGS = "Embeddings"
TAG_MODELS = "Models"
TAG_FILES = "Files"
TAG_BATCHES = "Batches"
TAG_COUNT_TOKENS = "Count Tokens"
TAG_TRANSLATIONS = "Translations"
TAG_SYSTEM = "System"
TAG_ADMIN = "Admin"

PROVIDER_OPENAI = "OpenAI"
PROVIDER_ANTHROPIC = "Anthropic"
PROVIDER_GEMINI = "Gemini"

_PROVIDER_ORDER = (
    PROVIDER_OPENAI,
    PROVIDER_ANTHROPIC,
    PROVIDER_GEMINI,
)
_PROVIDER_KEYS = {
    PROVIDER_OPENAI: "openai",
    PROVIDER_ANTHROPIC: "anthropic",
    PROVIDER_GEMINI: "gemini",
}
_CAPABILITY_ORDER = (
    TAG_CHAT,
    TAG_RESPONSES,
    TAG_EMBEDDINGS,
    TAG_MODELS,
    TAG_FILES,
    TAG_BATCHES,
    TAG_COUNT_TOKENS,
)
_PROVIDER_CAPABILITY_DESCRIPTIONS = {
    PROVIDER_OPENAI: {
        TAG_CHAT: "OpenAI-compatible chat completion endpoints.",
        TAG_RESPONSES: "OpenAI-compatible Responses API endpoints.",
        TAG_EMBEDDINGS: "OpenAI-compatible embedding creation endpoints.",
        TAG_MODELS: (
            "OpenAI-compatible model discovery endpoints, including LiteLLM "
            "model-info routes."
        ),
        TAG_FILES: "OpenAI-compatible file upload and retrieval endpoints.",
        TAG_BATCHES: "OpenAI-compatible batch creation and retrieval endpoints.",
    },
    PROVIDER_ANTHROPIC: {
        TAG_CHAT: "Anthropic Messages API compatible endpoints.",
        TAG_BATCHES: "Anthropic message batch endpoints.",
        TAG_COUNT_TOKENS: "Anthropic token counting endpoints.",
    },
    PROVIDER_GEMINI: {
        TAG_CHAT: "Gemini Developer API content generation endpoints.",
        TAG_EMBEDDINGS: "Gemini Developer API embedding endpoints.",
        TAG_MODELS: "Gemini Developer API model discovery endpoints.",
        TAG_FILES: "Gemini Developer API file upload and retrieval endpoints.",
        TAG_BATCHES: "Gemini Developer API batch endpoints.",
        TAG_COUNT_TOKENS: "Gemini Developer API token counting endpoints.",
    },
}
_STATIC_OPENAPI_TAGS = [
    {
        "name": TAG_BATCHES,
        "description": (
            "Standalone batch validation endpoint for OpenAI, Anthropic, and Gemini "
            "input payloads. It inspects staged files or inline request rows and "
            "returns diagnostics without creating an upstream batch job."
        ),
    },
    {
        "name": TAG_TRANSLATIONS,
        "description": (
            "Provider-to-provider request translation endpoints that convert one "
            "compatibility payload into another without calling the upstream API."
        ),
    },
    {
        "name": TAG_SYSTEM,
        "description": "Health and metrics endpoints.",
    },
    {
        "name": TAG_ADMIN,
        "description": "Operator and runtime administration endpoints.",
    },
]
_TAG_PROVIDER_ALIASES = {
    "openai": "openai",
    "anthropic": "anthropic",
    "gemini": "gemini",
    "litellm": "openai",
    "system": "system",
    "admin": "admin",
}


def provider_tag(capability: str, provider: str) -> str:
    """Build a provider-scoped OpenAPI tag."""
    return f"{capability} {provider}"


def build_openapi_tags(enabled_providers: Collection[str]) -> list[dict[str, str]]:
    """Build ordered OpenAPI tag metadata for the enabled providers."""
    enabled = set(enabled_providers)
    tags: list[dict[str, str]] = []
    for capability in _CAPABILITY_ORDER:
        for provider in _PROVIDER_ORDER:
            provider_key = _PROVIDER_KEYS[provider]
            if provider_key not in enabled:
                continue
            description = _PROVIDER_CAPABILITY_DESCRIPTIONS[provider].get(capability)
            if description is None:
                continue
            tags.append(
                {
                    "name": provider_tag(capability, provider),
                    "description": description,
                }
            )
    return [*tags, *_STATIC_OPENAPI_TAGS]


def resolve_tag_provider(tag: str) -> str | None:
    """Resolve a normalized provider key from a route tag."""
    normalized = tag.strip().lower()
    aliased = _TAG_PROVIDER_ALIASES.get(normalized)
    if aliased is not None:
        return aliased
    for provider, provider_key in _PROVIDER_KEYS.items():
        if normalized.endswith(f" {provider.lower()}"):
            return provider_key
    return None


OPENAPI_TAGS = build_openapi_tags(_PROVIDER_KEYS.values())
