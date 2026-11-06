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
                "description": (
                    "Function declarations are mapped to executable tools; "
                    "compatible provider tools map to GigaChat v2 built-ins."
                ),
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
    """Describe the resumable upload handshake and raw-byte continuation."""
    return {
        "description": (
            "Start a resumable upload with JSON metadata and X-Goog-Upload-Command: start. "
            "Post raw bytes to the returned X-Goog-Upload-URL with an exact offset and "
            "upload/finalize command. Metadata-only files are not published. "
            "Authentication is required on every stage; sessions expire after 24 hours."
        ),
        "parameters": [
            {"in": "header", "name": name, "schema": {"type": "string"}}
            for name in (
                "X-Goog-Upload-Protocol",
                "X-Goog-Upload-Command",
                "X-Goog-Upload-Header-Content-Length",
                "X-Goog-Upload-Header-Content-Type",
                "X-Goog-Upload-Offset",
            )
        ],
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "file": {
                                "type": "object",
                                "properties": {
                                    "displayName": {"type": "string"},
                                    "mimeType": {"type": "string"},
                                },
                            }
                        },
                    }
                },
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"}
                },
            }
        },
    }


def gemini_batches_openapi_extra(*, create: bool) -> dict[str, Any]:
    """Describe native batch execution and the SDK Operation projection."""
    result = {
        "description": (
            "Submit one model's inline requests or owned JSONL file to native GigaChat batch execution. "
            "No streaming, stateful continuation, hosted tools, cancellation or processing-time SLA. "
            "The response is an Operation named batches/{id}; output is in metadata.output."
            if create
            else "Read registered owner-scoped native jobs; poll on demand with retained results."
        )
    }
    if create:
        result["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["batch"],
                        "properties": {
                            "batch": {
                                "type": "object",
                                "required": ["inputConfig"],
                                "properties": {
                                    "displayName": {"type": "string"},
                                    "inputConfig": {
                                        "type": "object",
                                        "properties": {
                                            "fileName": {"type": "string"},
                                            "requests": {
                                                "type": "object",
                                                "properties": {
                                                    "requests": {
                                                        "type": "array",
                                                        "items": {"type": "object"},
                                                    }
                                                },
                                            },
                                        },
                                    },
                                },
                            }
                        },
                    }
                }
            },
        }
    return result
