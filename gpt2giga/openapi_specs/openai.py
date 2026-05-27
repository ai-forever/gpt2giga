"""OpenAPI helpers for OpenAI-compatible endpoints."""

from typing import Any, Dict

from gpt2giga.openapi_specs.common import _request_body_oneof

OPENAI_ADDITIONAL_PROPERTIES_NOTE = (
    "Additional properties are shown for SDK compatibility; unsupported unknown "
    "parameters may be rejected with a 400 OpenAI-compatible error."
)
GIGACHAT_EXTRA_BODY_DESCRIPTION = (
    "Allowlisted GigaChat-specific fields moved to `additional_fields`: `flags`, "
    "`function_ranker`, `profanity_check`, `repetition_penalty`, `storage`, "
    "`update_interval`. Unsupported keys are rejected."
)
SAFE_EXTRA_HEADERS_DESCRIPTION = (
    "Client SDK extra headers. Only diagnostic headers are forwarded upstream: "
    "`x-request-id`, `x-correlation-id`, `x-trace-id`, `traceparent`; auth, "
    "transport, `x-stainless-*`, `openai-*`, and `anthropic-*` headers are blocked."
)
SAFE_EXTRA_QUERY_DESCRIPTION = (
    "Client SDK extra query parameters. The upstream allowlist is empty by default, "
    "so arbitrary query parameters are not forwarded to GigaChat."
)


def chat_completions_openapi_extra() -> Dict[str, Any]:
    """OpenAPI extras for POST /chat/completions."""
    minimal_schema: Dict[str, Any] = {
        "title": "ChatCompletionsRequestMinimal",
        "type": "object",
        "description": OPENAI_ADDITIONAL_PROPERTIES_NOTE,
        "required": ["model", "messages"],
        "properties": {
            "model": {
                "type": "string",
                "description": "Model id.",
                "example": "GigaChat-2-Max",
            },
            "messages": {
                "type": "array",
                "description": "Conversation messages.",
                "items": {
                    "type": "object",
                    "required": ["role", "content"],
                    "properties": {
                        "role": {
                            "type": "string",
                            "description": "Message role.",
                            "enum": [
                                "system",
                                "user",
                                "assistant",
                                "tool",
                                "developer",
                            ],
                        },
                        "content": {
                            "description": "Message content (string or structured parts).",
                            "oneOf": [
                                {"type": "string"},
                                {"type": "array", "items": {"type": "object"}},
                            ],
                        },
                        "name": {
                            "type": "string",
                            "description": "Optional name (legacy / tool messages).",
                        },
                        "tool_calls": {
                            "type": "array",
                            "description": "Tool calls (OpenAI tools API).",
                            "items": {"type": "object"},
                        },
                    },
                    "additionalProperties": True,
                },
            },
            "stream": {
                "type": "boolean",
                "description": "If true, returns SSE stream (`text/event-stream`).",
                "default": False,
            },
        },
        "additionalProperties": True,
    }

    full_schema: Dict[str, Any] = {
        "title": "ChatCompletionsRequestFull",
        "type": "object",
        "description": OPENAI_ADDITIONAL_PROPERTIES_NOTE,
        "required": ["model", "messages"],
        "properties": {
            "model": {"type": "string", "description": "Model id."},
            "messages": minimal_schema["properties"]["messages"],
            "stream": minimal_schema["properties"]["stream"],
            "temperature": {
                "type": "number",
                "description": "Sampling temperature.",
                "default": 1,
            },
            "top_p": {
                "type": "number",
                "description": "Nucleus sampling parameter.",
                "default": 1,
            },
            "max_tokens": {
                "type": "integer",
                "description": "Maximum number of output tokens.",
            },
            "max_completion_tokens": {
                "type": "integer",
                "description": (
                    "OpenAI Chat Completions output-token limit. Mapped to "
                    "`max_tokens`; rejected if it conflicts with `max_tokens`."
                ),
            },
            "max_output_tokens": {
                "type": "integer",
                "description": "Alias used by some clients (mapped to max_tokens).",
            },
            "stop": {
                "description": "Stop sequence(s).",
                "oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ],
            },
            "response_format": {
                "type": "object",
                "description": "Structured output / JSON schema (best effort).",
                "additionalProperties": True,
            },
            "tools": {
                "type": "array",
                "description": "OpenAI tools format (type=function).",
                "items": {"type": "object", "additionalProperties": True},
            },
            "functions": {
                "type": "array",
                "description": "Legacy functions format (will be mapped for GigaChat).",
                "items": {"type": "object", "additionalProperties": True},
            },
            "function_call": {
                "description": "Force function/tool call (best effort).",
                "oneOf": [{"type": "string"}, {"type": "object"}],
            },
            "extra_body": {
                "type": "object",
                "description": GIGACHAT_EXTRA_BODY_DESCRIPTION,
                "additionalProperties": True,
            },
            "extra_headers": {
                "type": "object",
                "description": SAFE_EXTRA_HEADERS_DESCRIPTION,
                "additionalProperties": True,
            },
            "extra_query": {
                "type": "object",
                "description": SAFE_EXTRA_QUERY_DESCRIPTION,
                "additionalProperties": True,
            },
            "user": {
                "type": "string",
                "description": "OpenAI abuse-monitoring metadata; accepted and ignored.",
            },
            "metadata": {
                "type": "object",
                "description": "OpenAI storage/query metadata; accepted and ignored.",
                "additionalProperties": True,
            },
            "service_tier": {
                "type": "string",
                "description": "OpenAI service-tier option; accepted and ignored.",
            },
            "safety_identifier": {
                "type": "string",
                "description": "OpenAI safety identifier; accepted and ignored.",
            },
            "logprobs": {
                "type": "boolean",
                "description": "Rejected: log probabilities are not supported.",
            },
            "top_logprobs": {
                "type": "integer",
                "description": "Rejected: log probabilities are not supported.",
            },
            "audio": {
                "type": "object",
                "description": "Rejected: audio output is not supported.",
                "additionalProperties": True,
            },
            "prediction": {
                "type": "object",
                "description": "Rejected: predicted outputs are not supported.",
                "additionalProperties": True,
            },
        },
        "additionalProperties": True,
    }

    minimal_example = {
        "model": "GigaChat-2-Max",
        "messages": [{"role": "user", "content": "Hello!"}],
    }
    full_example = {
        "model": "GigaChat-2-Max",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Write a haiku about proxy servers."},
        ],
        "temperature": 0.7,
        "top_p": 1,
        "stream": False,
    }

    extra_examples = {
        "streaming": {
            "summary": "Streaming response (SSE)",
            "value": {
                "model": "GigaChat-2-Max",
                "messages": [{"role": "user", "content": "Stream it."}],
                "stream": True,
            },
        },
        "tools": {
            "summary": "Tool calling (OpenAI tools format)",
            "value": {
                "model": "GigaChat-2-Max",
                "messages": [
                    {"role": "user", "content": "Call the weather tool in Moscow."}
                ],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "description": "Get weather by city.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "city": {"type": "string"},
                                    "units": {"type": "string", "enum": ["c", "f"]},
                                },
                                "required": ["city"],
                            },
                        },
                    }
                ],
            },
        },
    }

    description = (
        "**Required**: `model`, `messages`.\n\n"
        "**Notes**:\n"
        "- `stream=true` returns an SSE stream (`text/event-stream`).\n"
        "- `extra_body` supports only allowlisted GigaChat-specific fields.\n"
        "- Unknown or unsupported optional parameters may be rejected with `400`."
    )
    return _request_body_oneof(
        minimal_schema=minimal_schema,
        full_schema=full_schema,
        minimal_example=minimal_example,
        full_example=full_example,
        extra_examples=extra_examples,
        description=description,
    )


