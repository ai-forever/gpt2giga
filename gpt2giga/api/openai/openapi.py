"""OpenAPI helpers for OpenAI-compatible endpoints."""

from typing import Any, Dict

from gpt2giga.api._openapi import _request_body_oneof


def chat_completions_openapi_extra() -> Dict[str, Any]:
    """OpenAPI extras for POST /chat/completions."""
    minimal_schema: Dict[str, Any] = {
        "title": "ChatCompletionsRequestMinimal",
        "type": "object",
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
            "user": {"type": "string", "description": "End-user identifier."},
            "metadata": {
                "type": "object",
                "description": "Custom metadata.",
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
        "- Unknown optional parameters are accepted on a best-effort basis."
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
                    "Optional. Used for token decoding when `input` is token ids. "
                    "Embeddings model is selected from proxy settings."
                ),
            },
        },
        "additionalProperties": True,
    }

    full_schema: Dict[str, Any] = {
        "title": "EmbeddingsRequestFull",
        "type": "object",
        "required": ["input"],
        "properties": {
            **minimal_schema["properties"],
            "encoding_format": {
                "type": "string",
                "description": "OpenAI compatibility parameter (best effort).",
                "enum": ["float", "base64"],
            },
            "user": {"type": "string", "description": "End-user identifier."},
        },
        "additionalProperties": True,
    }

    description = (
        "**Required**: `input`.\n\n"
        "**Notes**:\n"
        "- `model` is optional; embeddings model is configured on the proxy side.\n"
        "- Token-id inputs (`List[int]` / `List[List[int]]`) require `model` for decoding."
    )
    return _request_body_oneof(
        minimal_schema=minimal_schema,
        full_schema=full_schema,
        minimal_example={"input": "Hello world"},
        full_example={"input": ["Hello", "world"], "model": "gpt-4o-mini"},
        description=description,
    )


def responses_openapi_extra() -> Dict[str, Any]:
    """OpenAPI extras for POST /responses."""
    minimal_schema: Dict[str, Any] = {
        "title": "ResponsesRequestMinimal",
        "type": "object",
        "required": ["input"],
        "properties": {
            "model": {
                "type": "string",
                "description": "Model id. Optional when continuing via `conversation.id` or `previous_response_id`.",
            },
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
        "required": ["input"],
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
                "description": 'OpenAI tools format. Functions and built-in `web_search*`, `code_interpreter`, `image_generation` / `image_generate`, `url_content_extraction`, `model_3d_generate` are supported best-effort. For `web_search`, GigaChat-native config may be passed as `{"type": "web_search", "web_search": {"type": "actual_info_web_search", "indexes": [...], "flags": [...]}}`.',
                "items": {"type": "object", "additionalProperties": True},
            },
            "tool_choice": {
                "description": "Tool choice (best effort).",
                "oneOf": [{"type": "string"}, {"type": "object"}],
            },
            "store": {
                "type": "boolean",
                "description": "When true or omitted, enables GigaChat stateful storage for Responses v2. Set false to force stateless execution.",
            },
            "storage": {
                "type": "object",
                "description": "Best-effort passthrough to GigaChat `storage` (`thread_id`, `limit`, `metadata`). Boolean form is not supported.",
                "additionalProperties": True,
            },
            "previous_response_id": {
                "type": "string",
                "description": "Continue an in-memory Responses conversation using a previous response id.",
            },
            "conversation": {
                "type": "object",
                "description": "Directly target an existing GigaChat thread via `conversation.id`.",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Existing conversation/thread id.",
                    }
                },
                "additionalProperties": True,
            },
            "metadata": {
                "type": "object",
                "description": "Custom metadata.",
                "additionalProperties": True,
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
        "**Required**: `input`.\n\n"
        "**Notes**:\n"
        "- `stream=true` returns an SSE stream (`text/event-stream`).\n"
        "- Responses v2 enables GigaChat stateful storage by default; use `store=false` to disable it.\n"
        "- `model` may be omitted when continuing via `conversation.id` or `previous_response_id`.\n"
        "- `previous_response_id` continues proxy-tracked thread metadata and does not survive proxy restarts.\n"
        "- `conversation.id` directly targets an existing GigaChat thread.\n"
        "- Optional `storage` is passed through best-effort to GigaChat for `limit` / `metadata` / `thread_id`.\n"
        "- Unknown optional parameters are accepted on a best-effort basis."
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
                "enum": ["/v1/chat/completions", "/v1/embeddings"],
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
        "- Supported endpoints: `/v1/chat/completions` and `/v1/embeddings`.\n"
        "- If `GPT2GIGA_GIGACHAT_API_MODE=v2`, `/v1/chat/completions` batch "
        "requests still use the GigaChat v1 backend until v2 batching support is "
        "implemented."
    )
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
        extra_examples={
            "embeddings_batch": {
                "summary": "Batch over the Embeddings API",
                "value": {
                    "completion_window": "24h",
                    "endpoint": "/v1/embeddings",
                    "input_file_id": "file-embed123",
                },
            }
        },
        description=description,
    )
