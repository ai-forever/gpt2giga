from gpt2giga.protocols.anthropic import normalized_response_to_anthropic_message
from gpt2giga.protocols.normalized import (
    NormalizedChoice,
    NormalizedMessage,
    NormalizedResponse,
    NormalizedToolCall,
)


def test_normalized_response_to_anthropic_maps_tool_use():
    response = NormalizedResponse(
        id="req-1",
        choices=[
            NormalizedChoice(
                index=0,
                message=NormalizedMessage(
                    role="assistant",
                    content=None,
                    tool_calls=[
                        NormalizedToolCall(
                            id="call_write",
                            name="write_file",
                            arguments={
                                "file_path": "hello.py",
                                "content": "print(1)",
                            },
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )
        ],
    )

    payload = normalized_response_to_anthropic_message(
        response,
        requested_model="claude-test",
        response_id="rq-1",
    )

    assert payload["stop_reason"] == "tool_use"
    assert payload["content"] == [
        {
            "type": "tool_use",
            "id": "call_write",
            "name": "write_file",
            "input": {
                "file_path": "hello.py",
                "content": "print(1)",
            },
        }
    ]
