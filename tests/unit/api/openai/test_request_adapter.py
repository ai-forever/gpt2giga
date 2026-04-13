from gpt2giga.api.openai.request_adapter import (
    build_normalized_chat_request,
    build_normalized_embeddings_request,
    build_normalized_responses_request,
)


def test_build_normalized_chat_request_converts_messages_and_tools():
    request = build_normalized_chat_request(
        {
            "model": "gpt-x",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            "temperature": 0.7,
        }
    )

    assert request.model == "gpt-x"
    assert request.stream is True
    assert request.messages[0].role == "user"
    assert request.messages[0].content == "hi"
    assert request.tools[0].name == "lookup"
    assert request.options["temperature"] == 0.7
    assert len(request.options["functions"]) == 1


def test_build_normalized_chat_request_accepts_input_fallback():
    request = build_normalized_chat_request({"model": "gpt-x", "input": "hi"})

    assert request.messages[0].to_openai_message() == {
        "role": "user",
        "content": "hi",
    }


def test_build_normalized_responses_request_preserves_function_history_items():
    request = build_normalized_responses_request(
        {
            "model": "gpt-x",
            "instructions": "answer briefly",
            "input": [
                {"role": "user", "content": "hi"},
                {"type": "function_call", "name": "lookup", "arguments": "{}"},
            ],
        }
    )

    assert request.model == "gpt-x"
    assert request.instructions == "answer briefly"
    assert request.input[0].to_openai_message() == {
        "role": "user",
        "content": "hi",
    }
    assert request.input[1] == {
        "type": "function_call",
        "name": "lookup",
        "arguments": "{}",
    }


def test_build_normalized_responses_request_allows_missing_model_for_thread_continuation():
    request = build_normalized_responses_request(
        {
            "input": "continue",
            "previous_response_id": "resp_prev",
        }
    )

    assert request.model is None
    assert request.input == "continue"
    assert request.options["previous_response_id"] == "resp_prev"


def test_build_normalized_embeddings_request_keeps_additional_options():
    request = build_normalized_embeddings_request(
        {
            "model": "gpt-x",
            "input": [1, 2, 3],
            "encoding_format": "float",
        }
    )

    assert request.model == "gpt-x"
    assert request.input == [1, 2, 3]
    assert request.options == {"encoding_format": "float"}
