"""OpenAPI helpers for Anthropic-compatible endpoints."""

from typing import Any, Dict

from gpt2giga.openapi_specs.common import _request_body_oneof

ANTHROPIC_ADDITIONAL_PROPERTIES_NOTE = (
    "Additional properties are shown for Anthropic SDK compatibility; unsupported "
    "unknown parameters may be rejected with a 400 Anthropic-compatible error."
)
ANTHROPIC_EXTRA_BODY_DESCRIPTION = (
    "Allowlisted GigaChat-specific fields moved to `additional_fields`: `flags`, "
    "`function_ranker`, `profanity_check`, `repetition_penalty`, `storage`, "
    "`update_interval`. Unsupported keys are rejected."
)
ANTHROPIC_EXTRA_HEADERS_DESCRIPTION = (
    "Client SDK extra headers. Only diagnostic headers are forwarded upstream: "
    "`x-request-id`, `x-correlation-id`, `x-trace-id`, `traceparent`; auth, "
    "transport, `x-stainless-*`, `openai-*`, and `anthropic-*` headers are blocked."
)
ANTHROPIC_EXTRA_QUERY_DESCRIPTION = (
    "Client SDK extra query parameters. The upstream allowlist is empty by default, "
    "so arbitrary query parameters are not forwarded to GigaChat."
)


def anthropic_count_tokens_openapi_extra() -> Dict[str, Any]:
    """OpenAPI extras for POST /messages/count_tokens."""
    minimal_schema: Dict[str, Any] = {
        "title": "AnthropicCountTokensRequestMinimal",
        "type": "object",
        "description": ANTHROPIC_ADDITIONAL_PROPERTIES_NOTE,
        "required": ["model", "messages"],
        "properties": {
            "model": {"type": "string", "description": "Model id."},
            "messages": {
                "type": "array",
                "description": "Anthropic messages array.",
                "items": {"type": "object", "additionalProperties": True},
            },
        },
        "additionalProperties": True,
    }

    full_schema: Dict[str, Any] = {
        "title": "AnthropicCountTokensRequestFull",
        "type": "object",
        "description": ANTHROPIC_ADDITIONAL_PROPERTIES_NOTE,
        "required": ["model", "messages"],
        "properties": {
            **minimal_schema["properties"],
            "system": {
                "description": "System prompt (string or content blocks).",
                "oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "object"}},
                ],
            },
            "tools": {
                "type": "array",
                "description": "Anthropic tools (input_schema). Included in token count.",
                "items": {"type": "object", "additionalProperties": True},
            },
            "extra_body": {
                "type": "object",
                "description": ANTHROPIC_EXTRA_BODY_DESCRIPTION,
                "additionalProperties": True,
            },
            "extra_headers": {
                "type": "object",
                "description": ANTHROPIC_EXTRA_HEADERS_DESCRIPTION,
                "additionalProperties": True,
            },
            "extra_query": {
                "type": "object",
                "description": ANTHROPIC_EXTRA_QUERY_DESCRIPTION,
                "additionalProperties": True,
            },
        },
        "additionalProperties": True,
    }

    description = (
        "**Required**: `model`, `messages`.\n\n"
        "**Notes**:\n"
        "- Returns `{input_tokens: <count>}` without creating a message.\n"
        "- Tool definitions are included in the token count if provided.\n"
        "- Generation-only options are ignored for counting, but unsupported "
        "content blocks and unsupported `extra_body` keys are rejected."
    )
    return _request_body_oneof(
        minimal_schema=minimal_schema,
        full_schema=full_schema,
        minimal_example={
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "Hello"}],
        },
        full_example={
            "model": "GigaChat-2-Max",
            "system": "You are a helpful assistant.",
            "messages": [{"role": "user", "content": "Count these tokens please"}],
            "tools": [
                {
                    "name": "get_weather",
                    "description": "Get weather by city.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                        "required": ["city"],
                    },
                }
            ],
        },
        description=description,
    )


