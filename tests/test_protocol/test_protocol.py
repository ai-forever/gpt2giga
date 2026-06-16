import json
from unittest.mock import MagicMock

from gigachat.models import Chat
from loguru import logger

from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import AttachmentProcessor, RequestTransformer, ResponseProcessor


class DummyClient:
    def __init__(self):
        self.called = False


def _kilocode_nullable_parameters():
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["launch", "click"]},
            "url": {"type": ["string", "null"], "description": "URL to navigate to"},
            "coordinate": {
                "type": ["string", "null"],
                "description": "Screen coordinate for click actions",
            },
            "size": {
                "type": ["string", "null"],
                "description": "Viewport dimensions",
            },
            "text": {
                "type": ["string", "null"],
                "description": "Text to type",
            },
            "path": {
                "type": ["string", "null"],
                "description": "Screenshot output path",
            },
        },
        "required": ["action", "url", "coordinate", "size", "text", "path"],
        "additionalProperties": False,
    }


def test_attachment_processor_construction():
    p = AttachmentProcessor(logger)
    assert hasattr(p, "upload_file")


async def test_request_transformer_collapse_messages():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger)
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "user", "content": "world"},
    ]
    data = {"messages": messages}
    chat = await rt.prepare_chat(data)
    # После collapse два подряд user должны склеиться
    # chat is now a dict
    assert len(chat["messages"]) == 1
    assert (
        "hello" in chat["messages"][0]["content"]
        and "world" in chat["messages"][0]["content"]
    )


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
    chat = await rt.prepare_chat(data)
    # chat is dict
    assert chat.get("functions") and len(chat["functions"]) == 1


async def test_prepare_chat_keeps_tool_result_state_for_legacy_gigachat():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger)

    chat = await rt.prepare_chat(
        {
            "model": "GigaChat-2-Max",
            "messages": [
                {"role": "user", "content": "Weather?"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "019ed0c7-f14d-7cae-8dc6-ff8d01d617e4",
                            "type": "function",
                            "function": {
                                "name": "get_weather",
                                "arguments": '{"city": "Москва"}',
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "019ed0c7-f14d-7cae-8dc6-ff8d01d617e4",
                    "content": '{"city": "Москва", "temp": "+5°C"}',
                },
            ],
        }
    )

    assert "functions_state_id" not in chat["messages"][1]
    assert chat["messages"][2]["functions_state_id"] == (
        "019ed0c7-f14d-7cae-8dc6-ff8d01d617e4"
    )


async def test_prepare_chat_strips_assistant_state_from_legacy_function_history():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger)

    state_id = "019ed0fe-194e-7e50-87b1-16acc2509040"
    chat = await rt.prepare_chat(
        {
            "model": "GigaChat-2-Max",
            "messages": [
                {"role": "user", "content": "Какая погода в Москве?"},
                {
                    "role": "assistant",
                    "content": "",
                    "function_call": {
                        "name": "get_weather",
                        "arguments": {"city": "Москва"},
                    },
                    "functions_state_id": state_id,
                },
                {
                    "role": "function",
                    "content": (
                        '{"city": "Москва", "temp": "+5°C", "conditions": "облачно"}'
                    ),
                    "name": "get_weather",
                    "functions_state_id": state_id,
                },
            ],
            "functions": [
                {
                    "name": "get_weather",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                        "required": ["city"],
                    },
                }
            ],
        }
    )

    assert "functions_state_id" not in chat["messages"][1]
    assert chat["messages"][2]["functions_state_id"] == state_id
    Chat.model_validate(chat)


async def test_request_transformer_normalizes_nullable_tool_schema_for_legacy_chat():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger)
    data = {
        "model": "GigaChat-2-Max",
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "browser_action",
                    "description": "Perform browser actions",
                    "strict": True,
                    "parameters": _kilocode_nullable_parameters(),
                },
            }
        ],
        "messages": [{"role": "user", "content": "open a page"}],
    }

    chat = await rt.prepare_chat(data)

    Chat.model_validate(chat)
    properties = chat["functions"][0].parameters.model_dump(
        by_alias=True,
        exclude_none=True,
    )["properties"]
    for field_name in ("url", "coordinate", "size", "text", "path"):
        assert properties[field_name]["type"] == "string"


