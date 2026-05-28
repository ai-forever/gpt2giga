import pytest
from loguru import logger

from gpt2giga.common.client_params import ClientCompatibilityError, ClientParamStatus
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
        ClientParamStatus.REJECTED
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
def test_build_openai_data_from_anthropic_request_rejects_stateful_params(param):
    data = {
        "model": "claude-x",
        "messages": [{"role": "user", "content": "hi"}],
        param: {"enabled": True},
    }

    with pytest.raises(ClientCompatibilityError) as exc_info:
        _build_openai_data_from_anthropic_request(data, logger)

    assert exc_info.value.provider == "anthropic"
    assert exc_info.value.param == param


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


def test_build_openai_data_from_anthropic_request_rejects_tool_choice_any():
    data = {
        "model": "claude-x",
        "messages": [{"role": "user", "content": "hi"}],
        "tool_choice": {"type": "any"},
    }

    with pytest.raises(ClientCompatibilityError) as exc_info:
        _build_openai_data_from_anthropic_request(data, logger)

    assert exc_info.value.param == "tool_choice"


@pytest.mark.parametrize(
    "tool_choice",
    [
        {"type": "tool"},
        {"type": "tool", "name": ""},
        {"type": "tool", "name": None},
    ],
)
def test_build_openai_data_from_anthropic_request_rejects_forced_tool_without_name(
    tool_choice,
):
    data = {
        "model": "claude-x",
        "messages": [{"role": "user", "content": "hi"}],
        "tool_choice": tool_choice,
    }

    with pytest.raises(ClientCompatibilityError) as exc_info:
        _build_openai_data_from_anthropic_request(data, logger)

    assert exc_info.value.provider == "anthropic"
    assert exc_info.value.param == "tool_choice"


def test_build_openai_data_from_anthropic_request_rejects_server_tools():
    data = {
        "model": "claude-x",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
    }

    with pytest.raises(ClientCompatibilityError) as exc_info:
        _build_openai_data_from_anthropic_request(data, logger)

    assert exc_info.value.param == "tools"


@pytest.mark.parametrize(
    "tool",
    [
        {"name": "", "input_schema": {"type": "object"}},
        {"name": None, "input_schema": {"type": "object"}},
        {"name": "sum", "input_schema": "bad"},
    ],
)
def test_build_openai_data_from_anthropic_request_rejects_invalid_function_tools(
    tool,
):
    data = {
        "model": "claude-x",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [tool],
    }

    with pytest.raises(ClientCompatibilityError) as exc_info:
        _build_openai_data_from_anthropic_request(data, logger)

    assert exc_info.value.provider == "anthropic"
    assert exc_info.value.param == "tools"


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
def test_build_openai_data_from_anthropic_request_rejects_unsupported_content_blocks(
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

    with pytest.raises(ClientCompatibilityError) as exc_info:
        _build_openai_data_from_anthropic_request(data, logger)

    assert exc_info.value.provider == "anthropic"
    assert block_type in exc_info.value.message
    assert "Supported request content blocks" in exc_info.value.message


def test_build_openai_data_from_anthropic_request_rejects_text_citations():
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

    with pytest.raises(ClientCompatibilityError) as exc_info:
        _build_openai_data_from_anthropic_request(data, logger)

    assert exc_info.value.param == "messages[0].content[0].citations"
    assert "citations" in exc_info.value.message


def test_build_openai_data_from_anthropic_request_rejects_image_file_source():
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

    with pytest.raises(ClientCompatibilityError) as exc_info:
        _build_openai_data_from_anthropic_request(data, logger)

    assert exc_info.value.param == "messages[0].content[0].source.type"
    assert "base64" in exc_info.value.message
    assert "url" in exc_info.value.message


def test_build_openai_data_from_anthropic_request_rejects_nested_tool_result_blocks():
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

    with pytest.raises(ClientCompatibilityError) as exc_info:
        _build_openai_data_from_anthropic_request(data, logger)

    assert exc_info.value.param == "messages[1].content[0].content[0]"
    assert "search_result" in exc_info.value.message


def test_build_openai_data_from_anthropic_request_rejects_unsupported_system_block():
    data = {
        "model": "claude-x",
        "system": [{"type": "document", "source": {"type": "text", "data": "doc"}}],
        "messages": [{"role": "user", "content": "hi"}],
    }

    with pytest.raises(ClientCompatibilityError) as exc_info:
        _build_openai_data_from_anthropic_request(data, logger)

    assert exc_info.value.param == "system[0]"
    assert "document" in exc_info.value.message