def anthropic_messages_openapi_extra() -> Dict[str, Any]:
    """OpenAPI extras for POST /messages."""
    minimal_schema: Dict[str, Any] = {
        "title": "AnthropicMessagesRequestMinimal",
        "type": "object",
        "description": ANTHROPIC_ADDITIONAL_PROPERTIES_NOTE,
        "required": ["model", "messages"],
        "properties": {
            "model": {"type": "string", "description": "Model id."},
            "system": {
                "description": "System prompt (string or content blocks).",
                "oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "object"}},
                ],
            },
            "messages": {
                "type": "array",
                "description": "Anthropic messages array.",
                "items": {"type": "object", "additionalProperties": True},
            },
            "stream": {
                "type": "boolean",
                "description": "If true, returns Anthropic-style SSE stream.",
                "default": False,
            },
        },
        "additionalProperties": True,
    }

    full_schema: Dict[str, Any] = {
        "title": "AnthropicMessagesRequestFull",
        "type": "object",
        "description": ANTHROPIC_ADDITIONAL_PROPERTIES_NOTE,
        "required": ["model", "messages"],
        "properties": {
            **minimal_schema["properties"],
            "max_tokens": {
                "type": "integer",
                "description": "Maximum output tokens.",
            },
            "temperature": {"type": "number", "description": "Sampling temperature."},
            "top_p": {"type": "number", "description": "Nucleus sampling parameter."},
            "stop_sequences": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Stop sequences.",
            },
            "tools": {
                "type": "array",
                "description": "Anthropic tools (input_schema).",
                "items": {"type": "object", "additionalProperties": True},
            },
            "tool_choice": {
                "type": "object",
                "description": "Tool choice (best effort).",
                "additionalProperties": True,
            },
            "thinking": {
                "type": "object",
                "description": "Thinking budget (mapped to reasoning_effort best effort).",
                "additionalProperties": True,
            },
            "output_config": {
                "type": "object",
                "description": "Structured output config (`format.type=json_schema`).",
                "additionalProperties": True,
            },
            "extra_body": {
                "type": "object",
                "description": ANTHROPIC_EXTRA_BODY_DESCRIPTION,
                "additionalProperties": True,
            },
            "extra_headers": {
                "type": "object",
                "description": ANTHROPIC_EXTRA_HEADERS_DESCRIPTION,
                "additionalProperties": True,
            },
            "extra_query": {
                "type": "object",
                "description": ANTHROPIC_EXTRA_QUERY_DESCRIPTION,
                "additionalProperties": True,
            },
            "metadata": {
                "type": "object",
                "description": "Anthropic metadata; accepted and ignored.",
                "additionalProperties": True,
            },
            "service_tier": {
                "type": "string",
                "description": "Anthropic service tier; accepted and ignored.",
            },
            "top_k": {
                "type": "integer",
                "description": "Anthropic sampling option; accepted and ignored.",
            },
            "container": {
                "type": "string",
                "description": "Rejected: Anthropic containers are not supported.",
            },
            "context_management": {
                "type": "object",
                "description": "Rejected: stateful context management is not supported.",
                "additionalProperties": True,
            },
            "mcp_servers": {
                "type": "array",
                "description": "Rejected: MCP server tools are not supported.",
                "items": {"type": "object", "additionalProperties": True},
            },
        },
        "additionalProperties": True,
    }

    description = (
        "**Required**: `model`, `messages`.\n\n"
        "**Notes**:\n"
        "- `stream=true` returns Anthropic-style SSE events.\n"
        "- `tool_choice.type` supports `auto`, `none`, and forced `tool`; "
        "`any` is rejected.\n"
        "- Supported request content blocks are `text`, `image`, `tool_use`, "
        "and `tool_result`; document/file/container/search/thinking input blocks "
        "are rejected.\n"
        "- Unknown or unsupported optional parameters may be rejected with `400`."
    )
    return _request_body_oneof(
        minimal_schema=minimal_schema,
        full_schema=full_schema,
        minimal_example={
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "Hello"}],
        },
        full_example={
            "model": "GigaChat-2-Max",
            "system": "You are a helpful assistant.",
            "messages": [{"role": "user", "content": "Say hello"}],
            "max_tokens": 256,
            "stream": False,
        },
        extra_examples={
            "streaming": {
                "summary": "Streaming response (Anthropic SSE)",
                "value": {
                    "model": "GigaChat-2-Max",
                    "messages": [{"role": "user", "content": "Stream it"}],
                    "stream": True,
                },
            },
            "structured_output": {
                "summary": "Structured JSON output",
                "value": {
                    "model": "GigaChat-2-Max",
                    "messages": [
                        {
                            "role": "user",
                            "content": "Extract contact information from this text.",
                        }
                    ],
                    "max_tokens": 256,
                    "output_config": {
                        "format": {
                            "type": "json_schema",
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "email": {"type": "string"},
                                },
                                "required": ["name", "email"],
                                "additionalProperties": False,
                            },
                        }
                    },
                },
            },
        },
        description=description,
    )


