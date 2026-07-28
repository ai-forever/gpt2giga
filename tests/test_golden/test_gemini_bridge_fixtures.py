import json
from pathlib import Path

from gpt2giga.protocols.gemini import (
    normalized_chat_response_to_gemini,
    normalized_stream_event_to_gemini_sse,
)
from gpt2giga.protocols.normalized import (
    NormalizedChoice,
    NormalizedError,
    NormalizedMessage,
    NormalizedResponse,
    NormalizedStreamEvent,
    NormalizedToolCall,
    NormalizedUsage,
)
from gpt2giga.routers.gemini.models import build_gemini_model_list


FIXTURES = Path(__file__).parents[1] / "golden" / "gemini"


def _load_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_gemini_generate_content_matches_golden_fixture():
    actual = normalized_chat_response_to_gemini(
        NormalizedResponse(
            id="response-1",
            model="fixture-model",
            choices=[
                NormalizedChoice(
                    index=0,
                    message=NormalizedMessage(role="assistant", content="Hello!"),
                    finish_reason="stop",
                )
            ],
            usage=NormalizedUsage(
                input_tokens=4,
                output_tokens=2,
                total_tokens=6,
            ),
        ),
        requested_model="fixture-model",
    )

    assert actual == _load_json("generate_content.json")


def test_gemini_function_call_matches_golden_fixture():
    actual = normalized_chat_response_to_gemini(
        NormalizedResponse(
            id="response-tool-1",
            model="fixture-model",
            choices=[
                NormalizedChoice(
                    index=0,
                    message=NormalizedMessage(
                        role="assistant",
                        tool_calls=[
                            NormalizedToolCall(
                                id="call-1",
                                name="lookup",
                                arguments={"q": "ping"},
                            )
                        ],
                    ),
                    finish_reason="tool_calls",
                )
            ],
            usage=NormalizedUsage(
                input_tokens=8,
                output_tokens=3,
                total_tokens=11,
            ),
        ),
        requested_model="fixture-model",
    )

    assert actual == _load_json("function_call.json")


def test_gemini_stream_matches_golden_fixture():
    events = [
        NormalizedStreamEvent(
            type="content_delta",
            id="response-stream-1",
            model="fixture-model",
            choice_index=0,
            content_delta="Hello",
        ),
        NormalizedStreamEvent(
            type="message_end",
            id="response-stream-1",
            model="fixture-model",
            choice_index=0,
            finish_reason="stop",
            usage=NormalizedUsage(
                input_tokens=4,
                output_tokens=1,
                total_tokens=5,
            ),
        ),
    ]
    actual = "".join(
        frame
        for event in events
        if (
            frame := normalized_stream_event_to_gemini_sse(
                event,
                requested_model="fixture-model",
                response_id="response-stream-1",
            )
        )
        is not None
    )

    assert actual == _load_json("stream_generate_content.json")["body"]


def test_gemini_safety_error_matches_golden_fixture():
    actual = normalized_chat_response_to_gemini(
        NormalizedResponse(
            error=NormalizedError(
                type="SAFETY",
                message="The response was blocked by the upstream safety policy.",
                code=400,
                error_class="invalid_request",
                retryable=False,
            )
        ),
        requested_model="fixture-model",
    )

    assert actual == _load_json("safety_error.json")


def test_gemini_model_list_matches_golden_fixture():
    actual = build_gemini_model_list(
        [
            {
                "id": "fixture-model",
                "owned_by": "fixture",
                "input_token_limit": 8192,
                "output_token_limit": 2048,
                "capabilities": ["chat", "generation"],
            }
        ]
    )

    assert actual == _load_json("models.json")
