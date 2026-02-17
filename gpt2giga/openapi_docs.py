"""OpenAPI/Swagger documentation helpers.

This module defines `openapi_extra` payloads for FastAPI routes.
We intentionally keep runtime request handling unchanged (routes still accept
`Request` and parse JSON manually), but we enrich Swagger so users can see
required fields and common optional parameters.
"""

from typing import Any, Dict


def _request_body_oneof(
    *,
    minimal_schema: Dict[str, Any],
    full_schema: Dict[str, Any],
    minimal_example: Dict[str, Any],
    full_example: Dict[str, Any],
    extra_examples: Dict[str, Dict[str, Any]] | None = None,
    description: str | None = None,
) -> Dict[str, Any]:
    """Build OpenAPI `requestBody` with oneOf + examples.

    Args:
        minimal_schema: Minimal request schema (required fields and basics).
        full_schema: Full request schema (common options + additionalProperties).
        minimal_example: Minimal example payload.
        full_example: Full example payload.
        extra_examples: Additional named examples.
        description: Optional description for requestBody.

    Returns:
        Dict suitable for passing as `openapi_extra` in FastAPI route decorators.
    """
    examples: Dict[str, Dict[str, Any]] = {
        "minimal": {"summary": "Minimal request", "value": minimal_example},
        "full": {"summary": "Full request", "value": full_example},
    }
    if extra_examples:
        examples.update(extra_examples)

    request_body: Dict[str, Any] = {
        "required": True,
        "content": {
            "application/json": {
                "schema": {"oneOf": [minimal_schema, full_schema]},
                "examples": examples,
            }
        },
    }
    if description:
        request_body["description"] = description

    return {"requestBody": request_body}


def chat_completions_openapi_extra() -> Dict[str, Any]:
    """OpenAPI extras for `POST /chat/completions`."""
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
        # Keep schema future-proof: the proxy may accept more OpenAI parameters.
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
    """OpenAPI extras for `POST /embeddings`."""
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

    minimal_example = {"input": "Hello world"}
    full_example = {"input": ["Hello", "world"], "model": "gpt-4o-mini"}

    description = (
        "**Required**: `input`.\n\n"
        "**Notes**:\n"
        "- `model` is optional; embeddings model is configured on the proxy side.\n"
        "- Token-id inputs (`List[int]` / `List[List[int]]`) require `model` for decoding."
    )
    return _request_body_oneof(
        minimal_schema=minimal_schema,
        full_schema=full_schema,
        minimal_example=minimal_example,
        full_example=full_example,
        description=description,
    )


def responses_openapi_extra() -> Dict[str, Any]:
    """OpenAPI extras for `POST /responses`."""
    minimal_schema: Dict[str, Any] = {
        "title": "ResponsesRequestMinimal",
        "type": "object",
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
                "description": "Custom metadata.",
                "additionalProperties": True,
            },
        },
        "additionalProperties": True,
    }

    minimal_example = {"model": "GigaChat-2-Max", "input": "Talk about yourself."}
    full_example = {
        "model": "GigaChat-2-Max",
        "instructions": "Answer concisely.",
        "input": [
            {"role": "user", "content": [{"type": "input_text", "text": "Hello"}]},
        ],
        "stream": False,
    }

    extra_examples = {
        "streaming": {
            "summary": "Streaming response (SSE lifecycle events)",
            "value": {
                "model": "GigaChat-2-Max",
                "input": "Stream it.",
                "stream": True,
            },
        }
    }

    description = (
        "**Required**: `model`, `input`.\n\n"
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


def anthropic_count_tokens_openapi_extra() -> Dict[str, Any]:
    """OpenAPI extras for `POST /messages/count_tokens` (Anthropic token counting)."""
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

    minimal_example = {
        "model": "GigaChat-2-Max",
        "messages": [{"role": "user", "content": "Hello"}],
    }
    full_example = {
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
        minimal_example=minimal_example,
        full_example=full_example,
        description=description,
    )


def anthropic_messages_openapi_extra() -> Dict[str, Any]:
    """OpenAPI extras for `POST /messages` (Anthropic Messages API)."""
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

    minimal_example = {
        "model": "GigaChat-2-Max",
        "messages": [{"role": "user", "content": "Hello"}],
    }
    full_example = {
        "model": "GigaChat-2-Max",
        "system": "You are a helpful assistant.",
        "messages": [{"role": "user", "content": "Say hello"}],
        "max_tokens": 256,
        "stream": False,
    }

    extra_examples = {
        "streaming": {
            "summary": "Streaming response (Anthropic SSE)",
            "value": {
                "model": "GigaChat-2-Max",
                "messages": [{"role": "user", "content": "Stream it"}],
                "stream": True,
            },
        }
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
        minimal_example=minimal_example,
        full_example=full_example,
        extra_examples=extra_examples,
        description=description,
    )
