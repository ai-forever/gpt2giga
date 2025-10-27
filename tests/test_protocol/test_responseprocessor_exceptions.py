from types import SimpleNamespace

from gpt2giga.protocol import ResponseProcessor


def test_process_stream_chunk_response_tool_call_branch():
    rp = ResponseProcessor()
    giga = SimpleNamespace(
        dict=lambda: {
            "choices": [
                {
                    "delta": {
                        "function_call": {"name": "x", "arguments": {}},
                        "functions_state_id": "1",
                        "role": "assistant",
                        "content": None,
                    }
                }
            ]
        }
    )
    out = rp.process_stream_chunk_response(giga, sequence_number=1)
    # либо ResponseTextDeltaEvent, либо output message list при tool_call
    assert out
