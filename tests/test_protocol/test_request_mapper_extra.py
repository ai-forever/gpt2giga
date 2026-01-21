import pytest
from gpt2giga.protocol.request_mapper import RequestTransformer
from gpt2giga.config import ProxyConfig
from unittest.mock import MagicMock, AsyncMock


@pytest.fixture
def mock_logger():
    return MagicMock()


@pytest.fixture
def mock_attachment_processor():
    ap = AsyncMock()
    ap.upload_file.return_value = "file_id_123"
    return ap


@pytest.fixture
def request_transformer(mock_logger, mock_attachment_processor):
    config = ProxyConfig()
    config.proxy_settings.enable_images = True
    return RequestTransformer(config, mock_logger, mock_attachment_processor)


@pytest.mark.asyncio
async def test_process_content_parts_limits(request_transformer):
    # Test cutting off excess attachments (> 2 per message)
    # We use "file" type because "image_url" has early cutoff in the loop preventing accumulation
    content = [
        {"type": "file", "file": {"filename": "f1", "file_data": "d"}},
        {"type": "file", "file": {"filename": "f2", "file_data": "d"}},
        {"type": "file", "file": {"filename": "f3", "file_data": "d"}},
    ]
    texts, attachments = await request_transformer._process_content_parts(content)
    assert len(attachments) == 2
    assert texts == []
    request_transformer.logger.warning.assert_called_with(
        "GigaChat can only handle 2 images per message. Cutting off excess."
    )


@pytest.mark.asyncio
async def test_process_content_parts_file(request_transformer):
    content = [{"type": "file", "file": {"filename": "f.txt", "file_data": "data"}}]
    texts, attachments = await request_transformer._process_content_parts(content)
    assert len(attachments) == 1
    assert attachments[0] == "file_id_123"


@pytest.mark.asyncio
async def test_transform_messages_roles(request_transformer):
    messages = [
        {"role": "developer", "content": "dev"},
        {"role": "user", "content": "u1"},
        {"role": "system", "content": "sys_later"},  # Should become user
        {
            "role": "tool",
            "content": "tool_res",
            "name": "fn1",
        },  # Should become function
    ]

    res = await request_transformer.transform_messages(messages)

    assert res[0]["role"] == "system"
    assert res[0]["content"] == "dev"

    assert res[2]["role"] == "user"
    assert res[2]["content"] == "sys_later"

    assert res[3]["role"] == "function"
    # Content of tool role is json dumped
    assert res[3]["content"] == '"tool_res"'


@pytest.mark.asyncio
async def test_transform_messages_tool_calls_bad_json(request_transformer):
    messages = [
        {
            "role": "assistant",
            "tool_calls": [{"function": {"name": "fn", "arguments": "{bad_json"}}],
        }
    ]
    res = await request_transformer.transform_messages(messages)
    # Should catch JSONDecodeError and log warning
    request_transformer.logger.warning.assert_called()
    # function_call should still be set but arguments might remain string or be partial?
    # Code:
    # message["function_call"] = message["tool_calls"][0]["function"]
    # try: message["function_call"]["arguments"] = json.loads(...)
    # except: log

    assert "function_call" in res[0]
    assert res[0]["function_call"]["arguments"] == "{bad_json"


def test_transform_chat_parameters(request_transformer):
    data = {
        "temperature": 0,
        "max_output_tokens": 100,
        "response_format": {"type": "json_schema", "json_schema": {"schema": {}}},
        "tools": [{"type": "function", "function": {"name": "f"}}],
    }

    res = request_transformer.transform_chat_parameters(data)

    assert res["top_p"] == 0
    assert "temperature" not in res  # pop(temperature, 0) -> if 0 set top_p=0
    assert res["max_tokens"] == 100
    assert "max_output_tokens" not in res
    # transform_chat_parameters no longer keeps response_format if it is converted to function call
    # assert res["response_format"] == {"type": "json_schema", "schema": {}}
    assert len(res["functions"]) == 2  # One from tools + one from structured output
    assert res["functions"][1]["name"] == "structured_output"
    assert res["function_call"]["name"] == "structured_output"


def test_transform_response_format_complex(request_transformer):
    # response api input format
    data = {
        "instructions": "sys",
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "hello"},
                    {"type": "input_image", "image_url": "http://img"},
                ],
            },
            {"type": "function_call", "name": "fn", "arguments": "{}"},
            {"type": "function_call_output", "output": {"res": 1}},
        ],
    }

    res = request_transformer.transform_response_format(data)

    assert res[0]["role"] == "system"
    assert res[0]["content"] == "sys"

    # User message with list content
    assert res[1]["role"] == "user"
    assert isinstance(res[1]["content"], list)
    assert res[1]["content"][0]["type"] == "text"
    assert res[1]["content"][1]["type"] == "image_url"

    # Function call
    assert res[2]["role"] == "assistant"
    assert res[2]["function_call"]

    # Function output
    assert res[3]["role"] == "function"
    assert res[3]["content"] == '{"res": 1}'


def test_limit_attachments(request_transformer):
    # Setup messages with many attachments
    messages = [
        {"attachments": ["a"] * 5},
        {"attachments": ["b"] * 6},  # Total 11
    ]
    request_transformer._limit_attachments(messages)

    # Should limit to 10 total starting from end?
    # Code iterates reversed.
    # Msg 2 (last): 6 attachments. count=6.
    # Msg 1 (first): 5 attachments. count=6+5=11 > 10.
    # Allowed for Msg 1 = 10 - 6 = 4.

    assert len(messages[1]["attachments"]) == 6
    assert len(messages[0]["attachments"]) == 4