async def test_request_transformer_normalizes_uppercase_tool_schema_for_legacy_chat():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger)
    data = {
        "model": "GigaChat-2-Max",
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "city": {"type": "STRING"},
                            "include_forecast": {"type": "BOOLEAN"},
                            "daily_highs": {
                                "type": "ARRAY",
                                "items": {"type": "NUMBER"},
                            },
                        },
                        "required": ["city"],
                    },
                },
            }
        ],
        "messages": [{"role": "user", "content": "weather"}],
    }

    chat = await rt.prepare_chat(data)

    Chat.model_validate(chat)
    params = chat["functions"][0].parameters.model_dump(
        by_alias=True,
        exclude_none=True,
    )
    assert params["type"] == "object"
    assert params["properties"]["city"]["type"] == "string"
    assert params["properties"]["include_forecast"]["type"] == "boolean"
    assert params["properties"]["daily_highs"]["type"] == "array"
    assert params["properties"]["daily_highs"]["items"]["type"] == "number"


async def test_request_transformer_normalizes_nullable_legacy_functions():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger)
    data = {
        "model": "GigaChat-2-Max",
        "functions": [
            {
                "name": "browser_action",
                "description": "Perform browser actions",
                "parameters": _kilocode_nullable_parameters(),
            }
        ],
        "messages": [{"role": "user", "content": "open a page"}],
    }

    chat = await rt.prepare_chat(data)

    Chat.model_validate(chat)
    properties = chat["functions"][0].parameters.model_dump(
        by_alias=True,
        exclude_none=True,
    )["properties"]
    for field_name in ("url", "coordinate", "size", "text", "path"):
        assert properties[field_name]["type"] == "string"


async def test_prepare_chat_normalizes_raw_function_schemas():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger)

    chat = await rt.prepare_chat(
        {
            "model": "GigaChat-2-Max",
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "final_answer",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "answers": {"type": "object"},
                                "score": {
                                    "anyOf": [
                                        {"type": "integer"},
                                        {"type": "number"},
                                        {"type": "null"},
                                    ]
                                },
                                "meta": {"type": ["object", "null"]},
                            },
                        },
                    },
                }
            ],
            "messages": [{"role": "user", "content": "hi"}],
        }
    )

    params = chat["functions"][0].parameters.model_dump(
        by_alias=True,
        exclude_none=True,
    )
    assert params["properties"]["answers"]["type"] == "object"
    assert params["properties"]["answers"]["properties"] == {}
    assert params["properties"]["score"]["type"] == "integer"
    assert "anyOf" not in params["properties"]["score"]
    assert params["properties"]["meta"]["type"] == "object"
    assert params["properties"]["meta"]["properties"] == {}


async def test_request_transformer_dev_debug_logging_includes_full_payload():
    mock_logger = MagicMock()
    mock_bound_logger = MagicMock()
    mock_logger.bind.return_value = mock_bound_logger
    cfg = ProxyConfig(proxy=ProxySettings(mode="DEV"))
    rt = RequestTransformer(cfg, mock_logger)

    await rt.prepare_chat(
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
    assert json.loads(out["metadata"]["gigachat_called_tools"]) == [
        {
            "index": 0,
            "choice_index": 0,
            "name": "write_file",
            "arguments": {"file_path": "/app/regex.txt"},
            "role": "assistant",
            "tools_state_id": "019e94aa-de11-705c-998b-040af4d06462",
        }
    ]


def test_response_processor_chat_metadata_includes_input_tool_calls():
    rp = ResponseProcessor(logger)
    giga_resp = MockResponse(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Aquarius: stars are aligned.",
                    },
                    "finish_reason": "stop",
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
            "messages": [
                {"role": "user", "content": "What is my horoscope?"},
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "019e97ee-44ad-711e-bee2-9bd35832e31f",
                            "type": "function",
                            "function": {
                                "name": "get_horoscope",
                                "arguments": '{"sign":"Aquarius"}',
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "019e97ee-44ad-711e-bee2-9bd35832e31f",
                    "content": '{"horoscope":"Aquarius: stars are aligned."}',
                },
            ]
        },
    )

    assert json.loads(out["metadata"]["gigachat_called_tools"]) == [
        {
            "index": 0,
            "message_index": 1,
            "name": "get_horoscope",
            "arguments": {"sign": "Aquarius"},
            "tool_call_index": 0,
            "role": "assistant",
            "call_id": "019e97ee-44ad-711e-bee2-9bd35832e31f",
            "tools_state_id": "019e97ee-44ad-711e-bee2-9bd35832e31f",
        }
    ]


