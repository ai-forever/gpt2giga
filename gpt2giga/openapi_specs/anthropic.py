"""OpenAPI helpers for Anthropic-compatible endpoints."""

from typing import Any, Dict

from gpt2giga.openapi_specs.common import _request_body_oneof


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
