from types import SimpleNamespace
from unittest.mock import MagicMock

from gigachat.models import ChatCompletionRequest
from loguru import logger

from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import RequestTransformer
from gpt2giga.protocol.anthropic.request import (
    _build_openai_data_from_anthropic_request,
)
from gpt2giga.protocols.gemini.adapter import GeminiProtocolAdapter
from gpt2giga.providers.gigachat.adapter import normalized_chat_to_openai_payload


async def test_prepare_chat_completion_builds_chat_completion_request():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion(
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


async def test_prepare_chat_completion_maps_tools_and_forced_function_call():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion(
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


async def test_prepare_chat_completion_normalizes_uppercase_gemini_tool_schema():
    cfg = ProxyConfig(proxy=ProxySettings(gigachat_api_mode="v2"))
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion(
        {
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "weather"}],
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
        }
    )

    assert isinstance(request, ChatCompletionRequest)
    spec = request.tools[0].functions.specifications[0]
    assert spec.parameters["type"] == "object"
    assert spec.parameters["properties"]["city"]["type"] == "string"
    assert spec.parameters["properties"]["include_forecast"]["type"] == "boolean"
    assert spec.parameters["properties"]["daily_highs"]["type"] == "array"
    assert spec.parameters["properties"]["daily_highs"]["items"]["type"] == "number"


async def test_prepare_chat_completion_adds_properties_to_empty_tool_schema():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion(
        {
            "model": "GigaChat-3-Ultra",
            "messages": [{"role": "user", "content": "hello"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "update_topic",
                        "description": "Update progress.",
                        "parameters": {},
                    },
                }
            ],
        }
    )

    spec = request.tools[0].functions.specifications[0]
    assert spec.parameters == {"type": "object", "properties": {}}


async def test_prepare_chat_completion_normalizes_anthropic_nested_tool_schema():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    openai_data = _build_openai_data_from_anthropic_request(
        {
            "model": "claude-x",
            "messages": [{"role": "user", "content": "inspect"}],
            "tools": [
                {
                    "name": "read_result",
                    "description": "Read a tool result.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "format": "uri",
                                "description": "Target URL.",
                            },
                            "annotations": {
                                "type": "object",
                                "description": "Optional annotations.",
                            },
                        },
                    },
                }
            ],
        },
        logger,
    )

    request = await rt.prepare_chat_completion(openai_data)

    spec = request.tools[0].functions.specifications[0]
    url = spec.parameters["properties"]["url"]
    annotations = spec.parameters["properties"]["annotations"]
    assert url["type"] == "string"
    assert "format" not in url
    assert annotations["type"] == "object"
    assert annotations["properties"] == {}


async def test_prepare_chat_completion_defaults_untyped_array_items():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion(
        {
            "model": "giga",
            "messages": [{"role": "user", "content": "select"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "select_subject",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "excludedBodyParts": {
                                    "type": "array",
                                    "items": {},
                                },
                            },
                        },
                    },
                }
            ],
        }
    )

    spec = request.tools[0].functions.specifications[0]
    excluded_body_parts = spec.parameters["properties"]["excludedBodyParts"]
    assert excluded_body_parts["items"]["type"] == "string"


async def test_prepare_chat_completion_defaults_untyped_tool_properties():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion(
        {
            "model": "giga",
            "messages": [{"role": "user", "content": "run workflow"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "Workflow",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "args": {
                                    "description": (
                                        "Optional input value exposed to the script "
                                        "as the global args, verbatim."
                                    ),
                                },
                                "scriptPath": {
                                    "description": "Path to a workflow script file.",
                                    "type": "string",
                                },
                            },
                        },
                    },
                }
            ],
        }
    )

    spec = request.tools[0].functions.specifications[0]
    args = spec.parameters["properties"]["args"]
    assert args["type"] == "object"
    assert args["properties"] == {}


async def test_prepare_chat_completion_maps_builtin_tools_in_v2_mode():
    cfg = ProxyConfig(proxy=ProxySettings(gigachat_api_mode="v2"))
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion(
        {
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "search"}],
            "tools": [
                {
                    "type": "web_search_preview",
                    "indexes": ["web"],
                    "flags": ["trusted"],
                }
            ],
            "tool_choice": {"type": "web_search_preview"},
        }
    )

    assert request.tools[0].web_search.indexes == ["web"]
    assert request.tools[0].web_search.flags == ["trusted"]
    assert request.tool_config.mode == "tool"
    assert request.tool_config.tool_name == "web_search"


