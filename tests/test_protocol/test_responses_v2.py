import pytest
from fastapi import HTTPException
from loguru import logger

from gpt2giga.models.config import ProxyConfig
from gpt2giga.protocol import RequestTransformer, ResponseProcessor


@pytest.mark.asyncio
async def test_prepare_response_v2_maps_json_schema_tools_and_conversation():
    transformer = RequestTransformer(ProxyConfig(), logger)
    chat = await transformer.prepare_response_v2(
        {
            "model": "gpt-x",
            "input": "hello",
            "conversation": {"id": "thread-1"},
            "text": {
                "format": {
                    "type": "json_schema",
                    "json_schema": {
                        "schema": {
                            "type": "object",
                            "properties": {"city": {"type": "string"}},
                        }
                    },
                }
            },
            "reasoning": {"effort": "medium", "summary": "auto"},
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
                },
                {"type": "web_search"},
                {"type": "code_interpreter"},
                {"type": "image_generation"},
                {"type": "file_search", "vector_store_ids": ["vs_1"]},
            ],
            "temperature": 0.7,
            "top_p": 0.9,
            "max_output_tokens": 128,
            "top_logprobs": 2,
        }
    )

    payload = chat.model_dump(exclude_none=True, by_alias=True)
    assert payload["storage"]["thread_id"] == "thread-1"
    assert payload["model_options"]["response_format"]["type"] == "json_schema"
    assert payload["model_options"]["reasoning"]["effort"] == "medium"
    assert payload["model_options"]["temperature"] == 0.7
    assert payload["model_options"]["top_p"] == 0.9
    assert payload["model_options"]["max_tokens"] == 128
    assert payload["model_options"]["top_logprobs"] == 2
    assert payload["tools"][0]["functions"]["specifications"][0]["name"] == "sum"
    assert payload["tools"][1] == {"web_search": {}}
    assert payload["tools"][2] == {"code_interpreter": {}}
    assert payload["tools"][3] == {"image_generate": {}}


@pytest.mark.asyncio
async def test_prepare_response_v2_maps_multimodal_and_replayed_tool_items():
    transformer = RequestTransformer(ProxyConfig(), logger)
    chat = await transformer.prepare_response_v2(
        {
            "model": "gpt-x",
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "hello"},
                        {"type": "input_file", "file_id": "file-1"},
                        {"type": "input_image", "file_id": "img-1"},
                    ],
                },
                {
                    "type": "function_call",
                    "name": "sum",
                    "arguments": '{"a": 1}',
                    "call_id": "call-1",
                },
                {
                    "type": "function_call_output",
                    "name": "sum",
                    "output": '{"ok": true}',
                    "call_id": "call-1",
                },
                {
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "done"}],
                    "tool_calls": [
                        {
                            "id": "call-2",
                            "function": {
                                "name": "web_search",
                                "arguments": '{"query": "hi"}',
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "name": "web_search",
                    "content": '{"result": "ok"}',
                    "tool_call_id": "call-2",
                },
            ],
        }
    )

    messages = chat.model_dump(exclude_none=True, by_alias=True)["messages"]
    assert messages[0]["content"][0] == {
        "text": "hello",
        "files": [{"id": "file-1"}, {"id": "img-1"}],
    }
    assert len(messages) == 5
    assert messages[1]["role"] == "assistant"
    assert messages[1]["tools_state_id"] == "call-1"
    assert messages[1]["content"][0]["function_call"]["name"] == "sum"
    assert messages[2]["role"] == "tool"
    assert messages[2]["tools_state_id"] == "call-1"
    assert messages[2]["content"][0]["function_result"]["name"] == "sum"
    assert messages[3]["role"] == "assistant"
    assert messages[3]["tools_state_id"] == "call-2"
    assert messages[3]["content"][0] == {"text": "done"}
    assert (
        messages[3]["content"][1]["function_call"]["name"]
        == "__gpt2giga_user_search_web"
    )
    assert messages[4]["role"] == "tool"
    assert messages[4]["tools_state_id"] == "call-2"
    assert (
        messages[4]["content"][0]["function_result"]["name"]
        == "__gpt2giga_user_search_web"
    )


