"""OpenAPI tag names and display order."""

OPENAPI_TAG_OPENAI_CHAT_COMPLETIONS = "OpenAI / Chat Completions"
OPENAPI_TAG_OPENAI_RESPONSES = "OpenAI / Responses"
OPENAPI_TAG_OPENAI_EMBEDDINGS = "OpenAI / Embeddings"
OPENAPI_TAG_OPENAI_MODELS = "OpenAI / Models"
OPENAPI_TAG_OPENAI_FILES = "OpenAI / Files"
OPENAPI_TAG_OPENAI_BATCHES = "OpenAI / Batches"
OPENAPI_TAG_ANTHROPIC_MESSAGES = "Anthropic / Messages"
OPENAPI_TAG_ANTHROPIC_MESSAGE_BATCHES = "Anthropic / Message Batches"
OPENAPI_TAG_LITELLM_MODEL_INFO = "LiteLLM / Model Info"
OPENAPI_TAG_SYSTEM_HEALTH = "System / Health"
OPENAPI_TAG_SYSTEM_LOGS = "System / Logs"
OPENAPI_TAG_ADMIN_TRAFFIC_LOGS = "Admin / Traffic Logs"
OPENAPI_TAG_ADMIN_DEBUG_TRANSLATION = "Admin / Debug Translation"

_OPENAPI_TAGS_METADATA_BY_NAME = {
    OPENAPI_TAG_OPENAI_CHAT_COMPLETIONS: {
        "name": OPENAPI_TAG_OPENAI_CHAT_COMPLETIONS,
        "description": "OpenAI-compatible chat completion routes.",
    },
    OPENAPI_TAG_OPENAI_RESPONSES: {
        "name": OPENAPI_TAG_OPENAI_RESPONSES,
        "description": "OpenAI-compatible Responses API routes.",
    },
    OPENAPI_TAG_OPENAI_EMBEDDINGS: {
        "name": OPENAPI_TAG_OPENAI_EMBEDDINGS,
        "description": "OpenAI-compatible embeddings routes.",
    },
    OPENAPI_TAG_OPENAI_MODELS: {
        "name": OPENAPI_TAG_OPENAI_MODELS,
        "description": "OpenAI-compatible model discovery routes.",
    },
    OPENAPI_TAG_OPENAI_FILES: {
        "name": OPENAPI_TAG_OPENAI_FILES,
        "description": "OpenAI-compatible file routes.",
    },
    OPENAPI_TAG_OPENAI_BATCHES: {
        "name": OPENAPI_TAG_OPENAI_BATCHES,
        "description": "OpenAI-compatible batch routes.",
    },
    OPENAPI_TAG_ANTHROPIC_MESSAGES: {
        "name": OPENAPI_TAG_ANTHROPIC_MESSAGES,
        "description": "Anthropic-compatible Messages API routes.",
    },
    OPENAPI_TAG_ANTHROPIC_MESSAGE_BATCHES: {
        "name": OPENAPI_TAG_ANTHROPIC_MESSAGE_BATCHES,
        "description": "Anthropic-compatible Message Batches routes.",
    },
    OPENAPI_TAG_LITELLM_MODEL_INFO: {
        "name": OPENAPI_TAG_LITELLM_MODEL_INFO,
        "description": "LiteLLM-compatible model info routes.",
    },
    OPENAPI_TAG_SYSTEM_HEALTH: {
        "name": OPENAPI_TAG_SYSTEM_HEALTH,
        "description": "System health and readiness routes.",
    },
    OPENAPI_TAG_SYSTEM_LOGS: {
        "name": OPENAPI_TAG_SYSTEM_LOGS,
        "description": "Local development log inspection routes.",
    },
    OPENAPI_TAG_ADMIN_TRAFFIC_LOGS: {
        "name": OPENAPI_TAG_ADMIN_TRAFFIC_LOGS,
        "description": "Protected traffic log query and replay routes.",
    },
    OPENAPI_TAG_ADMIN_DEBUG_TRANSLATION: {
        "name": OPENAPI_TAG_ADMIN_DEBUG_TRANSLATION,
        "description": "Protected protocol translation debug routes.",
    },
}

_DEFAULT_OPENAPI_TAGS = [
    OPENAPI_TAG_OPENAI_CHAT_COMPLETIONS,
    OPENAPI_TAG_OPENAI_RESPONSES,
    OPENAPI_TAG_OPENAI_EMBEDDINGS,
    OPENAPI_TAG_OPENAI_MODELS,
    OPENAPI_TAG_ANTHROPIC_MESSAGES,
    OPENAPI_TAG_LITELLM_MODEL_INFO,
    OPENAPI_TAG_SYSTEM_HEALTH,
]


def build_openapi_tags_metadata(
    *,
    include_logs: bool,
    include_admin_logs: bool,
    include_debug_translation: bool,
) -> list[dict[str, str]]:
    """Build OpenAPI tag metadata for the routes mounted in this app."""
    tag_names = [*_DEFAULT_OPENAPI_TAGS]
    if include_logs:
        tag_names.append(OPENAPI_TAG_SYSTEM_LOGS)
    if include_admin_logs:
        tag_names.append(OPENAPI_TAG_ADMIN_TRAFFIC_LOGS)
    if include_debug_translation:
        tag_names.append(OPENAPI_TAG_ADMIN_DEBUG_TRANSLATION)
    return [_OPENAPI_TAGS_METADATA_BY_NAME[name] for name in tag_names]


OPENAPI_TAGS_METADATA = build_openapi_tags_metadata(
    include_logs=True,
    include_admin_logs=True,
    include_debug_translation=True,
)