async def test_prepare_chat_completion_ignores_builtin_tools_when_mapping_disabled():
    cfg = ProxyConfig(
        proxy=ProxySettings(
            gigachat_api_mode="v2",
            disable_builtin_tool_mapping=True,
        )
    )
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion(
        {
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "search"}],
            "tools": [
                {
                    "type": "web_search_preview",
                    "indexes": ["web"],
                    "flags": ["trusted"],
                }
            ],
            "tool_choice": {"type": "web_search_preview"},
        }
    )

    payload = request.model_dump(exclude_none=True)
    assert "tools" not in payload
    assert "tool_config" not in payload


async def test_prepare_chat_completion_maps_anthropic_builtin_tool_types():
    cfg = ProxyConfig(proxy=ProxySettings(gigachat_api_mode="v2"))
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion(
        {
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "search and fetch"}],
            "tools": [
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": 5,
                    "allowed_domains": ["example.com"],
                    "indexes": ["web"],
                },
                {
                    "type": "web_fetch_20250910",
                    "name": "web_fetch",
                    "max_uses": 2,
                },
                {
                    "type": "code_execution_20250825",
                    "name": "code_execution",
                },
            ],
            "tool_choice": {"type": "web_search"},
        }
    )

    assert request.tools[0].web_search.model_dump(exclude_none=True) == {
        "indexes": ["web"],
        "max_uses": 5,
        "allowed_domains": ["example.com"],
    }
    assert request.tools[1].url_content_extraction == {"max_uses": 2}
    assert request.tools[2].code_interpreter == {}
    assert request.tool_config.mode == "tool"
    assert request.tool_config.tool_name == "web_search"


async def test_prepare_chat_completion_maps_gemini_builtin_tool_types():
    cfg = ProxyConfig(proxy=ProxySettings(gigachat_api_mode="v2"))
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion(
        {
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "search, read, calculate"}],
            "tools": [
                {
                    "type": "googleSearch",
                    "googleSearch": {"indexes": ["web"]},
                },
                {
                    "type": "urlContext",
                    "urlContext": {"max_uses": 2},
                },
                {"type": "codeExecution"},
            ],
            "tool_choice": {"type": "googleSearch"},
        }
    )

    assert request.tools[0].web_search.indexes == ["web"]
    assert request.tools[1].url_content_extraction == {"max_uses": 2}
    assert request.tools[2].code_interpreter == {}
    assert request.tool_config.mode == "tool"
    assert request.tool_config.tool_name == "web_search"


async def test_prepare_chat_completion_enables_builtin_tools_when_default_mode_is_v1():
    cfg = ProxyConfig(proxy=ProxySettings(gigachat_api_mode="v1"))
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion(
        {
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "search"}],
            "tools": [{"type": "web_search_preview"}],
            "tool_choice": {"type": "web_search_preview"},
        }
    )

    assert request.tools[0].web_search is not None
    assert request.tool_config.tool_name == "web_search"


async def test_prepare_chat_disables_builtin_tools_when_default_mode_is_v2():
    cfg = ProxyConfig(proxy=ProxySettings(gigachat_api_mode="v2"))
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat(
        {
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "search"}],
            "tools": [{"type": "web_search_preview"}],
            "tool_choice": {"type": "web_search_preview"},
        }
    )

    assert "_gpt2giga_builtin_tools" not in request
    assert "tools" not in request


async def test_prepare_chat_completion_maps_native_structured_output_and_reasoning():
    cfg = ProxyConfig(
        proxy=ProxySettings(
            enable_reasoning=True,
            structured_output_mode="native",
        )
    )
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion(
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
    assert request.model_options.response_format.schema_ == {
        "type": "object",
        "properties": {},
    }
    assert request.model_options.response_format.strict is True
    assert request.tools is None


async def test_prepare_chat_completion_disable_reasoning_omits_model_option():
    cfg = ProxyConfig(
        proxy=ProxySettings(
            enable_reasoning=True,
            disable_reasoning=True,
        )
    )
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion(
        {
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "hello"}],
            "reasoning_effort": "high",
        }
    )

    assert request.model_options is None
    assert "reasoning" not in request.model_dump(exclude_none=True)


async def test_prepare_chat_completion_respects_pass_model_false():
    cfg = ProxyConfig(proxy=ProxySettings(pass_model=False))
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion(
        {
            "model": "openai-model",
            "messages": [{"role": "user", "content": "hello"}],
        }
    )

    assert request.model is None


