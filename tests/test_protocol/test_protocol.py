from unittest.mock import MagicMock

import pytest

from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import AttachmentProcessor, RequestTransformer, ResponseProcessor
from loguru import logger


class DummyClient:
    def __init__(self):
        self.called = False


def test_attachment_processor_construction():
    p = AttachmentProcessor(logger)
    assert hasattr(p, "upload_file")


@pytest.mark.asyncio
async def test_request_transformer_collapse_messages():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger)
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "user", "content": "world"},
    ]
    data = {"messages": messages}
    chat = await rt.send_to_gigachat(data)
    # После collapse два подряд user должны склеиться
    # chat is now a dict
    assert len(chat["messages"]) == 1
    assert (
        "hello" in chat["messages"][0]["content"]
        and "world" in chat["messages"][0]["content"]
    )


@pytest.mark.asyncio
async def test_request_transformer_tools_to_functions():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger)
    data = {
        "model": "GigaChat-2-Max",
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "sum",
                    "description": "calc",
                    "parameters": {
                        "type": "object",
                        "properties": {"a": {"type": "number"}},
                    },
                },
            }
        ],
        "messages": [{"role": "user", "content": "hi"}],
    }
    chat = await rt.send_to_gigachat(data)
    # chat is dict
    assert chat.get("functions") and len(chat["functions"]) == 1


@pytest.mark.asyncio
async def test_request_transformer_dev_debug_logging_includes_full_payload():
    mock_logger = MagicMock()
    mock_bound_logger = MagicMock()
    mock_logger.bind.return_value = mock_bound_logger
    cfg = ProxyConfig(proxy=ProxySettings(mode="DEV"))
    rt = RequestTransformer(cfg, mock_logger)

    await rt.send_to_gigachat(
        {"model": "GigaChat", "messages": [{"role": "user", "content": "hello"}]}
    )

    bind_kwargs = mock_logger.bind.call_args.kwargs
    assert bind_kwargs["event"] == "gigachat_request"
    assert bind_kwargs["payload"]["model"] == "GigaChat"
    assert bind_kwargs["payload"]["messages"][0]["content"] == "hello"
    mock_bound_logger.debug.assert_called_with("Sending request to GigaChat API")


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self):
        return self.data


def test_response_processor_process_function_call():
    rp = ResponseProcessor(logger)
    # Синтетический ответ GigaChat с function_call
    giga_resp = MockResponse(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "function_call": {"name": "sum", "arguments": {"a": 1}},
                    },
                    "finish_reason": "function_call",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )

    out = rp.process_response(giga_resp, gpt_model="gpt-x", response_id="1")
    choice = out["choices"][0]
    assert choice["message"]["tool_calls"][0]["type"] == "function"


