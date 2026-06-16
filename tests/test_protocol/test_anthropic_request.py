import pytest
from gigachat.models import Chat
from loguru import logger

from gpt2giga.common.client_params import ClientParamStatus
from gpt2giga.models.config import ProxyConfig
from gpt2giga.protocol import RequestTransformer
from gpt2giga.protocol.anthropic.params import classify_anthropic_messages_parameter
from gpt2giga.protocol.anthropic.request import (
    _build_openai_data_from_anthropic_request,
)


def test_build_openai_data_from_anthropic_request_preserves_literal_extra_options():
    data = {
        "model": "claude-x",
        "messages": [{"role": "user", "content": "hi"}],
        "extra_body": {"profanity_check": False},
        "extra_headers": {"x-me": "kus"},
        "extra_query": {"beta": "true"},
    }

    openai_data = _build_openai_data_from_anthropic_request(data, logger)

    assert openai_data["extra_body"] == {"profanity_check": False}
    assert openai_data["extra_headers"] == {"x-me": "kus"}
    assert openai_data["extra_query"] == {"beta": "true"}


def test_anthropic_messages_parameter_classifier_marks_known_states():
    assert classify_anthropic_messages_parameter("messages") == (
        ClientParamStatus.SUPPORTED
    )
    assert classify_anthropic_messages_parameter("top_k") == (
        ClientParamStatus.ACCEPTED_IGNORED
    )
    assert classify_anthropic_messages_parameter("profanity_check") == (
        ClientParamStatus.SUPPORTED
    )
    assert classify_anthropic_messages_parameter("container") == (
        ClientParamStatus.ACCEPTED_IGNORED
    )
    assert classify_anthropic_messages_parameter("custom_flag") == (
        ClientParamStatus.SUPPORTED
    )


def test_build_openai_data_from_anthropic_request_ignores_top_k():
    data = {
        "model": "claude-x",
        "messages": [{"role": "user", "content": "hi"}],
        "top_k": 50,
    }

    openai_data = _build_openai_data_from_anthropic_request(data, logger)

    assert "top_k" not in openai_data
    assert "extra_body" not in openai_data


def test_build_openai_data_from_anthropic_request_ignores_metadata():
    data = {
        "model": "claude-x",
        "messages": [{"role": "user", "content": "hi"}],
        "metadata": {"user_id": "local"},
        "service_tier": "auto",
    }

    openai_data = _build_openai_data_from_anthropic_request(data, logger)

    assert "metadata" not in openai_data
    assert "service_tier" not in openai_data


@pytest.mark.parametrize("param", ["container", "context_management", "mcp_servers"])
def test_build_openai_data_from_anthropic_request_ignores_stateful_params(param):
    data = {
        "model": "claude-x",
        "messages": [{"role": "user", "content": "hi"}],
        param: {"enabled": True},
    }

    openai_data = _build_openai_data_from_anthropic_request(data, logger)

    assert param not in openai_data
    assert "extra_body" not in openai_data


def test_build_openai_data_from_anthropic_request_normalizes_sdk_style_extra_body():
    data = {
        "model": "claude-x",
        "messages": [{"role": "user", "content": "hi"}],
        "profanity_check": False,
    }

    openai_data = _build_openai_data_from_anthropic_request(data, logger)

    assert openai_data["extra_body"] == {"profanity_check": False}
    assert "profanity_check" not in openai_data


def test_build_openai_data_from_anthropic_request_accepts_custom_extra_body():
    data = {
        "model": "claude-x",
        "messages": [{"role": "user", "content": "hi"}],
        "extra_body": {"custom_flag": "on"},
    }

    openai_data = _build_openai_data_from_anthropic_request(data, logger)

    assert openai_data["extra_body"] == {"custom_flag": "on"}


def test_build_openai_data_from_anthropic_request_maps_unknown_sdk_style_extra_body():
    data = {
        "model": "claude-x",
        "messages": [{"role": "user", "content": "hi"}],
        "custom_flag": "on",
    }

    openai_data = _build_openai_data_from_anthropic_request(data, logger)

    assert openai_data["extra_body"] == {"custom_flag": "on"}


def test_build_openai_data_from_anthropic_request_accepts_tool_choice_auto():
    data = {
        "model": "claude-x",
        "messages": [{"role": "user", "content": "hi"}],
        "tool_choice": {"type": "auto"},
    }

    openai_data = _build_openai_data_from_anthropic_request(data, logger)

    assert "tool_choice" not in openai_data


