"""OpenAPI helpers for Gemini-compatible endpoints."""

from typing import Any, Dict

from gpt2giga.api._openapi import _request_body_oneof


def gemini_generate_content_openapi_extra() -> Dict[str, Any]:
    """OpenAPI extras for Gemini generateContent."""
    minimal_schema = {
        "title": "GeminiGenerateContentMinimal",
        "type": "object",
        "required": ["contents"],
        "properties": {
            "contents": {
                "description": "Gemini content payload.",
                "oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "object"}},
                    {"type": "object"},
                ],
            }
        },
        "additionalProperties": True,
    }
    full_schema = {
        "title": "GeminiGenerateContentFull",
        "type": "object",
        "required": ["contents"],
        "properties": {
            **minimal_schema["properties"],
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


def gemini_count_tokens_openapi_extra() -> Dict[str, Any]:
    """OpenAPI extras for Gemini countTokens."""
    minimal_schema = {
        "title": "GeminiCountTokensMinimal",
        "type": "object",
        "required": ["contents"],
        "properties": {
            "contents": {
                "type": "array",
                "items": {"type": "object", "additionalProperties": True},
            }
        },
        "additionalProperties": True,
    }
    full_schema = {
        "title": "GeminiCountTokensFull",
        "type": "object",
        "properties": {
            "contents": minimal_schema["properties"]["contents"],
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


def gemini_batch_embed_contents_openapi_extra() -> Dict[str, Any]:
    """OpenAPI extras for Gemini batchEmbedContents."""
    minimal_schema = {
        "title": "GeminiBatchEmbedContentsMinimal",
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
    full_schema = {
        "title": "GeminiBatchEmbedContentsFull",
        "type": "object",
        "required": ["requests"],
        "properties": {
            "requests": minimal_schema["properties"]["requests"],
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
