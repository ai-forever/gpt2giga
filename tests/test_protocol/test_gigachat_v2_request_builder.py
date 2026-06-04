from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from gigachat.models import ChatCompletionRequest
from loguru import logger

from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import RequestTransformer


@pytest.mark.asyncio
async def test_prepare_chat_completion_v2_builds_primary_request():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion_v2(
        {
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "hello"}],
            "max_completion_tokens": 64,
            "temperature": 0.4,
            "top_p": 0.8,
            "stream": True,
        }
    )

    assert isinstance(request, ChatCompletionRequest)
    assert request.model == "GigaChat-2-Max"
    assert request.stream is True
    assert request.messages[0].role == "user"
    assert request.messages[0].content[0].text == "hello"
    assert request.model_options.max_tokens == 64
    assert request.model_options.temperature == 0.4
    assert request.model_options.top_p == 0.8


@pytest.mark.asyncio
async def test_prepare_chat_completion_v2_maps_tools_and_forced_function_call():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion_v2(
        {
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "search"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "web_search",
                        "description": "Search the web",
                        "parameters": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                        },
                    },
                }
            ],
            "tool_choice": {
                "type": "function",
                "function": {"name": "web_search"},
            },
        }
    )

    spec = request.tools[0].functions.specifications[0]
    assert spec.name == "__gpt2giga_user_search_web"
    assert spec.description == "Search the web"
    assert spec.parameters["properties"]["query"]["type"] == "string"
    assert request.tool_config.mode == "function"
    assert request.tool_config.function_name == "__gpt2giga_user_search_web"


@pytest.mark.asyncio
async def test_prepare_chat_completion_v2_maps_native_structured_output_and_reasoning():
    cfg = ProxyConfig(
        proxy=ProxySettings(
            enable_reasoning=True,
            structured_output_mode="native",
        )
    )
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion_v2(
        {
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "return json"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "Output",
                    "schema": {"type": "object"},
                    "strict": True,
                },
            },
        }
    )

    assert request.model_options.reasoning.effort == "high"
    assert request.model_options.response_format.type == "json_schema"
    assert request.model_options.response_format.schema_ == {"type": "object"}
    assert request.model_options.response_format.strict is True
    assert request.tools is None


@pytest.mark.asyncio
async def test_prepare_chat_completion_v2_respects_pass_model_false():
    cfg = ProxyConfig(proxy=ProxySettings(pass_model=False))
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion_v2(
        {
            "model": "openai-model",
            "messages": [{"role": "user", "content": "hello"}],
        }
    )

    assert request.model is None


@pytest.mark.asyncio
async def test_prepare_chat_completion_v2_prod_logging_omits_payload():
    mock_logger = MagicMock()
    mock_bound_logger = MagicMock()
    mock_logger.bind.return_value = mock_bound_logger
    cfg = ProxyConfig(proxy=ProxySettings(mode="PROD"))
    rt = RequestTransformer(cfg, logger=mock_logger)

    await rt.prepare_chat_completion_v2(
        {
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "secret payload"}],
        }
    )

    mock_bound_logger.debug.assert_called_with(
        "Sending v2 request to GigaChat API (payload omitted in PROD)"
    )


@pytest.mark.asyncio
async def test_prepare_response_v2_builds_primary_request_from_responses_input():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_response_v2(
        {
            "model": "GigaChat-2-Max",
            "instructions": "be concise",
            "input": "hello",
            "max_output_tokens": 32,
        }
    )

    assert request.model == "GigaChat-2-Max"
    assert [message.role for message in request.messages] == ["system", "user"]
    assert request.messages[0].content[0].text == "be concise"
    assert request.messages[1].content[0].text == "hello"
    assert request.model_options.max_tokens == 32
    assert request.storage.model_dump(exclude_none=True) == {}


@pytest.mark.asyncio
async def test_prepare_response_v2_omits_storage_when_store_false():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_response_v2(
        {
            "model": "GigaChat-2-Max",
            "input": "hello",
            "store": False,
        }
    )

    assert request.storage is None
    assert "storage" not in request.model_dump(exclude_none=True)


