from __future__ import annotations

import json

import gigachat.exceptions
import pytest
from fastapi import Request

from gpt2giga.api.gemini.response import (
    build_generate_content_response,
    gemini_exceptions_handler,
)


def test_build_generate_content_response_orders_reasoning_text_and_tool_call() -> None:
    response = build_generate_content_response(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "reasoning_content": "Need fresh search results.",
                        "content": "Looking it up.",
                        "function_call": {
                            "name": "__gpt2giga_user_search_web",
                            "arguments": '{"query":"weather in Moscow"}',
                        },
                    },
                    "finish_reason": "function_call",
                }
            ],
            "usage": {
                "prompt_tokens": 7,
                "completion_tokens": 3,
                "total_tokens": 10,
            },
        },
        "models/gemini-2.5-pro",
        "resp-gemini-tools",
    )

    parts = response["candidates"][0]["content"]["parts"]
    assert parts[0] == {"text": "Need fresh search results.", "thought": True}
    assert parts[1] == {"text": "Looking it up."}
    assert parts[2] == {
        "functionCall": {
            "name": "web_search",
            "args": {"query": "weather in Moscow"},
        }
    }
    assert response["candidates"][0]["finishReason"] == "STOP"


def test_build_generate_content_response_structured_output_coerces_scalar_args() -> (
    None
):
    response = build_generate_content_response(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "function_call": {
                            "name": "structured_output",
                            "arguments": '"done"',
                        },
                    },
                    "finish_reason": "function_call",
                }
            ],
            "usage": {
                "prompt_tokens": 5,
                "completion_tokens": 2,
                "total_tokens": 7,
            },
        },
        "gemini-test",
        "resp-gemini-structured",
        request_data={
            "generationConfig": {
                "responseJsonSchema": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                }
            }
        },
    )

    parts = response["candidates"][0]["content"]["parts"]
    assert parts == [{"text": json.dumps({"value": "done"})}]


@pytest.mark.asyncio
async def test_gemini_exceptions_handler_maps_gigachat_forbidden_error() -> None:
    @gemini_exceptions_handler
    async def failing_handler(request: Request):
        del request
        raise gigachat.exceptions.ForbiddenError(
            "https://gigachat.test",
            403,
            b'{"message":"forbidden"}',
            None,
        )

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": "/models/test:generateContent",
        "raw_path": b"/models/test:generateContent",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "scheme": "http",
    }
    request = Request(scope)
    response = await failing_handler(request=request)
    body = json.loads(response.body)

    assert response.status_code == 403
    assert body["error"]["code"] == 403
    assert body["error"]["status"] == "PERMISSION_DENIED"
    assert "forbidden" in body["error"]["message"]