def test_response_processor_dev_debug_logging_includes_full_response():
    mock_logger = MagicMock()
    mock_bound_logger = MagicMock()
    mock_logger.bind.return_value = mock_bound_logger
    rp = ResponseProcessor(mock_logger, mode="DEV")
    giga_resp = MockResponse(
        {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )

    out = rp.process_response(giga_resp, gpt_model="gpt-x", response_id="1")

    bind_kwargs = mock_logger.bind.call_args.kwargs
    assert bind_kwargs["event"] == "chat_completion_response"
    assert bind_kwargs["response"] == out
    assert bind_kwargs["response"]["choices"][0]["message"]["content"] == "Hello!"
    mock_bound_logger.debug.assert_called_with("Processed chat completion response")


def test_response_processor_adds_gigachat_headers_to_chat_metadata():
    rp = ResponseProcessor(logger)
    giga_resp = MockResponse(
        {
            "x_headers": {
                "X-Request-ID": "rq-1",
                "X-Session-ID": "session-1",
                "Authorization": "Bearer secret",
            },
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )

    out = rp.process_response(giga_resp, gpt_model="gpt-x", response_id="1")

    assert out["metadata"] == {
        "gigachat_x_request_id": "rq-1",
        "gigachat_x_session_id": "session-1",
    }
    assert "x_headers" not in out


def test_response_processor_merges_gigachat_headers_into_responses_metadata():
    rp = ResponseProcessor(logger)
    giga_resp = MockResponse(
        {
            "x_headers": {
                "x-request-id": "rq-1",
                "x-session-id": "session-1",
            },
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )

    out = rp.process_response_api(
        {"metadata": {"user_id": "user-1"}},
        giga_resp,
        gpt_model="gpt-x",
        response_id="1",
    )

    assert out["metadata"] == {
        "user_id": "user-1",
        "gigachat_x_request_id": "rq-1",
        "gigachat_x_session_id": "session-1",
    }


def test_response_processor_prod_debug_logging_omits_response():
    mock_logger = MagicMock()
    mock_bound_logger = MagicMock()
    mock_logger.bind.return_value = mock_bound_logger
    rp = ResponseProcessor(mock_logger, mode="PROD")
    giga_resp = MockResponse(
        {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "secret response"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )

    rp.process_response(giga_resp, gpt_model="gpt-x", response_id="1")

    bind_kwargs = mock_logger.bind.call_args.kwargs
    assert bind_kwargs == {"event": "chat_completion_response"}
    mock_bound_logger.debug.assert_called_with(
        "Processed chat completion response (payload omitted in PROD)"
    )


def test_response_processor_native_so_preserves_chat_tool_call():
    rp = ResponseProcessor(logger, structured_output_mode="native")
    giga_resp = MockResponse(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "function_call": {"name": "sum", "arguments": {"a": 1}},
                    },
                    "finish_reason": "function_call",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )

    out = rp.process_response(
        giga_resp,
        gpt_model="gpt-x",
        response_id="1",
        request_data={
            "response_format": {
                "type": "json_schema",
                "json_schema": {"schema": {"type": "object"}},
            }
        },
    )

    choice = out["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"][0]["function"]["name"] == "sum"
    assert "function_call" not in choice["message"]


def test_response_processor_unmaps_reserved_tool_name_web_search():
    rp = ResponseProcessor(logger)
    giga_resp = MockResponse(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "function_call": {
                            "name": "__gpt2giga_user_search_web",
                            "arguments": {"query": "hi"},
                        },
                    },
                    "finish_reason": "function_call",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )
    out = rp.process_response(giga_resp, gpt_model="gpt-x", response_id="1")
    tool_calls = out["choices"][0]["message"]["tool_calls"]
    assert tool_calls[0]["function"]["name"] == "web_search"


def test_response_processor_preserves_backend_state_as_tool_call_id():
    rp = ResponseProcessor(logger)
    giga_resp = MockResponse(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "function_call": {
                            "name": "write_file",
                            "arguments": {"file_path": "/app/regex.txt"},
                        },
                        "functions_state_id": "019e94aa-de11-705c-998b-040af4d06462",
                    },
                    "finish_reason": "function_call",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )

    out = rp.process_response(giga_resp, gpt_model="gpt-x", response_id="1")

    tool_call = out["choices"][0]["message"]["tool_calls"][0]
    assert tool_call["id"] == "019e94aa-de11-705c-998b-040af4d06462"
    assert tool_call["function"]["name"] == "write_file"


def test_response_processor_stream_chunk_handles_delta():
    rp = ResponseProcessor(logger)
    giga_resp = MockResponse(
        {
            "choices": [
                {
                    "delta": {
                        "role": "assistant",
                        "content": "hel",
                    }
                }
            ],
            "usage": None,
        }
    )
    out = rp.process_stream_chunk(giga_resp, gpt_model="gpt-x", response_id="1")
    assert out["object"] == "chat.completion.chunk"


def test_response_processor_extracts_think_tags_non_stream():
    rp = ResponseProcessor(logger)
    giga_resp = MockResponse(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "<think>use arithmetic</think>The answer is 42.",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )

    out = rp.process_response(giga_resp, gpt_model="gpt-x", response_id="1")
    message = out["choices"][0]["message"]
    assert message["content"] == "The answer is 42."
    assert message["reasoning_content"] == "use arithmetic"


def test_response_processor_extracts_split_think_tags_stream():
    rp = ResponseProcessor(logger)
    chunks = [
        MockResponse({"choices": [{"delta": {"content": "A<th"}}], "usage": None}),
        MockResponse(
            {"choices": [{"delta": {"content": "ink>reason"}}], "usage": None}
        ),
        MockResponse(
            {
                "choices": [
                    {
                        "delta": {"content": "</think>B"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": None,
            }
        ),
    ]

    outputs = [
        rp.process_stream_chunk(chunk, gpt_model="gpt-x", response_id="split-1")
        for chunk in chunks
    ]

    assert outputs[0]["choices"][0]["delta"]["content"] == "A"
    assert outputs[1]["choices"][0]["delta"]["content"] == ""
    assert outputs[1]["choices"][0]["delta"]["reasoning_content"] == "reason"
    assert outputs[2]["choices"][0]["delta"]["content"] == "B"
    assert "reasoning_content" not in outputs[2]["choices"][0]["delta"]


def test_response_processor_process_response_api_includes_reasoning_item():
    rp = ResponseProcessor(logger)
    giga_resp = MockResponse(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Paris",
                        "reasoning_content": "This is a simple geography fact.",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )
    out = rp.process_response_api(
        {
            "model": "gpt-x",
            "input": "Capital of France",
            "reasoning": {"effort": "high", "summary": "auto"},
        },
        giga_resp,
        gpt_model="gpt-x",
        response_id="resp-1",
    )
    assert out["reasoning"] == {"effort": "high", "summary": "auto"}
    assert out["output"][0]["type"] == "reasoning"
    assert out["output"][0]["summary"][0]["type"] == "summary_text"
    assert out["output"][0]["summary"][0]["text"] == "This is a simple geography fact."
    assert out["output"][1]["type"] == "message"
    assert out["output"][1]["content"][0]["text"] == "Paris"


def test_response_processor_native_so_preserves_responses_tool_call():
    rp = ResponseProcessor(logger, structured_output_mode="native")
    giga_resp = MockResponse(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "function_call": {
                            "name": "sum",
                            "arguments": {"a": 1},
                        },
                        "functions_state_id": "state-1",
                    },
                    "finish_reason": "function_call",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )

    out = rp.process_response_api(
        {
            "model": "gpt-x",
            "input": "add",
            "text": {
                "format": {
                    "type": "json_schema",
                    "schema": {"type": "object"},
                }
            },
        },
        giga_resp,
        gpt_model="gpt-x",
        response_id="resp-1",
    )

    assert out["output"][0]["type"] == "function_call"
    assert out["output"][0]["name"] == "sum"
    assert out["output"][0]["arguments"] == '{"a": 1}'
    assert out["output"][0]["call_id"] == "state-1"
    assert out["output"][0]["id"] == "fc_state-1"


def test_response_processor_response_api_extracts_think_tags():
    rp = ResponseProcessor(logger)
    giga_resp = MockResponse(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "<think>First, reason.</think>Final.",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )
    out = rp.process_response_api(
        {"model": "gpt-x", "input": "hi"},
        giga_resp,
        gpt_model="gpt-x",
        response_id="resp-think",
    )
    assert out["output"][0]["type"] == "reasoning"
    assert out["output"][0]["summary"][0]["text"] == "First, reason."
    assert out["output"][1]["content"][0]["text"] == "Final."


def test_response_processor_tool_calls_include_index():
    """Test that tool_calls include index field required by OpenAI SDK for streaming"""
    rp = ResponseProcessor(logger)
    # Non-streaming response with function_call
    giga_resp = MockResponse(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "function_call": {
                            "name": "browser_action",
                            "arguments": {"action": "click"},
                        },
                    },
                    "finish_reason": "function_call",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
    )
    out = rp.process_response(giga_resp, gpt_model="gpt-x", response_id="test-1")
    tool_calls = out["choices"][0]["message"]["tool_calls"]
    assert len(tool_calls) == 1
    assert "index" in tool_calls[0], (
        "tool_calls must include 'index' field for OpenAI SDK compatibility"
    )
    assert tool_calls[0]["index"] == 0


def test_response_processor_stream_tool_calls_include_index():
    """Test that streaming tool_calls include index field required by OpenAI SDK"""
    rp = ResponseProcessor(logger)
    # Streaming response with function_call
    giga_resp = MockResponse(
        {
            "choices": [
                {
                    "delta": {
                        "role": "assistant",
                        "content": "",
                        "function_call": {
                            "name": "task",
                            "arguments": {"command": "/explore"},
                        },
                    },
                    "finish_reason": "function_call",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
    )
    out = rp.process_stream_chunk(
        giga_resp, gpt_model="gpt-x", response_id="test-stream-1"
    )
    tool_calls = out["choices"][0]["delta"]["tool_calls"]
    assert len(tool_calls) == 1
    assert "index" in tool_calls[0], "streaming tool_calls must include 'index' field"
    assert tool_calls[0]["index"] == 0
