from gpt2giga_harness.protocols.openai import (
    OpenAIChatCompletionStreamAccumulator,
)


def test_chat_completion_stream_accumulator_rebuilds_content_tools_and_usage():
    accumulator = OpenAIChatCompletionStreamAccumulator()

    events = accumulator.observe_chunk(
        b'data: {"id":"req-1","model":"GigaChat","choices":'
        b'[{"index":0,"delta":{"content":"Hi","tool_calls":'
        b'[{"index":0,"id":"call-1","type":"function","function":'
        b'{"name":"lookup","arguments":"{\\"q\\":"}}]}}]}\n\n'
        b'data: {"choices":[{"index":0,"delta":{"tool_calls":'
        b'[{"index":0,"function":{"arguments":"\\"ping\\"}"}}]},'
        b'"finish_reason":"tool_calls"}],"usage":{"prompt_tokens":1,'
        b'"completion_tokens":2,"total_tokens":3}}\n\n'
        b"data: [DONE]\n\n"
    )
    response = accumulator.to_normalized_response()

    assert [event.type for event in events] == [
        "content_delta",
        "tool_call_start",
        "tool_call_delta",
        "message_end",
        "usage",
    ]
    assert response.choices[0].message.content == "Hi"
    assert response.choices[0].message.tool_calls[0].arguments == '{"q":"ping"}'
    assert response.usage.total_tokens == 3


def test_chat_completion_stream_accumulator_keeps_distinct_tools_reusing_index_zero():
    accumulator = OpenAIChatCompletionStreamAccumulator()

    first = accumulator.observe_payload(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "agent-call",
                                "type": "function",
                                "function": {
                                    "name": "invoke_agent",
                                    "arguments": "{}",
                                },
                            }
                        ]
                    }
                }
            ]
        }
    )
    second = accumulator.observe_payload(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "child-call",
                                "type": "function",
                                "function": {
                                    "name": "shell",
                                    "arguments": '{"command":"pwd"}',
                                },
                            }
                        ]
                    }
                }
            ]
        }
    )

    assert [event.type for event in (*first, *second)] == [
        "tool_call_start",
        "tool_call_start",
    ]
    assert [
        tool_call.id
        for tool_call in accumulator.to_normalized_response()
        .choices[0]
        .message.tool_calls
    ] == ["agent-call", "child-call"]