@pytest.mark.asyncio
async def test_prepare_response_v2_repairs_dangling_assistant_function_call():
    transformer = RequestTransformer(ProxyConfig(), logger)
    chat = await transformer.prepare_response_v2(
        {
            "model": "gpt-x",
            "input": [
                {
                    "role": "assistant",
                    "content": "",
                    "function_call": {
                        "name": "run_shell_command",
                        "arguments": '{"command": "pwd"}',
                    },
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "System: Potential loop detected. Please continue.",
                        }
                    ],
                },
            ],
        }
    )

    messages = chat.model_dump(exclude_none=True, by_alias=True)["messages"]
    function_call_part = next(
        part["function_call"]
        for part in messages[0]["content"]
        if "function_call" in part
    )
    assert len(messages) == 3
    assert messages[0]["role"] == "assistant"
    assert function_call_part["name"] == "run_shell_command"
    assert messages[1]["role"] == "tool"
    assert messages[1]["content"][0]["function_result"]["name"] == "run_shell_command"
    assert messages[1]["content"][0]["function_result"]["result"]["status"] == (
        "interrupted"
    )
    assert messages[2]["role"] == "user"
    assert messages[2]["content"][0]["text"] == (
        "System: Potential loop detected. Please continue."
    )


@pytest.mark.asyncio
async def test_prepare_response_v2_wraps_plain_tool_outputs_in_json_object():
    transformer = RequestTransformer(ProxyConfig(), logger)
    chat = await transformer.prepare_response_v2(
        {
            "model": "gpt-x",
            "input": [
                {
                    "type": "function_call",
                    "name": "exec_command",
                    "arguments": '{"cmd": "pwd"}',
                    "call_id": "call-1",
                },
                {
                    "type": "function_call_output",
                    "name": "exec_command",
                    "output": "Command output",
                    "call_id": "call-1",
                },
                {
                    "role": "tool",
                    "name": "exec_command",
                    "content": "More output",
                    "tool_call_id": "call-2",
                },
            ],
        }
    )

    messages = chat.model_dump(exclude_none=True, by_alias=True)["messages"]
    assert messages[1]["content"][0]["function_result"]["result"] == {
        "output": "Command output"
    }
    assert messages[2]["content"][0]["function_result"]["result"] == {
        "output": "More output"
    }


@pytest.mark.asyncio
async def test_prepare_response_v2_resolves_previous_response_id():
    transformer = RequestTransformer(ProxyConfig(), logger)
    chat = await transformer.prepare_response_v2(
        {
            "model": "gpt-x",
            "input": "hello",
            "previous_response_id": "resp_prev",
        },
        response_store={"resp_prev": {"thread_id": "thread-9"}},
    )

    payload = chat.model_dump(exclude_none=True, by_alias=True)
    assert payload["storage"]["thread_id"] == "thread-9"


@pytest.mark.asyncio
async def test_prepare_response_v2_omits_storage_without_thread():
    transformer = RequestTransformer(ProxyConfig(), logger)
    chat = await transformer.prepare_response_v2(
        {
            "model": "gpt-x",
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "what's in this image?"},
                        {"type": "input_image", "file_id": "img-1"},
                    ],
                }
            ],
            "store": False,
        }
    )

    payload = chat.model_dump(exclude_none=True, by_alias=True)
    assert "storage" not in payload
    assert payload["messages"][0]["content"] == [
        {"text": "what's in this image?", "files": [{"id": "img-1"}]}
    ]