@pytest.mark.asyncio
async def test_prepare_response_v2_maps_previous_response_id_to_storage_thread_id():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_response_v2(
        {
            "model": "GigaChat-2-Max",
            "input": "hello",
            "previous_response_id": "resp_thread_1",
        }
    )

    assert request.model is None
    assert request.storage.thread_id == "thread_1"
    assert request.model_dump(exclude_none=True)["storage"] == {"thread_id": "thread_1"}
    assert "model" not in request.model_dump(exclude_none=True)


@pytest.mark.asyncio
async def test_prepare_response_v2_maps_function_call_output():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_response_v2(
        {
            "model": "GigaChat-2-Max",
            "input": [
                {"type": "function_call", "name": "sum", "arguments": '{"a": 1}'},
                {
                    "type": "function_call_output",
                    "name": "sum",
                    "output": {"result": 2},
                },
            ],
        }
    )

    assert request.messages[0].role == "assistant"
    assert request.messages[0].function_call is None
    function_call = request.messages[0].content[0].function_call
    assert function_call.name == "sum"
    assert function_call.arguments == {"a": 1}
    assert request.messages[1].role == "tool"
    result = request.messages[1].content[0].function_result
    assert result.name == "sum"
    assert result.result == {"result": 2}


@pytest.mark.asyncio
async def test_prepare_response_v2_replays_function_call_with_tools_state_id():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    tool = {
        "type": "function",
        "name": "get_horoscope",
        "description": "Get today's horoscope for an astrological sign.",
        "parameters": {
            "type": "object",
            "properties": {"sign": {"type": "string"}},
            "required": ["sign"],
        },
    }

    request = await rt.prepare_response_v2(
        {
            "model": "GigaChat-3-Ultra",
            "instructions": "Respond only with a horoscope generated by a tool.",
            "tools": [tool] * 20,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "What is my horoscope? I am an Aquarius.",
                        }
                    ],
                },
                {
                    "type": "function_call",
                    "id": "fc_019e9355-4241-76b8-909f-8e6782952b5f",
                    "call_id": "call_response_1",
                    "name": "get_horoscope",
                    "arguments": '{"sign": "Aquarius"}',
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_response_1",
                    "output": '{"horoscope": '
                    '"Aquarius: Next Tuesday you will befriend a baby otter."}',
                },
            ],
        }
    )

    assert [message.role for message in request.messages] == [
        "system",
        "user",
        "assistant",
        "tool",
    ]
    assert request.messages[2].tools_state_id == (
        "019e9355-4241-76b8-909f-8e6782952b5f"
    )
    assert request.messages[2].content[0].function_call.name == "get_horoscope"
    assert request.messages[2].content[0].function_call.arguments == {
        "sign": "Aquarius"
    }
    assert request.messages[3].tools_state_id == (
        "019e9355-4241-76b8-909f-8e6782952b5f"
    )
    result = request.messages[3].content[0].function_result
    assert result.name == "get_horoscope"
    assert result.result == {
        "horoscope": "Aquarius: Next Tuesday you will befriend a baby otter."
    }
    assert len(request.tools[0].functions.specifications) == 1
    assert request.storage.model_dump(exclude_none=True) == {}


@pytest.mark.asyncio
async def test_prepare_response_v2_maps_responses_builtin_tools():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_response_v2(
        {
            "model": "GigaChat-2-Max",
            "input": "Find current sources and then calculate a summary.",
            "tools": [
                {
                    "type": "web_search_preview",
                    "indexes": ["web"],
                    "flags": ["trusted"],
                },
                {
                    "type": "code_interpreter",
                    "container": {"type": "auto"},
                },
                {
                    "type": "image_generation",
                    "size": "1024x1024",
                },
                {
                    "type": "function",
                    "function": {
                        "name": "save_result",
                        "parameters": {
                            "type": "object",
                            "properties": {"value": {"type": "string"}},
                        },
                    },
                },
            ],
            "tool_choice": {"type": "web_search_preview"},
        }
    )

    assert request.tools[0].web_search.indexes == ["web"]
    assert request.tools[0].web_search.flags == ["trusted"]
    assert request.tools[1].code_interpreter == {"container": {"type": "auto"}}
    assert request.tools[2].image_generate == {"size": "1024x1024"}
    spec = request.tools[3].functions.specifications[0]
    assert spec.name == "save_result"
    assert spec.parameters["properties"]["value"]["type"] == "string"
    assert request.tool_config.mode == "tool"
    assert request.tool_config.tool_name == "web_search"


