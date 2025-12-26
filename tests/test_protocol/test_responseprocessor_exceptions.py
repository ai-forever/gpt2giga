from loguru import logger

from gpt2giga.protocol import ResponseProcessor


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self):
        return self.data


def test_process_stream_chunk_response_tool_call_branch():
    rp = ResponseProcessor(logger=logger)
    giga = MockResponse(
        {
            "choices": [
                {
                    "delta": {
                        "function_call": {"name": "x", "arguments": {}},
                        "functions_state_id": "1",
                        "role": "assistant",
                        "content": None,
                        "finish_reason": None,  # Add this to avoid potential error if expected
                    }
                }
            ],
            # Add usage to match structure if needed, though dict passed doesn't have it in original
            "usage": None,
        }
    )
    # The original test code had dict with choices and inside choices delta with function_call.
    # Note: original code had finish_reason inside delta? No, inside choices usually.
    # Original:
    # "choices": [
    #     {
    #         "delta": { ... },
    #         # where is finish_reason?
    #     }
    # ]
    # process_stream_chunk_response calls giga.model_dump()
    # then accesses giga_dict["choices"][0]["delta"]
    # So the structure seems fine.

    out = rp.process_stream_chunk_response(giga, sequence_number=1)
    # либо ResponseTextDeltaEvent, либо output message list при tool_call
    assert out
