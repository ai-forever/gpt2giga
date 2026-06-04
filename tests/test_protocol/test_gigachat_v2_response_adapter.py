from types import SimpleNamespace

from gigachat.models import ChatCompletionResponse
from gigachat.models.chat_completions import ChatCompletionChunk
from loguru import logger

from gpt2giga.protocol.response.gigachat_v2_adapter import (
    adapt_v2_chunk_to_v1_shape,
    adapt_v2_completion_to_v1_shape,
    adapt_v2_usage,
    extract_v2_assistant_text,
    extract_v2_function_call,
    extract_v2_reasoning_text,
)
from gpt2giga.protocol.response.processor import ResponseProcessor


def test_adapt_v2_completion_text_to_v1_shape():
    response = ChatCompletionResponse.model_validate(
        {
            "model": "GigaChat-2-Max",
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"text": "Hel"}, {"text": "lo"}],
                }
            ],
            "finish_reason": "stop",
            "usage": {
                "input_tokens": 2,
                "output_tokens": 3,
                "total_tokens": 5,
                "input_tokens_details": {"cached_tokens": 1},
            },
        }
    )

    adapted = adapt_v2_completion_to_v1_shape(response, default_model="fallback")

    assert adapted["model"] == "GigaChat-2-Max"
    assert adapted["choices"][0]["message"]["content"] == "Hello"
    assert adapted["choices"][0]["finish_reason"] == "stop"
    assert adapted["usage"] == {
        "prompt_tokens": 2,
        "completion_tokens": 3,
        "total_tokens": 5,
        "precached_prompt_tokens": 1,
    }


def test_adapt_v2_completion_reasoning_role_to_v1_reasoning_content():
    response = ChatCompletionResponse.model_validate(
        {
            "model": "GigaChat-2-Max",
            "messages": [
                {
                    "role": "reasoning",
                    "content": [{"text": "This is a simple geography fact."}],
                },
                {
                    "role": "assistant",
                    "content": [{"text": "Paris"}],
                },
            ],
            "finish_reason": "stop",
            "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
        }
    )

    adapted = adapt_v2_completion_to_v1_shape(response, default_model="fallback")
    message = adapted["choices"][0]["message"]

    assert message["role"] == "assistant"
    assert message["content"] == "Paris"
    assert message["reasoning_content"] == "This is a simple geography fact."
    assert extract_v2_assistant_text(response) == "Paris"
    assert extract_v2_reasoning_text(response) == "This is a simple geography fact."


def test_adapt_v2_completion_function_call_to_v1_shape():
    response = ChatCompletionResponse.model_validate(
        {
            "messages": [
                {
                    "role": "assistant",
                    "message_id": "msg_1",
                    "function_call": {
                        "name": "__gpt2giga_user_search_web",
                        "arguments": {"query": "cats"},
                    },
                }
            ],
            "usage": {"input_tokens": 1, "output_tokens": 0},
        }
    )

    adapted = adapt_v2_completion_to_v1_shape(response, default_model="fallback")
    message = adapted["choices"][0]["message"]

    assert adapted["model"] == "fallback"
    assert adapted["choices"][0]["finish_reason"] == "function_call"
    assert message["content"] is None
    assert message["function_call"] == {
        "name": "__gpt2giga_user_search_web",
        "arguments": {"query": "cats"},
    }
    assert message["functions_state_id"] == "msg_1"
    assert adapted["usage"]["total_tokens"] == 1


def test_adapted_v2_completion_can_flow_through_response_processor():
    response = ChatCompletionResponse.model_validate(
        {
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"text": "done"}],
                }
            ],
            "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
        }
    )
    adapted = adapt_v2_completion_to_v1_shape(response, default_model="fallback")

    processor = ResponseProcessor(logger=logger)
    processed = processor.process_response(
        SimpleNamespace(model_dump=lambda: adapted),
        gpt_model="gpt-x",
        response_id="v2",
    )

    assert processed["object"] == "chat.completion"
    assert processed["choices"][0]["message"]["content"] == "done"
    assert processed["usage"]["prompt_tokens"] == 1
    assert processed["usage"]["completion_tokens"] == 2


