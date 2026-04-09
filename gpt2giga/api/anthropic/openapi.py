"""OpenAPI helpers for Anthropic-compatible endpoints."""

from typing import Any, Dict

from gpt2giga.api._openapi import _request_body_oneof


def anthropic_count_tokens_openapi_extra() -> Dict[str, Any]:
    """OpenAPI extras for POST /messages/count_tokens."""
    minimal_schema: Dict[str, Any] = {
        "title": "AnthropicCountTokensRequestMinimal",
        "type": "object",
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
        },
        "additionalProperties": True,
    }

    description = (
        "**Required**: `model`, `messages`.\n\n"
        "**Notes**:\n"
        "- Returns `{input_tokens: <count>}` without creating a message.\n"
        "- Tool definitions are included in the token count if provided."
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
        },
        "additionalProperties": True,
    }

    description = (
        "**Required**: `model`, `messages`.\n\n"
        "**Notes**:\n"
        "- `stream=true` returns Anthropic-style SSE events.\n"
        "- Unknown optional parameters are accepted on a best-effort basis."
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
            }
        },
        description=description,
    )


def anthropic_message_batches_openapi_extra() -> Dict[str, Any]:
    """OpenAPI extras for POST /messages/batches."""
    minimal_schema: Dict[str, Any] = {
        "title": "AnthropicMessageBatchesRequestMinimal",
        "type": "object",
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
        "submission to GigaChat."
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