def anthropic_message_batches_openapi_extra() -> Dict[str, Any]:
    """OpenAPI extras for POST /messages/batches."""
    minimal_schema: Dict[str, Any] = {
        "title": "AnthropicMessageBatchesRequestMinimal",
        "type": "object",
        "description": ANTHROPIC_ADDITIONAL_PROPERTIES_NOTE,
        "required": ["requests"],
        "properties": {
            "completion_window": {
                "type": "string",
                "description": 'Optional completion window. Only `"24h"` is supported.',
            },
            "requests": {
                "type": "array",
                "description": "Anthropic batch requests to process asynchronously.",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["custom_id", "params"],
                    "properties": {
                        "custom_id": {
                            "type": "string",
                            "description": "Client-defined identifier for this request.",
                        },
                        "params": {
                            "type": "object",
                            "description": "Anthropic Messages API payload for this item.",
                            "additionalProperties": True,
                        },
                    },
                    "additionalProperties": True,
                },
            },
        },
        "additionalProperties": True,
    }

    full_schema: Dict[str, Any] = {
        "title": "AnthropicMessageBatchesRequestFull",
        "type": "object",
        "description": ANTHROPIC_ADDITIONAL_PROPERTIES_NOTE,
        "required": ["requests"],
        "properties": {
            "completion_window": {
                "type": "string",
                "description": 'Optional completion window. Only `"24h"` is supported.',
            },
            "requests": {
                "type": "array",
                "description": "Anthropic batch requests to process asynchronously.",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["custom_id", "params"],
                    "properties": {
                        "custom_id": {
                            "type": "string",
                            "description": "Client-defined identifier for this request.",
                        },
                        "params": {
                            "type": "object",
                            "description": "Anthropic Messages API payload for this item.",
                            "properties": {
                                "model": {
                                    "type": "string",
                                    "description": "Model id.",
                                },
                                "max_tokens": {
                                    "type": "integer",
                                    "description": "Maximum output tokens.",
                                },
                                "system": {
                                    "description": "System prompt (string or content blocks).",
                                    "oneOf": [
                                        {"type": "string"},
                                        {"type": "array", "items": {"type": "object"}},
                                    ],
                                },
                                "messages": {
                                    "type": "array",
                                    "description": "Anthropic messages array.",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": True,
                                    },
                                },
                                "tools": {
                                    "type": "array",
                                    "description": "Anthropic tools (input_schema).",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": True,
                                    },
                                },
                                "output_config": {
                                    "type": "object",
                                    "description": "Structured output config (`format.type=json_schema`).",
                                    "additionalProperties": True,
                                },
                                "extra_body": {
                                    "type": "object",
                                    "description": ANTHROPIC_EXTRA_BODY_DESCRIPTION,
                                    "additionalProperties": True,
                                },
                                "extra_headers": {
                                    "type": "object",
                                    "description": ANTHROPIC_EXTRA_HEADERS_DESCRIPTION,
                                    "additionalProperties": True,
                                },
                                "extra_query": {
                                    "type": "object",
                                    "description": ANTHROPIC_EXTRA_QUERY_DESCRIPTION,
                                    "additionalProperties": True,
                                },
                            },
                            "additionalProperties": True,
                        },
                    },
                    "additionalProperties": True,
                },
            },
        },
        "additionalProperties": True,
    }

    description = (
        "**Required**: `requests`.\n\n"
        "**Notes**:\n"
        "- If provided, `completion_window` must be `24h`.\n"
        "- Each request item must include a unique `custom_id` and a non-streaming "
        "Messages API `params` object.\n"
        "- Batch items are translated to the OpenAI-compatible batch pipeline before "
        "submission to GigaChat.\n"
        "- This schema is used only when the batches router is mounted; the default "
        "public Anthropic router omits batch routes until GigaChat SDK batch support "
        "is available."
    )
    return _request_body_oneof(
        minimal_schema=minimal_schema,
        full_schema=full_schema,
        minimal_example={
            "completion_window": "24h",
            "requests": [
                {
                    "custom_id": "req-1",
                    "params": {
                        "model": "GigaChat-2-Max",
                        "max_tokens": 128,
                        "messages": [{"role": "user", "content": "Hello batch"}],
                    },
                }
            ],
        },
        full_example={
            "completion_window": "24h",
            "requests": [
                {
                    "custom_id": "req-tools-1",
                    "params": {
                        "model": "GigaChat-2-Max",
                        "system": "You are a research assistant.",
                        "max_tokens": 256,
                        "messages": [
                            {
                                "role": "user",
                                "content": "Summarize yesterday's deployment notes.",
                            }
                        ],
                        "output_config": {
                            "format": {
                                "type": "json_schema",
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "summary": {"type": "string"},
                                    },
                                    "required": ["summary"],
                                    "additionalProperties": False,
                                },
                            }
                        },
                        "tools": [
                            {
                                "name": "lookup_release_notes",
                                "description": "Find release notes by date.",
                                "input_schema": {
                                    "type": "object",
                                    "properties": {
                                        "date": {"type": "string"},
                                    },
                                    "required": ["date"],
                                },
                            }
                        ],
                    },
                }
            ],
        },
        extra_examples={
            "multiple_requests": {
                "summary": "Multiple batch requests",
                "value": {
                    "requests": [
                        {
                            "custom_id": "req-1",
                            "params": {
                                "model": "GigaChat-2-Max",
                                "max_tokens": 128,
                                "messages": [
                                    {
                                        "role": "user",
                                        "content": "Draft a release note title.",
                                    }
                                ],
                            },
                        },
                        {
                            "custom_id": "req-2",
                            "params": {
                                "model": "GigaChat-2-Max",
                                "max_tokens": 128,
                                "messages": [
                                    {
                                        "role": "user",
                                        "content": "Draft a one-line summary.",
                                    }
                                ],
                            },
                        },
                    ]
                },
            }
        },
        description=description,
    )