@pytest.mark.asyncio
async def test_prepare_response_v2_rejects_forced_unsupported_tool_choice():
    transformer = RequestTransformer(ProxyConfig(), logger)
    with pytest.raises(HTTPException) as exc_info:
        await transformer.prepare_response_v2(
            {
                "model": "gpt-x",
                "input": "hello",
                "tool_choice": {"type": "file_search"},
            }
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"]["type"] == "invalid_request_error"


@pytest.mark.asyncio
async def test_prepare_response_v2_rejects_conversation_and_previous_response_id():
    transformer = RequestTransformer(ProxyConfig(), logger)
    with pytest.raises(HTTPException) as exc_info:
        await transformer.prepare_response_v2(
            {
                "model": "gpt-x",
                "input": "hello",
                "conversation": {"id": "thread-1"},
                "previous_response_id": "resp_prev",
            },
            response_store={"resp_prev": {"thread_id": "thread-9"}},
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"]["param"] == "conversation"


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self, *args, **kwargs):
        return self.data


def test_response_processor_process_response_api_v2_maps_text_and_fields():
    processor = ResponseProcessor(logger)
    response_store = {}
    out = processor.process_response_api_v2(
        {
            "model": "gpt-x",
            "input": "Capital of France",
            "reasoning": {"effort": "high", "summary": "auto"},
            "top_logprobs": 2,
        },
        MockResponse(
            {
                "model": "gpt-x",
                "thread_id": "thread-1",
                "created_at": 123,
                "messages": [
                    {
                        "message_id": "msg-1",
                        "role": "assistant",
                        "content": [{"text": "Paris"}],
                    }
                ],
                "finish_reason": "stop",
                "usage": {
                    "input_tokens": 1,
                    "input_tokens_details": {"cached_tokens": 1},
                    "output_tokens": 2,
                    "total_tokens": 3,
                },
            }
        ),
        gpt_model="gpt-x",
        response_id="v2-1",
        response_store=response_store,
    )

    assert out["conversation"] == {"id": "thread-1"}
    assert out["completed_at"] is not None
    assert out["reasoning"] == {"effort": "high", "summary": "auto"}
    assert out["usage"]["input_tokens"] == 1
    assert out["usage"]["input_tokens_details"]["cached_tokens"] == 1
    assert out["output"][0]["type"] == "message"
    assert out["output"][0]["content"][0]["text"] == "Paris"
    assert "store" not in out
    assert response_store[out["id"]]["thread_id"] == "thread-1"


def test_response_processor_process_response_api_v2_maps_function_and_builtin_tool():
    processor = ResponseProcessor(logger)
    out = processor.process_response_api_v2(
        {"model": "gpt-x", "input": "hello"},
        MockResponse(
            {
                "model": "gpt-x",
                "thread_id": "thread-2",
                "created_at": 123,
                "messages": [
                    {
                        "message_id": "msg-1",
                        "role": "assistant",
                        "tools_state_id": "state-1",
                        "content": [
                            {
                                "function_call": {
                                    "name": "sum",
                                    "arguments": {"a": 1},
                                }
                            },
                            {
                                "tool_execution": {
                                    "name": "web_search",
                                    "status": "completed",
                                }
                            },
                        ],
                    }
                ],
                "finish_reason": "stop",
                "usage": {
                    "input_tokens": 1,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens": 2,
                    "total_tokens": 3,
                },
                "additional_data": {"execution_steps": [{"query": "weather"}]},
            }
        ),
        gpt_model="gpt-x",
        response_id="v2-2",
    )

    assert out["output"][0]["type"] == "function_call"
    assert out["output"][0]["name"] == "sum"
    assert out["output"][1]["type"] == "web_search_call"
    assert out["output"][1]["status"] == "completed"
    assert out["output"][1]["action"]["query"] == "weather"


def test_response_processor_process_response_api_v2_marks_incomplete():
    processor = ResponseProcessor(logger)
    out = processor.process_response_api_v2(
        {"model": "gpt-x", "input": "hello"},
        MockResponse(
            {
                "model": "gpt-x",
                "thread_id": "thread-3",
                "created_at": 123,
                "messages": [],
                "finish_reason": "length",
                "usage": {
                    "input_tokens": 1,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens": 2,
                    "total_tokens": 3,
                },
            }
        ),
        gpt_model="gpt-x",
        response_id="v2-3",
    )

    assert out["status"] == "incomplete"
    assert out["incomplete_details"] == {"reason": "max_output_tokens"}
