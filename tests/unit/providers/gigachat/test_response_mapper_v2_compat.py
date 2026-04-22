from __future__ import annotations

from gpt2giga.providers.gigachat import ResponseProcessor


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self, *args, **kwargs):
        return self.data


def test_normalize_chat_v2_response_maps_builtin_tool_execution_to_function_call():
    normalized = ResponseProcessor.normalize_chat_v2_response(
        MockResponse(
            {
                "model": "gpt-x",
                "messages": [
                    {
                        "role": "assistant",
                        "tools_state_id": "tool-state-1",
                        "content": [
                            {
                                "tool_execution": {
                                    "name": "web_search",
                                    "status": "searching",
                                }
                            }
                        ],
                    }
                ],
                "finish_reason": "stop",
                "usage": {
                    "input_tokens": 2,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens": 1,
                    "total_tokens": 3,
                },
            }
        )
    )

    choice = normalized["choices"][0]
    assert choice["message"]["function_call"] == {
        "name": "web_search",
        "arguments": {},
    }
    assert choice["message"]["functions_state_id"] == "tool-state-1"
    assert choice["finish_reason"] == "function_call"


def test_normalize_chat_v2_stream_chunk_maps_builtin_tool_execution_to_delta():
    normalized = ResponseProcessor.normalize_chat_v2_stream_chunk(
        MockResponse(
            {
                "model": "gpt-x",
                "messages": [
                    {
                        "role": "assistant",
                        "tools_state_id": "tool-state-2",
                        "content": [
                            {
                                "tool_execution": {
                                    "name": "image_generate",
                                    "status": "generating",
                                }
                            }
                        ],
                    }
                ],
            }
        )
    )

    choice = normalized["choices"][0]
    assert choice["delta"] == {
        "role": "assistant",
        "function_call": {
            "name": "image_generate",
            "arguments": {},
        },
        "functions_state_id": "tool-state-2",
    }
    assert choice["finish_reason"] == "function_call"