@pytest.mark.asyncio
async def test_prepare_chat_completion_v2_maps_additional_fields():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion_v2(
        {
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "hello"}],
            "extra_body": {
                "flags": ["beta"],
                "repetition_penalty": 1.2,
                "custom_flag": "on",
            },
        }
    )

    assert request.flags == ["beta"]
    assert request.model_options.repetition_penalty == 1.2
    assert request.model_extra["custom_flag"] == "on"


@pytest.mark.asyncio
async def test_prepare_chat_completion_v2_reuses_attachment_uploads():
    class AttachmentProcessor:
        async def upload_file_with_meta(self, *_args, **_kwargs):
            return SimpleNamespace(
                file_id="file_1",
                file_kind="image",
                file_size_bytes=1,
            )

    cfg = ProxyConfig()
    cfg.proxy_settings.enable_images = True
    rt = RequestTransformer(
        cfg,
        logger=logger,
        attachment_processor=AttachmentProcessor(),
    )

    request = await rt.prepare_chat_completion_v2(
        {
            "model": "GigaChat-2-Max",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "look"},
                        {"type": "image_url", "image_url": {"url": "data:image/png"}},
                    ],
                }
            ],
        },
        giga_client=object(),
    )

    content = request.messages[0].content
    assert content[0].text == "look"
    assert content[1].files[0].id_ == "file_1"


@pytest.mark.asyncio
async def test_prepare_chat_completion_v2_maps_tool_call_result_history():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion_v2(
        {
            "model": "GigaChat-2-Max",
            "messages": [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_019e94aa-de11-705c-998b-040af4d06462",
                            "type": "function",
                            "function": {
                                "name": "write_file",
                                "arguments": '{"file_path": "/app/regex.txt"}',
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call_019e94aa-de11-705c-998b-040af4d06462",
                    "content": {
                        "output": [
                            {
                                "type": "text",
                                "text": "Successfully wrote /app/regex.txt.",
                            }
                        ]
                    },
                },
            ],
        }
    )

    assert [message.role for message in request.messages] == ["assistant", "tool"]
    assert request.messages[0].tools_state_id == (
        "019e94aa-de11-705c-998b-040af4d06462"
    )
    function_call = request.messages[0].content[0].function_call
    assert function_call.name == "write_file"
    assert function_call.arguments == {"file_path": "/app/regex.txt"}

    assert request.messages[1].tools_state_id == (
        "019e94aa-de11-705c-998b-040af4d06462"
    )
    function_result = request.messages[1].content[0].function_result
    assert function_result.name == "write_file"
    assert function_result.result == {
        "output": [
            {
                "type": "text",
                "text": "Successfully wrote /app/regex.txt.",
            }
        ]
    }


@pytest.mark.asyncio
async def test_prepare_chat_completion_v2_repairs_legacy_empty_tool_result():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion_v2(
        {
            "model": "GigaChat-2-Max",
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "function_call": {
                                "name": "run_shell_command",
                                "arguments": {
                                    "command": "qemu-system-x86_64 -cdrom alpine.iso"
                                },
                            }
                        }
                    ],
                },
                {"role": "tool"},
            ],
        }
    )

    assert len(request.messages) == 2
    assert request.messages[0].role == "assistant"
    assert request.messages[0].content[0].function_call.name == "run_shell_command"
    assert request.messages[1].role == "tool"
    function_result = request.messages[1].content[0].function_result
    assert function_result.name == "run_shell_command"
    assert function_result.result == {}