def test_build_openai_data_from_anthropic_request_ignores_tool_choice_any():
    data = {
        "model": "claude-x",
        "messages": [{"role": "user", "content": "hi"}],
        "tool_choice": {"type": "any"},
    }

    openai_data = _build_openai_data_from_anthropic_request(data, logger)

    assert "tool_choice" not in openai_data
    assert "function_call" not in openai_data


@pytest.mark.parametrize(
    "tool_choice",
    [
        {"type": "tool"},
        {"type": "tool", "name": ""},
        {"type": "tool", "name": None},
    ],
)
def test_build_openai_data_from_anthropic_request_ignores_forced_tool_without_name(
    tool_choice,
):
    data = {
        "model": "claude-x",
        "messages": [{"role": "user", "content": "hi"}],
        "tool_choice": tool_choice,
    }

    openai_data = _build_openai_data_from_anthropic_request(data, logger)

    assert "function_call" not in openai_data


def test_build_openai_data_from_anthropic_request_maps_server_tools_to_builtins():
    data = {
        "model": "claude-x",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 5,
                "allowed_domains": ["example.com"],
            },
            {
                "type": "web_fetch_20250910",
                "name": "web_fetch",
                "max_uses": 2,
            },
            {"type": "code_execution_20250825", "name": "code_execution"},
            {
                "name": "sum",
                "description": "Add numbers",
                "input_schema": {
                    "type": "object",
                    "properties": {"a": {"type": "number"}},
                },
            },
        ],
        "tool_choice": {"type": "tool", "name": "web_search"},
    }

    openai_data = _build_openai_data_from_anthropic_request(data, logger)

    assert openai_data["tools"][:3] == [
        {
            "type": "web_search",
            "max_uses": 5,
            "allowed_domains": ["example.com"],
        },
        {"type": "url_content_extraction", "max_uses": 2},
        {"type": "code_interpreter"},
    ]
    assert openai_data["tools"][3]["type"] == "function"
    assert openai_data["tools"][3]["function"]["name"] == "sum"
    assert len(openai_data["functions"]) == 1
    assert openai_data["tool_choice"] == {"type": "web_search"}


def test_build_openai_data_from_anthropic_request_maps_named_websearch_builtin():
    data = {
        "model": "claude-x",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [
            {
                "name": "WebSearch",
                "description": "Allows Claude to search the web.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            }
        ],
        "tool_choice": {"type": "tool", "name": "WebSearch"},
    }

    openai_data = _build_openai_data_from_anthropic_request(data, logger)

    assert openai_data["tools"] == [{"type": "web_search"}]
    assert "functions" not in openai_data
    assert "function_call" not in openai_data
    assert openai_data["tool_choice"] == {"type": "web_search"}


def test_build_openai_data_from_anthropic_request_keeps_custom_web_search_tool():
    data = {
        "model": "claude-x",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [
            {
                "name": "web_search",
                "description": "Local search function.",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            }
        ],
        "tool_choice": {"type": "tool", "name": "web_search"},
    }

    openai_data = _build_openai_data_from_anthropic_request(data, logger)

    assert openai_data["tools"][0]["type"] == "function"
    assert openai_data["tools"][0]["function"]["name"] == "web_search"
    assert openai_data["function_call"] == {"name": "web_search"}


@pytest.mark.parametrize(
    "tool",
    [
        {"name": "", "input_schema": {"type": "object"}},
        {"name": None, "input_schema": {"type": "object"}},
    ],
)
def test_build_openai_data_from_anthropic_request_ignores_nameless_function_tools(
    tool,
):
    data = {
        "model": "claude-x",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [tool],
    }

    openai_data = _build_openai_data_from_anthropic_request(data, logger)

    assert "tools" not in openai_data
    assert "functions" not in openai_data


def test_build_openai_data_from_anthropic_request_defaults_bad_tool_schema():
    data = {
        "model": "claude-x",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{"name": "sum", "input_schema": "bad"}],
    }

    openai_data = _build_openai_data_from_anthropic_request(data, logger)

    assert openai_data["tools"][0]["function"]["parameters"] == {
        "type": "object",
        "properties": {},
    }


