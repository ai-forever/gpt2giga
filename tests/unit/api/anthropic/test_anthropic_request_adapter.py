from gpt2giga.api.anthropic.request_adapter import (
    build_normalized_chat_request,
    build_token_count_texts,
)


def test_build_normalized_chat_request_converts_messages_tools_and_options():
    request = build_normalized_chat_request(
        {
            "model": "claude-test",
            "system": [{"type": "text", "text": "Be brief"}],
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "Hi"}]},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Checking"},
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "lookup_weather",
                            "input": {"city": "Moscow"},
                        },
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_1",
                            "content": "sunny",
                        }
                    ],
                },
            ],
            "tools": [
                {
                    "name": "lookup_weather",
                    "description": "Look up weather.",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ],
            "tool_choice": {"type": "tool", "name": "lookup_weather"},
            "max_tokens": 128,
            "thinking": {"type": "enabled", "budget_tokens": 4000},
            "stream": True,
        }
    )

    assert request.model == "claude-test"
    assert request.stream is True
    assert [message.role for message in request.messages] == [
        "system",
        "user",
        "assistant",
        "tool",
    ]
    assert request.messages[0].content == "Be brief"
    assert request.messages[2].tool_calls[0]["function"]["name"] == "lookup_weather"
    assert request.messages[3].name == "lookup_weather"
    assert request.messages[3].tool_call_id == "toolu_1"
    assert request.tools[0].name == "lookup_weather"
    assert request.options["max_tokens"] == 128
    assert request.options["reasoning_effort"] == "medium"
    assert request.options["function_call"] == {"name": "lookup_weather"}
    assert len(request.options["functions"]) == 1


def test_build_token_count_texts_collects_visible_texts_and_tool_definitions():
    texts = build_token_count_texts(
        {
            "system": "Be brief",
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "Hello"}]},
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Hi there"}],
                },
            ],
            "tools": [
                {
                    "name": "lookup_weather",
                    "description": "Look up weather.",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ],
        }
    )

    assert "Be brief" in texts
    assert "Hello" in texts
    assert "Hi there" in texts
    assert any("lookup_weather" in text for text in texts)
