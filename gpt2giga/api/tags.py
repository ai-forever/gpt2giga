"""Shared OpenAPI tag names and ordering."""

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

OPENAPI_TAGS = [
    {
        "name": TAG_CHAT,
        "description": (
            "Text generation endpoints across OpenAI, Anthropic, and Gemini "
            "compatibility layers."
        ),
    },
    {
        "name": TAG_RESPONSES,
        "description": "OpenAI-compatible Responses API endpoints.",
    },
    {
        "name": TAG_EMBEDDINGS,
        "description": "Embedding creation endpoints across supported APIs.",
    },
    {
        "name": TAG_MODELS,
        "description": "Model discovery and model metadata endpoints.",
    },
    {
        "name": TAG_FILES,
        "description": "File upload, listing, retrieval, and content access endpoints.",
    },
    {
        "name": TAG_BATCHES,
        "description": "Batch creation, listing, retrieval, and results endpoints.",
    },
    {
        "name": TAG_COUNT_TOKENS,
        "description": "Token counting endpoints for Anthropic and Gemini compatibility.",
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
