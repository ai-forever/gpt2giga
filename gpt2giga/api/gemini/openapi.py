"""OpenAPI helpers for Gemini-compatible endpoints."""

from typing import Any

from gpt2giga.api._openapi import _request_body_oneof


def gemini_generate_content_openapi_extra() -> dict[str, Any]:
    """OpenAPI extras for Gemini generateContent."""
    minimal_properties: dict[str, Any] = {
        "contents": {
            "description": "Gemini content payload.",
            "oneOf": [
                {"type": "string"},
                {"type": "array", "items": {"type": "object"}},
                {"type": "object"},
            ],
        }
    }
    minimal_schema: dict[str, Any] = {
        "title": "GeminiGenerateContentMinimal",
        "type": "object",
        "required": ["contents"],
        "properties": minimal_properties,
        "additionalProperties": True,
    }
    full_schema: dict[str, Any] = {
        "title": "GeminiGenerateContentFull",
        "type": "object",
        "required": ["contents"],
        "properties": {
            **minimal_properties,
            "systemInstruction": {"type": "object", "additionalProperties": True},
            "generationConfig": {"type": "object", "additionalProperties": True},
            "tools": {"type": "array", "items": {"type": "object"}},
            "toolConfig": {"type": "object", "additionalProperties": True},
        },
        "additionalProperties": True,
    }
    return _request_body_oneof(
        minimal_schema=minimal_schema,
        full_schema=full_schema,
        minimal_example={
            "contents": [{"role": "user", "parts": [{"text": "Say hello"}]}]
        },
        full_example={
            "systemInstruction": {"parts": [{"text": "You are concise."}]},
            "contents": [{"role": "user", "parts": [{"text": "Return JSON"}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": {
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                    "required": ["answer"],
                },
            },
        },
        description="Gemini Developer API compatible request body.",
    )


def gemini_count_tokens_openapi_extra() -> dict[str, Any]:
    """OpenAPI extras for Gemini countTokens."""
    contents_schema: dict[str, Any] = {
        "type": "array",
        "items": {"type": "object", "additionalProperties": True},
    }
    minimal_schema: dict[str, Any] = {
        "title": "GeminiCountTokensMinimal",
        "type": "object",
        "required": ["contents"],
        "properties": {"contents": contents_schema},
        "additionalProperties": True,
    }
    full_schema: dict[str, Any] = {
        "title": "GeminiCountTokensFull",
        "type": "object",
        "properties": {
            "contents": contents_schema,
            "generateContentRequest": {
                "type": "object",
                "additionalProperties": True,
            },
        },
        "additionalProperties": True,
    }
    return _request_body_oneof(
        minimal_schema=minimal_schema,
        full_schema=full_schema,
        minimal_example={
            "contents": [{"role": "user", "parts": [{"text": "Count me"}]}]
        },
        full_example={
            "generateContentRequest": {
                "systemInstruction": {"parts": [{"text": "You are concise."}]},
                "contents": [{"role": "user", "parts": [{"text": "Count me"}]}],
            }
        },
        description="Gemini countTokens-compatible request body.",
    )


def gemini_batch_embed_contents_openapi_extra() -> dict[str, Any]:
    """OpenAPI extras for Gemini batchEmbedContents."""
    requests_schema: dict[str, Any] = {
        "type": "array",
        "items": {"type": "object", "additionalProperties": True},
    }
    minimal_schema: dict[str, Any] = {
        "title": "GeminiBatchEmbedContentsMinimal",
        "type": "object",
        "required": ["requests"],
        "properties": {"requests": requests_schema},
        "additionalProperties": True,
    }
    full_schema: dict[str, Any] = {
        "title": "GeminiBatchEmbedContentsFull",
        "type": "object",
        "required": ["requests"],
        "properties": {
            "requests": requests_schema,
            "outputDimensionality": {"type": "integer"},
            "taskType": {"type": "string"},
            "title": {"type": "string"},
        },
        "additionalProperties": True,
    }
    return _request_body_oneof(
        minimal_schema=minimal_schema,
        full_schema=full_schema,
        minimal_example={
            "requests": [
                {
                    "model": "models/gemini-embedding-001",
                    "content": {"role": "user", "parts": [{"text": "hello"}]},
                }
            ]
        },
        full_example={
            "requests": [
                {
                    "model": "models/gemini-embedding-001",
                    "content": {"role": "user", "parts": [{"text": "hello"}]},
                },
                {
                    "model": "models/gemini-embedding-001",
                    "content": {"role": "user", "parts": [{"text": "world"}]},
                },
            ]
        },
        description="Gemini batchEmbedContents-compatible request body.",
    )