def embeddings_openapi_extra() -> Dict[str, Any]:
    """OpenAPI extras for POST /embeddings."""
    minimal_schema: Dict[str, Any] = {
        "title": "EmbeddingsRequestMinimal",
        "type": "object",
        "description": OPENAI_ADDITIONAL_PROPERTIES_NOTE,
        "required": ["input"],
        "properties": {
            "input": {
                "description": "Input text(s) or token ids.",
                "oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                    {"type": "array", "items": {"type": "integer"}},
                    {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "integer"}},
                    },
                ],
            },
            "model": {
                "type": "string",
                "description": (
                    "OpenAI-compatible model id. Optional gpt2giga extension: "
                    "falls back to the proxy embeddings model when omitted."
                ),
            },
        },
        "additionalProperties": True,
    }

    full_schema: Dict[str, Any] = {
        "title": "EmbeddingsRequestFull",
        "type": "object",
        "description": OPENAI_ADDITIONAL_PROPERTIES_NOTE,
        "required": ["input"],
        "properties": {
            **minimal_schema["properties"],
            "encoding_format": {
                "type": "string",
                "description": "Embedding vector format.",
                "enum": ["float", "base64"],
            },
            "dimensions": {
                "type": "integer",
                "description": (
                    "Accepted when it matches the native GigaChat embedding model "
                    "dimension: Embeddings/Embeddings-2=1024, "
                    "GigaEmbeddings-3B-2025-09=2048, EmbeddingsGigaR=2560."
                ),
            },
            "user": {
                "type": "string",
                "description": "OpenAI abuse-monitoring metadata; accepted and ignored.",
            },
            "extra_body": {
                "type": "object",
                "description": "Rejected for embeddings; no GigaChat embeddings extras are allowlisted.",
                "additionalProperties": True,
            },
            "extra_headers": {
                "type": "object",
                "description": SAFE_EXTRA_HEADERS_DESCRIPTION,
                "additionalProperties": True,
            },
            "extra_query": {
                "type": "object",
                "description": SAFE_EXTRA_QUERY_DESCRIPTION,
                "additionalProperties": True,
            },
        },
        "additionalProperties": True,
    }

    description = (
        "**Required**: `input`.\n\n"
        "**Notes**:\n"
        "- `model` is accepted like OpenAI, but can be omitted as a gpt2giga "
        "extension; the proxy then uses `GPT2GIGA_EMBEDDINGS`.\n"
        "- Token-id inputs (`List[int]` / `List[List[int]]`) require a model "
        "known to `tiktoken` for decoding.\n"
        "- `dimensions` is a strict compatibility check: accepted only when it "
        "matches the native dimension of the resolved GigaChat embedding model.\n"
        "- `extra_body` and unknown top-level fields are rejected for embeddings."
    )
    return _request_body_oneof(
        minimal_schema=minimal_schema,
        full_schema=full_schema,
        minimal_example={"input": "Hello world"},
        full_example={"input": ["Hello", "world"], "model": "EmbeddingsGigaR"},
        description=description,
    )