async def test_prepare_chat_completion_prod_logging_omits_payload():
    mock_logger = MagicMock()
    mock_bound_logger = MagicMock()
    mock_logger.bind.return_value = mock_bound_logger
    cfg = ProxyConfig(proxy=ProxySettings(mode="PROD"))
    rt = RequestTransformer(cfg, logger=mock_logger)

    await rt.prepare_chat_completion(
        {
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "secret payload"}],
        }
    )

    mock_bound_logger.debug.assert_called_with(
        "Sending chat completion request to GigaChat API (payload omitted in PROD)"
    )


async def test_prepare_chat_completion_dev_logging_includes_full_payload():
    mock_logger = MagicMock()
    mock_bound_logger = MagicMock()
    mock_logger.bind.return_value = mock_bound_logger
    cfg = ProxyConfig(proxy=ProxySettings(mode="DEV"))
    rt = RequestTransformer(cfg, logger=mock_logger)

    await rt.prepare_chat_completion(
        {
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "hello"}],
        }
    )

    bind_kwargs = mock_logger.bind.call_args.kwargs
    assert bind_kwargs["event"] == "gigachat_chat_completion_request"
    assert bind_kwargs["payload"]["model"] == "GigaChat-2-Max"
    assert bind_kwargs["payload"]["messages"][0]["content"][0]["text"] == "hello"
    mock_bound_logger.debug.assert_called_with(
        "Sending chat completion request to GigaChat API"
    )


async def test_prepare_response_chat_completion_builds_chat_completion_request_from_responses_input():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_response_chat_completion(
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
    assert request.storage is None
    assert "storage" not in request.model_dump(exclude_none=True)


async def test_prepare_response_chat_completion_sends_storage_when_store_true():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_response_chat_completion(
        {
            "model": "GigaChat-2-Max",
            "input": "hello",
            "store": True,
        }
    )

    assert request.storage.model_dump(exclude_none=True) == {}
    assert request.model_dump(exclude_none=True)["storage"] == {}


async def test_prepare_response_chat_completion_omits_storage_when_store_false():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_response_chat_completion(
        {
            "model": "GigaChat-2-Max",
            "input": "hello",
            "store": False,
        }
    )

    assert request.storage is None
    assert "storage" not in request.model_dump(exclude_none=True)


async def test_prepare_response_chat_completion_maps_previous_response_id_to_storage_thread_id():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_response_chat_completion(
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


async def test_prepare_response_chat_completion_maps_function_call_output():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_response_chat_completion(
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


async def test_prepare_response_chat_completion_replays_function_call_with_tools_state_id():
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

    request = await rt.prepare_response_chat_completion(
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
    assert request.storage is None
    assert "storage" not in request.model_dump(exclude_none=True)


async def test_prepare_response_chat_completion_maps_responses_builtin_tools():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_response_chat_completion(
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


async def test_prepare_response_chat_completion_ignores_builtin_tools_when_mapping_disabled():
    cfg = ProxyConfig(proxy=ProxySettings(disable_builtin_tool_mapping=True))
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_response_chat_completion(
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

    assert len(request.tools) == 1
    spec = request.tools[0].functions.specifications[0]
    assert spec.name == "save_result"
    assert spec.parameters["properties"]["value"]["type"] == "string"
    assert request.tool_config is None


async def test_prepare_response_chat_completion_flattens_namespace_tools():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_response_chat_completion(
        {
            "model": "GigaChat-2-Max",
            "input": "Open the browser.",
            "tools": [
                {
                    "type": "namespace",
                    "name": "mcp__playwright",
                    "tools": [
                        {
                            "type": "function",
                            "name": "browser_navigate",
                            "description": "Navigate to a URL.",
                            "parameters": {
                                "type": "object",
                                "properties": {"url": {"type": "string"}},
                            },
                        }
                    ],
                }
            ],
        }
    )

    spec = request.tools[0].functions.specifications[0]
    assert spec.name == "mcp__playwright__browser_navigate"
    assert spec.description == "Navigate to a URL."
    assert spec.parameters["properties"]["url"]["type"] == "string"


async def test_prepare_chat_completion_maps_additional_fields():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion(
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


async def test_prepare_chat_completion_maps_profanity_check_to_disable_filter():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion(
        {
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "hello"}],
            "extra_body": {"profanity_check": False},
        }
    )

    assert request.disable_filter is True
    assert "profanity_check" not in request.model_dump(exclude_none=True)


async def test_prepare_chat_completion_maps_gigachat_profanity_check_default():
    cfg = ProxyConfig(gigachat={"profanity_check": True})
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion(
        {
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "hello"}],
        }
    )

    assert request.disable_filter is False


async def test_prepare_chat_completion_request_profanity_check_overrides_default():
    cfg = ProxyConfig(gigachat={"profanity_check": True})
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion(
        {
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "hello"}],
            "extra_body": {"profanity_check": False},
        }
    )

    assert request.disable_filter is True


async def test_prepare_chat_completion_explicit_disable_filter_overrides_profanity_check():
    cfg = ProxyConfig(gigachat={"profanity_check": True})
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion(
        {
            "model": "GigaChat-2-Max",
            "messages": [{"role": "user", "content": "hello"}],
            "extra_body": {
                "profanity_check": False,
                "disable_filter": False,
            },
        }
    )

    assert request.disable_filter is False


async def test_prepare_chat_completion_reuses_attachment_uploads():
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

    request = await rt.prepare_chat_completion(
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


async def test_prepare_chat_completion_maps_tool_call_result_history():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion(
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


async def test_prepare_chat_completion_repairs_legacy_empty_tool_result():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    request = await rt.prepare_chat_completion(
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


async def test_prepare_chat_completion_maps_gemini_function_calling_example_history():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    normalized = GeminiProtocolAdapter().generate_content_to_normalized(
        {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": "Какая погода в Москве?"}],
                },
                {
                    "role": "model",
                    "parts": [
                        {
                            "functionCall": {
                                "id": "state-1",
                                "name": "get_weather",
                                "args": {"city": "Москва"},
                            }
                        }
                    ],
                },
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "id": "state-1",
                                "name": "get_weather",
                                "response": {
                                    "city": "Москва",
                                    "temperature_c": 5,
                                    "conditions": "облачно",
                                },
                            }
                        }
                    ],
                },
            ],
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": "get_weather",
                            "description": (
                                "Получить текущую погоду для указанного города."
                            ),
                            "parameters": {
                                "type": "OBJECT",
                                "properties": {
                                    "city": {
                                        "type": "STRING",
                                        "description": (
                                            "Название города, например Москва."
                                        ),
                                    }
                                },
                                "required": ["city"],
                            },
                        }
                    ]
                }
            ],
        },
        model="GigaChat-2-Max",
    )

    request = await rt.prepare_chat_completion(
        normalized_chat_to_openai_payload(normalized)
    )

    assert [message.role for message in request.messages] == [
        "user",
        "assistant",
        "tool",
    ]
    assert request.messages[1].tools_state_id == "state-1"
    assert request.messages[1].content[0].function_call.name == "get_weather"
    assert request.messages[1].content[0].function_call.arguments == {"city": "Москва"}
    assert request.messages[2].tools_state_id == "state-1"
    result = request.messages[2].content[0].function_result
    assert result.name == "get_weather"
    assert result.result == {
        "city": "Москва",
        "temperature_c": 5,
        "conditions": "облачно",
    }
    spec = request.tools[0].functions.specifications[0]
    assert spec.name == "get_weather"
    assert spec.parameters["properties"]["city"]["type"] == "string"