def test_response_processor_chat_metadata_includes_chat_completion_content_function_calls():
    rp = ResponseProcessor(logger)
    giga_resp = MockResponse(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Done.",
                    },
                    "finish_reason": "stop",
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
            "messages": [
                {
                    "role": "assistant",
                    "tools_state_id": "state-1",
                    "content": [
                        {
                            "function_call": {
                                "name": "run_shell_command",
                                "arguments": {"command": "make install"},
                            }
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tools_state_id": "state-1",
                    "content": [
                        {
                            "function_result": {
                                "name": "run_shell_command",
                                "result": {"result": "ok"},
                            }
                        }
                    ],
                },
            ]
        },
    )

    assert json.loads(out["metadata"]["gigachat_called_tools"]) == [
        {
            "index": 0,
            "message_index": 0,
            "name": "run_shell_command",
            "arguments": {"command": "make install"},
            "content_index": 0,
            "role": "assistant",
            "tools_state_id": "state-1",
        }
    ]


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
    assert json.loads(out["metadata"]["gigachat_called_tools"]) == [
        {
            "index": 0,
            "choice_index": 0,
            "name": "sum",
            "arguments": {"a": 1},
            "role": "assistant",
            "tools_state_id": "state-1",
        }
    ]


def test_response_processor_responses_tool_call_restores_namespace():
    rp = ResponseProcessor(logger, structured_output_mode="native")
    tools = [
        {
            "type": "namespace",
            "name": "mcp__playwright",
            "tools": [
                {
                    "type": "function",
                    "name": "browser_navigate",
                    "parameters": {
                        "type": "object",
                        "properties": {"url": {"type": "string"}},
                    },
                }
            ],
        }
    ]
    giga_resp = MockResponse(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "function_call": {
                            "name": "mcp__playwright__browser_navigate",
                            "arguments": {"url": "http://localhost:8090"},
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
        {"model": "gpt-x", "input": "open", "tools": tools},
        giga_resp,
        gpt_model="gpt-x",
        response_id="resp-1",
    )

    assert out["output"][0]["type"] == "function_call"
    assert out["output"][0]["name"] == "browser_navigate"
    assert out["output"][0]["namespace"] == "mcp__playwright"
    assert json.loads(out["metadata"]["gigachat_called_tools"]) == [
        {
            "index": 0,
            "choice_index": 0,
            "name": "browser_navigate",
            "namespace": "mcp__playwright",
            "arguments": {"url": "http://localhost:8090"},
            "role": "assistant",
            "tools_state_id": "state-1",
        }
    ]


def test_response_processor_responses_metadata_includes_input_called_tools():
    rp = ResponseProcessor(logger)
    giga_resp = MockResponse(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Aquarius: stars are aligned.",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )

    out = rp.process_response_api(
        {
            "input": [
                {"role": "user", "content": "What is my horoscope?"},
                {
                    "type": "function_call",
                    "id": "fc_state-1",
                    "call_id": "state-1",
                    "name": "sum",
                    "arguments": '{"a":1}',
                    "status": "completed",
                },
                {
                    "type": "function_call_output",
                    "call_id": "state-1",
                    "output": '{"result":1}',
                },
            ]
        },
        giga_resp,
        gpt_model="gpt-x",
        response_id="resp-1",
    )

    assert json.loads(out["metadata"]["gigachat_called_tools"]) == [
        {
            "index": 0,
            "input_index": 1,
            "name": "sum",
            "arguments": {"a": 1},
            "call_id": "state-1",
            "tools_state_id": "state-1",
            "id": "fc_state-1",
            "status": "completed",
        }
    ]


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