def responses_openapi_extra() -> Dict[str, Any]:
    """OpenAPI extras for POST /responses."""
    minimal_schema: Dict[str, Any] = {
        "title": "ResponsesRequestMinimal",
        "type": "object",
        "description": OPENAI_ADDITIONAL_PROPERTIES_NOTE,
        "required": ["model", "input"],
        "properties": {
            "model": {"type": "string", "description": "Model id."},
            "input": {
                "description": "Input text or multi-item conversation input.",
                "oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "object"}},
                ],
            },
            "stream": {
                "type": "boolean",
                "description": "If true, returns SSE stream (`text/event-stream`).",
                "default": False,
            },
        },
        "additionalProperties": True,
    }

    full_schema: Dict[str, Any] = {
        "title": "ResponsesRequestFull",
        "type": "object",
        "description": OPENAI_ADDITIONAL_PROPERTIES_NOTE,
        "required": ["model", "input"],
        "properties": {
            **minimal_schema["properties"],
            "instructions": {
                "type": "string",
                "description": "System instructions (mapped to a system message).",
            },
            "text": {
                "type": "object",
                "description": "Responses API text.format (incl. json_schema).",
                "additionalProperties": True,
            },
            "reasoning": {
                "type": "object",
                "description": "Responses API reasoning options (maps `effort` to `reasoning_effort`).",
                "additionalProperties": True,
            },
            "temperature": {"type": "number", "description": "Sampling temperature."},
            "top_p": {"type": "number", "description": "Nucleus sampling parameter."},
            "max_output_tokens": {
                "type": "integer",
                "description": "Maximum number of output tokens.",
            },
            "tools": {
                "type": "array",
                "description": "OpenAI tools format (type=function).",
                "items": {"type": "object", "additionalProperties": True},
            },
            "tool_choice": {
                "description": "Tool choice (best effort).",
                "oneOf": [{"type": "string"}, {"type": "object"}],
            },
            "metadata": {
                "type": "object",
                "description": "OpenAI storage/query metadata; accepted and ignored.",
                "additionalProperties": True,
            },
            "extra_body": {
                "type": "object",
                "description": GIGACHAT_EXTRA_BODY_DESCRIPTION,
                "additionalProperties": True,
            },
            "extra_headers": {
                "type": "object",
                "description": SAFE_EXTRA_HEADERS_DESCRIPTION,
                "additionalProperties": True,
            },
            "extra_query": {
                "type": "object",
                "description": SAFE_EXTRA_QUERY_DESCRIPTION,
                "additionalProperties": True,
            },
            "previous_response_id": {
                "type": "string",
                "description": "Rejected: stateful Responses continuation is not supported.",
            },
            "conversation": {
                "type": "object",
                "description": "Rejected: stateful Responses conversations are not supported.",
                "additionalProperties": True,
            },
            "background": {
                "type": "boolean",
                "description": "Rejected: background responses are not supported.",
            },
            "include": {
                "type": "array",
                "description": "Rejected: Responses include expansions are not supported.",
                "items": {"type": "string"},
            },
        },
        "additionalProperties": True,
    }

    extra_examples = {
        "streaming": {
            "summary": "Streaming response (SSE lifecycle events)",
            "value": {
                "model": "GigaChat-2-Max",
                "input": "Stream it.",
                "stream": True,
            },
        },
        "reasoning": {
            "summary": "Reasoning response",
            "value": {
                "model": "GigaChat-2-Max",
                "input": "What is the capital of France?",
                "reasoning": {"effort": "high"},
            },
        },
    }

    description = (
        "**Required**: `model`, `input`.\n\n"
        "**Notes**:\n"
        "- `stream=true` returns an SSE stream (`text/event-stream`).\n"
        "- Stateful lifecycle features such as `previous_response_id` and "
        "`conversation` are not supported.\n"
        "- Unknown or unsupported optional parameters may be rejected with `400`."
    )
    return _request_body_oneof(
        minimal_schema=minimal_schema,
        full_schema=full_schema,
        minimal_example={"model": "GigaChat-2-Max", "input": "Talk about yourself."},
        full_example={
            "model": "GigaChat-2-Max",
            "instructions": "Answer concisely.",
            "input": [
                {"role": "user", "content": [{"type": "input_text", "text": "Hello"}]}
            ],
            "stream": False,
        },
        extra_examples=extra_examples,
        description=description,
    )


