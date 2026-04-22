from __future__ import annotations

from gpt2giga.api.anthropic.response import _build_anthropic_response


def test_build_anthropic_response_orders_reasoning_text_and_tool_use() -> None:
    response = _build_anthropic_response(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "reasoning_content": "Need a tool call first.",
                        "content": "Checking.",
                        "function_call": {
                            "name": "__gpt2giga_user_search_web",
                            "arguments": {"query": "weather in Moscow"},
                        },
                    },
                    "finish_reason": "function_call",
                }
            ],
            "usage": {
                "prompt_tokens": 6,
                "completion_tokens": 4,
                "total_tokens": 10,
            },
        },
        "claude-test",
        "resp-anthropic-tools",
    )

    assert response["content"][0] == {
        "type": "thinking",
        "thinking": "Need a tool call first.",
    }
    assert response["content"][1] == {"type": "text", "text": "Checking."}
    assert response["content"][2]["type"] == "tool_use"
    assert response["content"][2]["name"] == "web_search"
    assert response["content"][2]["input"] == {"query": "weather in Moscow"}
    assert response["stop_reason"] == "tool_use"


def test_build_anthropic_response_coerces_non_object_function_arguments() -> None:
    response = _build_anthropic_response(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "function_call": {
                            "name": "get_weather",
                            "arguments": '["Moscow"]',
                        },
                    },
                    "finish_reason": "function_call",
                }
            ],
            "usage": {
                "prompt_tokens": 3,
                "completion_tokens": 1,
                "total_tokens": 4,
            },
        },
        "claude-test",
        "resp-anthropic-scalar",
    )

    assert response["content"] == [
        {
            "type": "tool_use",
            "id": response["content"][0]["id"],
            "name": "get_weather",
            "input": {},
        }
    ]