async def test_prepare_chat_completion_ignores_gemini_orphaned_function_call():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    normalized = GeminiProtocolAdapter().generate_content_to_normalized(
        {
            "contents": [
                {
                    "role": "model",
                    "parts": [
                        {
                            "functionCall": {
                                "id": "state-1",
                                "name": "run_shell_command",
                                "args": {"command": "pytest"},
                            }
                        }
                    ],
                },
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "id": "state-1",
                                "name": "run_shell_command",
                                "response": {"exit_code": 1},
                            }
                        }
                    ],
                },
                {
                    "role": "model",
                    "parts": [
                        {
                            "functionCall": {
                                "name": "update_topic",
                                "args": {
                                    "strategic_intent": (
                                        "Анализ и корректировка шестого конфликта"
                                    )
                                },
                            }
                        }
                    ],
                },
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": (
                                "System: Potential loop detected. "
                                "Please take a step back."
                            )
                        }
                    ],
                },
            ]
        },
        model="GigaChat-2-Max",
    )

    request = await rt.prepare_chat_completion(
        normalized_chat_to_openai_payload(normalized)
    )

    assert [message.role for message in request.messages] == [
        "assistant",
        "tool",
        "user",
    ]
    assert request.messages[0].content[0].function_call.name == "run_shell_command"
    assert request.messages[1].content[0].function_result.name == "run_shell_command"
    assert request.messages[2].content[0].text.startswith("System: Potential loop")
    assert all(
        part.function_call is None or part.function_call.name != "update_topic"
        for message in request.messages
        for part in message.content
    )