def files_openapi_extra() -> Dict[str, Any]:
    """OpenAPI extras for POST /files."""
    return {
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file", "purpose"],
                        "properties": {
                            "file": {
                                "type": "string",
                                "format": "binary",
                                "description": "File to upload.",
                            },
                            "purpose": {
                                "type": "string",
                                "description": "OpenAI file purpose.",
                                "example": "batch",
                            },
                        },
                    },
                    "examples": {
                        "batch_input": {
                            "summary": "Upload a batch input file",
                            "value": {
                                "purpose": "batch",
                                "file": "(binary JSONL file, for example batch.jsonl)",
                            },
                        },
                        "assistant_asset": {
                            "summary": "Upload an assistants file",
                            "value": {
                                "purpose": "assistants",
                                "file": "(binary file, for example handbook.pdf)",
                            },
                        },
                    },
                }
            },
            "description": (
                "**Required**: `file`, `purpose`.\n\n"
                "**Notes**:\n"
                "- `purpose` is accepted in OpenAI format and mapped to the closest "
                "GigaChat equivalent."
            ),
        }
    }


def batches_openapi_extra() -> Dict[str, Any]:
    """OpenAPI extras for POST /batches."""
    minimal_schema: Dict[str, Any] = {
        "title": "BatchCreateRequestMinimal",
        "type": "object",
        "required": ["completion_window", "endpoint", "input_file_id"],
        "properties": {
            "completion_window": {
                "type": "string",
                "enum": ["24h"],
                "description": "Currently only `24h` is supported.",
            },
            "endpoint": {
                "type": "string",
                "enum": [
                    "/v1/chat/completions",
                    "/v1/responses",
                    "/v1/embeddings",
                ],
                "description": "OpenAI endpoint to batch.",
            },
            "input_file_id": {
                "type": "string",
                "description": "Uploaded input file id.",
            },
        },
        "additionalProperties": True,
    }

    full_schema: Dict[str, Any] = {
        "title": "BatchCreateRequestFull",
        "type": "object",
        "required": ["completion_window", "endpoint", "input_file_id"],
        "properties": {
            **minimal_schema["properties"],
            "metadata": {
                "type": "object",
                "description": "Optional metadata preserved on the proxy response.",
                "additionalProperties": True,
            },
            "output_expires_after": {
                "type": "object",
                "description": "Accepted for compatibility and ignored upstream.",
                "additionalProperties": True,
            },
        },
        "additionalProperties": True,
    }

    description = (
        "**Required**: `completion_window`, `endpoint`, `input_file_id`.\n\n"
        "**Notes**:\n"
        "- Input JSONL is accepted in OpenAI batch format and translated before "
        "submission to GigaChat.\n"
        "- Supported endpoints: `/v1/chat/completions`, `/v1/responses`, "
        "and `/v1/embeddings`."
    )
    extra_examples = {
        "responses_batch": {
            "summary": "Batch over the Responses API",
            "value": {
                "completion_window": "24h",
                "endpoint": "/v1/responses",
                "input_file_id": "file-resp123",
                "metadata": {"source": "bulk-summarization"},
            },
        },
        "embeddings_batch": {
            "summary": "Batch over the Embeddings API",
            "value": {
                "completion_window": "24h",
                "endpoint": "/v1/embeddings",
                "input_file_id": "file-embed123",
            },
        },
    }
    return _request_body_oneof(
        minimal_schema=minimal_schema,
        full_schema=full_schema,
        minimal_example={
            "completion_window": "24h",
            "endpoint": "/v1/chat/completions",
            "input_file_id": "file-abc123",
        },
        full_example={
            "completion_window": "24h",
            "endpoint": "/v1/chat/completions",
            "input_file_id": "file-abc123",
            "metadata": {"source": "nightly-job"},
        },
        extra_examples=extra_examples,
        description=description,
    )