def test_adapted_v2_reasoning_flows_through_response_processors():
    response = ChatCompletionResponse.model_validate(
        {
            "messages": [
                {
                    "role": "reasoning",
                    "content": [{"text": "Use the capital-city fact."}],
                },
                {
                    "role": "assistant",
                    "content": [{"text": "Paris"}],
                },
            ],
            "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
        }
    )
    adapted = adapt_v2_completion_to_v1_shape(response, default_model="fallback")

    processor = ResponseProcessor(logger=logger)
    chat = processor.process_response(
        SimpleNamespace(model_dump=lambda: adapted),
        gpt_model="gpt-x",
        response_id="v2",
    )
    responses = processor.process_response_api(
        {"model": "gpt-x", "input": "Capital of France"},
        SimpleNamespace(model_dump=lambda: adapted),
        gpt_model="gpt-x",
        response_id="v2",
    )

    assert chat["choices"][0]["message"]["content"] == "Paris"
    assert chat["choices"][0]["message"]["reasoning_content"] == (
        "Use the capital-city fact."
    )
    assert responses["output"][0]["type"] == "reasoning"
    assert responses["output"][0]["summary"][0]["text"] == (
        "Use the capital-city fact."
    )
    assert responses["output"][1]["type"] == "message"
    assert responses["output"][1]["content"][0]["text"] == "Paris"


def test_adapted_v2_function_call_unmaps_reserved_tool_name_through_processor():
    response = ChatCompletionResponse.model_validate(
        {
            "messages": [
                {
                    "role": "assistant",
                    "message_id": "msg_1",
                    "function_call": {
                        "name": "__gpt2giga_user_search_web",
                        "arguments": {"query": "cats"},
                    },
                }
            ],
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        }
    )
    adapted = adapt_v2_completion_to_v1_shape(response, default_model="fallback")

    processor = ResponseProcessor(logger=logger)
    processed = processor.process_response(
        SimpleNamespace(model_dump=lambda: adapted),
        gpt_model="gpt-x",
        response_id="v2",
    )

    tool_call = processed["choices"][0]["message"]["tool_calls"][0]
    assert tool_call["function"]["name"] == "web_search"
    assert tool_call["function"]["arguments"] == '{"query": "cats"}'


def test_extract_v2_function_call_from_content_part():
    message = {
        "role": "assistant",
        "content": [
            {
                "function_call": {
                    "name": "lookup",
                    "arguments": {"id": 1},
                }
            }
        ],
    }

    assert extract_v2_function_call(message) == {
        "name": "lookup",
        "arguments": {"id": 1},
    }


def test_extract_v2_assistant_text_selects_assistant_message():
    response = {
        "messages": [
            {"role": "user", "content": [{"text": "ignored"}]},
            {"role": "assistant", "content": [{"text": "used"}]},
        ]
    }

    assert extract_v2_assistant_text(response) == "used"


def test_adapt_v2_chunk_text_to_v1_shape():
    chunk = ChatCompletionChunk.model_validate(
        {
            "model": "GigaChat-2-Max",
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"text": "Hi"}],
                }
            ],
        }
    )

    adapted = adapt_v2_chunk_to_v1_shape(chunk, default_model="fallback")

    assert adapted["model"] == "GigaChat-2-Max"
    assert adapted["choices"][0]["delta"] == {
        "content": "Hi",
        "role": "assistant",
    }
    assert adapted["choices"][0]["finish_reason"] is None
    assert adapted["usage"] is None


def test_adapt_v2_chunk_reasoning_role_to_v1_delta_reasoning_content():
    chunk = ChatCompletionChunk.model_validate(
        {
            "messages": [
                {
                    "role": "reasoning",
                    "content": [{"text": "Think first."}],
                }
            ],
        }
    )

    adapted = adapt_v2_chunk_to_v1_shape(chunk, default_model="fallback")
    delta = adapted["choices"][0]["delta"]

    assert delta["role"] == "assistant"
    assert delta["content"] == ""
    assert delta["reasoning_content"] == "Think first."


def test_adapt_v2_chunk_usage_only_does_not_fail():
    chunk = ChatCompletionChunk.model_validate(
        {
            "usage": {
                "input_tokens": 4,
                "output_tokens": 5,
                "total_tokens": 9,
            }
        }
    )

    adapted = adapt_v2_chunk_to_v1_shape(chunk, default_model="fallback")

    assert adapted["choices"][0]["delta"] == {"content": ""}
    assert adapted["choices"][0]["finish_reason"] is None
    assert adapted["usage"]["prompt_tokens"] == 4
    assert adapted["usage"]["completion_tokens"] == 5


def test_adapt_v2_usage_returns_none_for_missing_usage():
    assert adapt_v2_usage(None) is None