def test_build_openai_data_from_anthropic_request_normalizes_tool_schema():
    data = {
        "model": "claude-x",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [
            {
                "name": "final_answer",
                "input_schema": {
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
                    },
                },
            }
        ],
    }

    openai_data = _build_openai_data_from_anthropic_request(data, logger)

    parameters = openai_data["tools"][0]["function"]["parameters"]
    assert parameters["properties"]["answers"] == {
        "type": "object",
        "properties": {},
    }
    assert parameters["properties"]["score"]["type"] == "integer"
    assert "anyOf" not in parameters["properties"]["score"]


def test_build_openai_data_from_anthropic_request_keeps_function_tools():
    data = {
        "model": "claude-x",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [
            {
                "name": "sum",
                "description": "Add numbers",
                "input_schema": {
                    "type": "object",
                    "properties": {"a": {"type": "number"}},
                },
            }
        ],
    }

    openai_data = _build_openai_data_from_anthropic_request(data, logger)

    assert openai_data["tools"][0]["type"] == "function"
    assert openai_data["tools"][0]["function"]["name"] == "sum"
    assert len(openai_data["functions"]) == 1


@pytest.mark.parametrize(
    "block_type",
    [
        "document",
        "file",
        "thinking",
        "redacted_thinking",
        "search_result",
        "container_upload",
    ],
)
def test_build_openai_data_from_anthropic_request_ignores_unsupported_content_blocks(
    block_type,
):
    data = {
        "model": "claude-x",
        "messages": [
            {
                "role": "user",
                "content": [{"type": block_type}],
            }
        ],
    }

    openai_data = _build_openai_data_from_anthropic_request(data, logger)

    assert openai_data["messages"] == [{"role": "user", "content": ""}]


def test_build_openai_data_from_anthropic_request_ignores_text_citations():
    data = {
        "model": "claude-x",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "quoted",
                        "citations": [{"type": "char_location"}],
                    }
                ],
            }
        ],
    }

    openai_data = _build_openai_data_from_anthropic_request(data, logger)

    assert openai_data["messages"] == [{"role": "user", "content": "quoted"}]


def test_build_openai_data_from_anthropic_request_ignores_image_file_source():
    data = {
        "model": "claude-x",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "file", "file_id": "file_123"},
                    }
                ],
            }
        ],
    }

    openai_data = _build_openai_data_from_anthropic_request(data, logger)

    assert openai_data["messages"] == [{"role": "user", "content": ""}]


def test_build_openai_data_from_anthropic_request_ignores_nested_tool_result_blocks():
    data = {
        "model": "claude-x",
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "toolu_1", "name": "search", "input": {}}
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": [{"type": "search_result", "title": "Result"}],
                    }
                ],
            },
        ],
    }

    openai_data = _build_openai_data_from_anthropic_request(data, logger)

    assert openai_data["messages"][1]["role"] == "tool"
    assert openai_data["messages"][1]["content"] == "{}"


async def test_anthropic_tool_result_history_prepares_valid_legacy_chat_payload():
    data = {
        "model": "GigaChat-2-Max",
        "tools": [
            {
                "name": "get_weather",
                "description": "Get weather.",
                "input_schema": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            }
        ],
        "messages": [
            {"role": "user", "content": "Какая погода в Москве?"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_weather_1",
                        "name": "get_weather",
                        "input": {"city": "Москва"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_weather_1",
                        "content": '{"city": "Москва", "temp": "+5°C"}',
                    }
                ],
            },
        ],
    }
    openai_data = _build_openai_data_from_anthropic_request(data, logger)
    rt = RequestTransformer(ProxyConfig(), logger)

    chat = await rt.prepare_chat(openai_data)

    assert [message["role"] for message in chat["messages"]] == ["user", "function"]
    assert chat["messages"][1]["functions_state_id"] == "toolu_weather_1"
    assert chat.get("functions") and len(chat["functions"]) == 1
    Chat.model_validate(chat)


def test_build_openai_data_from_anthropic_request_ignores_unsupported_system_block():
    data = {
        "model": "claude-x",
        "system": [{"type": "document", "source": {"type": "text", "data": "doc"}}],
        "messages": [{"role": "user", "content": "hi"}],
    }

    openai_data = _build_openai_data_from_anthropic_request(data, logger)

    assert openai_data["messages"] == [{"role": "user", "content": "hi"}]
