"""OpenAPI helpers for Gemini-compatible endpoints."""

from typing import Any

from gpt2giga.openapi_specs.common import _request_body_oneof


def gemini_generate_content_openapi_extra(*, streaming: bool) -> dict[str, Any]:
    """OpenAPI extras for Gemini generateContent endpoints."""
    schema = {
        "title": "GeminiGenerateContentRequest",
        "type": "object",
        "required": ["contents"],
        "properties": {
            "contents": {
                "type": "array",
                "description": "Conversation contents using Gemini Content/Part shape.",
                "items": {"type": "object", "additionalProperties": True},
            },
            "systemInstruction": {
                "type": "object",
                "description": "Gemini system instruction. Text parts are mapped to a system message.",
                "additionalProperties": True,
            },
            "generationConfig": {
                "type": "object",
                "description": (
                    "Supported fields include temperature, topP, maxOutputTokens, "
                    "stopSequences, seed, presencePenalty, frequencyPenalty, "
                    "responseMimeType, responseSchema, and responseJsonSchema."
                ),
                "additionalProperties": True,
            },
            "tools": {
                "type": "array",
                "description": "Function declarations are mapped to normalized tools.",
                "items": {"type": "object", "additionalProperties": True},
            },
            "toolConfig": {
                "type": "object",
                "description": "Function calling config; supported best effort.",
                "additionalProperties": True,
            },
            "safetySettings": {
                "type": "array",
                "description": "Accepted and preserved for diagnostics; not enforced by GigaChat.",
                "items": {"type": "object", "additionalProperties": True},
            },
        },
        "additionalProperties": True,
    }
    method_name = "streamGenerateContent" if streaming else "generateContent"
    return _request_body_oneof(
        minimal_schema=schema,
        full_schema=schema,
        minimal_example={"contents": [{"parts": [{"text": "Hello from Gemini API"}]}]},
        full_example={
            "systemInstruction": {"parts": [{"text": "Be concise."}]},
            "contents": [{"role": "user", "parts": [{"text": "Write a haiku."}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 64},
        },
        description=(
            f"Gemini-compatible `{method_name}` request. The gateway executes the "
            "request through GigaChat and maps the response back to Gemini shape."
        ),
    )


def gemini_count_tokens_openapi_extra() -> dict[str, Any]:
    """OpenAPI extras for Gemini countTokens."""
    schema = {
        "title": "GeminiCountTokensRequest",
        "type": "object",
        "properties": {
            "contents": {"type": "array", "items": {"type": "object"}},
            "generateContentRequest": {"type": "object", "additionalProperties": True},
        },
        "additionalProperties": True,
    }
    return _request_body_oneof(
        minimal_schema=schema,
        full_schema=schema,
        minimal_example={"contents": [{"parts": [{"text": "Hello"}]}]},
        full_example={
            "generateContentRequest": {
                "contents": [{"parts": [{"text": "Hello"}]}],
                "systemInstruction": {"parts": [{"text": "Count me too."}]},
            }
        },
        description="Gemini-compatible token counting request.",
    )


def gemini_embed_content_openapi_extra(*, batch: bool) -> dict[str, Any]:
    """OpenAPI extras for Gemini embedding endpoints."""
    if batch:
        schema = {
            "title": "GeminiBatchEmbedContentRequest",
            "type": "object",
            "required": ["requests"],
            "properties": {
                "requests": {
                    "type": "array",
                    "items": {"type": "object", "additionalProperties": True},
                }
            },
            "additionalProperties": True,
        }
        example = {
            "requests": [
                {"content": {"parts": [{"text": "first"}]}},
                {"content": {"parts": [{"text": "second"}]}},
            ]
        }
    else:
        schema = {
            "title": "GeminiEmbedContentRequest",
            "type": "object",
            "required": ["content"],
            "properties": {
                "content": {"type": "object", "additionalProperties": True},
                "taskType": {"type": "string"},
                "outputDimensionality": {"type": "integer"},
            },
            "additionalProperties": True,
        }
        example = {"content": {"parts": [{"text": "Embed this"}]}}
    return _request_body_oneof(
        minimal_schema=schema,
        full_schema=schema,
        minimal_example=example,
        full_example=example,
        description="Gemini-compatible embeddings request.",
    )


def gemini_models_openapi_extra(*, list_models: bool) -> dict[str, Any]:
    """OpenAPI extras for Gemini model discovery."""
    return {
        "description": (
            "List Gemini-style model resources backed by GigaChat."
            if list_models
            else "Return one Gemini-style model resource backed by GigaChat."
        )
    }


def gemini_files_openapi_extra() -> dict[str, Any]:
    """OpenAPI extras for prepared Gemini Files routes."""
    return {
        "description": (
            "Prepared Gemini Files API route. The default public Gemini router omits "
            "file routes until batch/file execution is validated end to end."
        )
    }


def gemini_batches_openapi_extra(*, create: bool) -> dict[str, Any]:
    """OpenAPI extras for prepared Gemini Batch routes."""
    return {
        "description": (
            "Prepared Gemini Batch API create route. The default public Gemini router "
            "omits batch routes until execution semantics are validated."
            if create
            else "Prepared Gemini Batch API metadata route."
        )
    }
