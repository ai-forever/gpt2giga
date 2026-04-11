"""Tests for Anthropic Messages API router."""

import base64
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger

from gpt2giga.api.anthropic.request import (
    _convert_anthropic_messages_to_openai,
    _convert_anthropic_tools_to_openai,
    _extract_text_from_openai_messages,
    _extract_tool_definitions_text,
)
from gpt2giga.api.anthropic.response import (
    _build_anthropic_response,
    _map_stop_reason,
)
from gpt2giga.api.anthropic import router
from gpt2giga.core.config.settings import ProxyConfig
from gpt2giga.core.contracts import to_backend_payload
from gpt2giga.providers.gigachat import ResponseProcessor


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class MockResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self, *args, **kwargs):
        return self.data


class FakeTokensCount:
    """Mimics gigachat.models.tokens_count.TokensCount."""

    def __init__(self, tokens, characters=0):
        self.tokens = tokens
        self.characters = characters


class FakeGigachat:
    """Configurable fake that returns text or function_call responses."""

    def __init__(self, response_data=None):
        self._response = response_data or {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        }
        self.last_method = None

    async def achat(self, chat):
        self.last_method = "v1"
        return MockResponse(self._response)

    async def achat_v2(self, chat):
        self.last_method = "v2"
        response = self._response
        if "messages" in response:
            return MockResponse(response)

        choice = response["choices"][0]
        message = choice.get("message", {})
        content = []
        if message.get("content"):
            content.append({"text": message["content"]})
        if isinstance(message.get("function_call"), dict):
            content.append({"function_call": message["function_call"]})

        usage = response.get("usage") or {}
        return MockResponse(
            {
                "model": "anthropic-test",
                "created_at": 123,
                "messages": [
                    {
                        "message_id": "msg-1",
                        "role": "assistant",
                        "content": content or [{"text": ""}],
                    }
                ],
                "finish_reason": choice.get("finish_reason"),
                "usage": {
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                },
            }
        )

    async def atokens_count(self, input_, model=None):
        return [FakeTokensCount(tokens=len(s.split())) for s in input_]

    def astream(self, chat):
        async def gen():
            self.last_method = "v1"
            yield MockResponse(
                {"choices": [{"delta": {"content": "Hel"}}], "usage": None}
            )
            yield MockResponse(
                {
                    "choices": [{"delta": {"content": "lo!"}}],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 2,
                        "total_tokens": 12,
                    },
                }
            )

        return gen()

    def astream_v2(self, chat):
        async def gen():
            self.last_method = "v2"
            yield MockResponse(
                {
                    "model": "anthropic-test",
                    "created_at": 123,
                    "messages": [
                        {
                            "message_id": "msg-1",
                            "role": "assistant",
                            "content": [{"text": "Hel"}],
                        }
                    ],
                }
            )
            yield MockResponse(
                {
                    "model": "anthropic-test",
                    "created_at": 123,
                    "messages": [
                        {
                            "message_id": "msg-1",
                            "role": "assistant",
                            "content": [{"text": "lo!"}],
                        }
                    ],
                    "finish_reason": "stop",
                    "usage": {
                        "input_tokens": 10,
                        "input_tokens_details": {"cached_tokens": 0},
                        "output_tokens": 2,
                        "total_tokens": 12,
                    },
                }
            )

        return gen()


class FakeGigachatReasoning:
    """Fake that returns a response with reasoning_content."""

    async def achat(self, chat):
        return MockResponse(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Ответ: 1021 коробка.",
                            "reasoning_content": "847 + 3*156 = 847 + 468 = 1315. 1315 - 294 = 1021.",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 30,
                    "total_tokens": 50,
                },
            }
        )

    def astream(self, chat):
        async def gen():
            yield MockResponse(
                {
                    "choices": [
                        {
                            "delta": {
                                "reasoning_content": "847 + 468 = 1315. 1315 - 294 = 1021.",
                                "content": "",
                            }
                        }
                    ],
                    "usage": None,
                }
            )
            yield MockResponse(
                {
                    "choices": [{"delta": {"content": "Ответ: 1021."}}],
                    "usage": {
                        "prompt_tokens": 20,
                        "completion_tokens": 10,
                        "total_tokens": 30,
                    },
                }
            )

        return gen()


class FakeGigachatFunctionCall:
    """Fake that returns a function call response."""

    async def achat(self, chat):
        return MockResponse(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "function_call": {
                                "name": "get_weather",
                                "arguments": {"location": "San Francisco"},
                            },
                        },
                        "finish_reason": "function_call",
                    }
                ],
                "usage": {
                    "prompt_tokens": 15,
                    "completion_tokens": 8,
                    "total_tokens": 23,
                },
            }
        )

    def astream(self, chat):
        async def gen():
            yield MockResponse(
                {
                    "choices": [
                        {
                            "delta": {
                                "function_call": {
                                    "name": "get_weather",
                                    "arguments": {"location": "SF"},
                                }
                            }
                        }
                    ],
                    "usage": None,
                }
            )

        return gen()


class FakeGigachatFunctionCallReservedWebSearch:
    """Fake that returns an aliased reserved tool name from GigaChat."""

    async def achat(self, chat):
        return MockResponse(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "function_call": {
                                "name": "__gpt2giga_user_search_web",
                                "arguments": {"query": "SF"},
                            },
                        },
                        "finish_reason": "function_call",
                    }
                ],
                "usage": {
                    "prompt_tokens": 15,
                    "completion_tokens": 8,
                    "total_tokens": 23,
                },
            }
        )

    def astream(self, chat):
        async def gen():
            yield MockResponse(
                {
                    "choices": [
                        {
                            "delta": {
                                "function_call": {
                                    "name": "__gpt2giga_user_search_web",
                                    "arguments": {"query": "SF"},
                                }
                            }
                        }
                    ],
                    "usage": None,
                }
            )

        return gen()


class FakeBatchRequestCounts:
    def __init__(self, total, completed=None, failed=None):
        self.total = total
        self.completed = completed
        self.failed = failed


class FakeBatch:
    def __init__(
        self,
        batch_id,
        *,
        status,
        request_counts,
        output_file_id=None,
        created_at=123,
        updated_at=124,
    ):
        self.id_ = batch_id
        self.status = status
        self.request_counts = request_counts
        self.output_file_id = output_file_id
        self.created_at = created_at
        self.updated_at = updated_at


class FakeBatches:
    def __init__(self, batches):
        self.batches = batches


class FakeFileContent:
    def __init__(self, content):
        self.content = content


class FakeGigachatBatches(FakeGigachat):
    def __init__(self):
        super().__init__()
        self.batches = {}
        self.files = {}
        self.last_batch_content = None
        self.last_batch_method = None

    async def acreate_batch(self, file, method):
        self.last_batch_content = file
        self.last_batch_method = method
        output_payload = [
            {
                "id": "req-1",
                "result": {
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "Batch hello"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 3,
                        "completion_tokens": 2,
                        "total_tokens": 5,
                    },
                },
            },
            {
                "id": "req-2",
                "error": {
                    "message": "Bad batch input",
                    "status": 400,
                },
            },
        ]
        self.files["file-output-1"] = FakeFileContent(
            base64.b64encode(
                ("\n".join(json.dumps(row) for row in output_payload) + "\n").encode(
                    "utf-8"
                )
            ).decode("utf-8")
        )
        batch = FakeBatch(
            "batch-1",
            status="completed",
            request_counts=FakeBatchRequestCounts(total=2, completed=1, failed=1),
            output_file_id="file-output-1",
        )
        self.batches[batch.id_] = batch
        return batch

    async def aget_batches(self, batch_id=None):
        if batch_id is None:
            return FakeBatches(list(self.batches.values()))
        batch = self.batches.get(batch_id)
        return FakeBatches([batch] if batch else [])

    async def aget_file_content(self, file_id):
        return self.files[file_id]


class FakeRequestTransformer:
    def __init__(self):
        self.last_mode = None

    async def prepare_chat_completion(self, data, giga_client=None):
        payload = to_backend_payload(data)
        self.last_mode = "v1"
        return {
            "model": payload.get("model", "giga"),
            "messages": payload.get("messages", []),
            "reasoning_effort": payload.get("reasoning_effort"),
            "functions": payload.get("functions"),
            "function_call": payload.get("function_call"),
        }

    async def prepare_chat_completion_v2(self, data, giga_client=None):
        payload = to_backend_payload(data)
        self.last_mode = "v2"

        class Prepared:
            def model_dump(self, *args, **kwargs):
                return {
                    "model": payload.get("model", "giga"),
                    "messages": [
                        {
                            "role": "user",
                            "content": [{"text": str(payload.get("messages", []))}],
                        }
                    ],
                }

        return Prepared()


def make_app(gigachat=None, *, config=None):
    app = FastAPI()
    app.include_router(router)
    app.state.gigachat_client = gigachat or FakeGigachat()
    app.state.response_processor = ResponseProcessor(logger=logger)
    app.state.request_transformer = FakeRequestTransformer()
    app.state.config = config or ProxyConfig()
    app.state.logger = logger
    return app


# ---------------------------------------------------------------------------
# Unit tests for conversion helpers
# ---------------------------------------------------------------------------


class TestConvertAnthropicToolsToOpenai:
    def test_basic_tool(self):
        tools = [
            {
                "name": "get_weather",
                "description": "Get current weather",
                "input_schema": {
                    "type": "object",
                    "properties": {"location": {"type": "string"}},
                    "required": ["location"],
                },
            }
        ]
        result = _convert_anthropic_tools_to_openai(tools)
        assert len(result) == 1
        assert result[0]["type"] == "function"
        fn = result[0]["function"]
        assert fn["name"] == "get_weather"
        assert fn["description"] == "Get current weather"
        assert fn["parameters"]["type"] == "object"

    def test_tool_without_input_schema(self):
        tools = [{"name": "noop", "description": "Does nothing"}]
        result = _convert_anthropic_tools_to_openai(tools)
        assert result[0]["function"]["parameters"] == {
            "type": "object",
            "properties": {},
        }

    def test_multiple_tools(self):
        tools = [
            {"name": "a", "description": "A", "input_schema": {"type": "object"}},
            {"name": "b", "description": "B", "input_schema": {"type": "object"}},
        ]
        result = _convert_anthropic_tools_to_openai(tools)
        assert len(result) == 2
        assert result[0]["function"]["name"] == "a"
        assert result[1]["function"]["name"] == "b"


class TestConvertAnthropicMessagesToOpenai:
    def test_string_system(self):
        result = _convert_anthropic_messages_to_openai(
            "You are helpful.", [{"role": "user", "content": "Hi"}]
        )
        assert result[0] == {"role": "system", "content": "You are helpful."}
        assert result[1] == {"role": "user", "content": "Hi"}

    def test_list_system(self):
        system = [
            {"type": "text", "text": "Line 1"},
            {"type": "text", "text": "Line 2"},
        ]
        result = _convert_anthropic_messages_to_openai(
            system, [{"role": "user", "content": "Hi"}]
        )
        assert result[0]["role"] == "system"
        assert "Line 1" in result[0]["content"]
        assert "Line 2" in result[0]["content"]

    def test_no_system(self):
        result = _convert_anthropic_messages_to_openai(
            None, [{"role": "user", "content": "Hi"}]
        )
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_string_content(self):
        result = _convert_anthropic_messages_to_openai(
            None,
            [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "World"},
            ],
        )
        assert result[0] == {"role": "user", "content": "Hello"}
        assert result[1] == {"role": "assistant", "content": "World"}

    def test_user_text_blocks(self):
        result = _convert_anthropic_messages_to_openai(
            None,
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Part 1"},
                        {"type": "text", "text": "Part 2"},
                    ],
                }
            ],
        )
        assert result[0]["role"] == "user"
        assert "Part 1" in result[0]["content"]
        assert "Part 2" in result[0]["content"]

    def test_user_image_block_base64(self):
        result = _convert_anthropic_messages_to_openai(
            None,
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this"},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": "abc123",
                            },
                        },
                    ],
                }
            ],
        )
        assert result[0]["role"] == "user"
        content = result[0]["content"]
        assert isinstance(content, list)
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "image_url"
        assert "data:image/png;base64,abc123" in content[1]["image_url"]["url"]

    def test_user_image_block_url(self):
        result = _convert_anthropic_messages_to_openai(
            None,
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "url",
                                "url": "https://example.com/img.png",
                            },
                        }
                    ],
                }
            ],
        )
        content = result[0]["content"]
        assert isinstance(content, list)
        assert content[0]["image_url"]["url"] == "https://example.com/img.png"

    def test_assistant_tool_use(self):
        result = _convert_anthropic_messages_to_openai(
            None,
            [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_123",
                            "name": "get_weather",
                            "input": {"location": "SF"},
                        }
                    ],
                }
            ],
        )
        msg = result[0]
        assert msg["role"] == "assistant"
        assert len(msg["tool_calls"]) == 1
        tc = msg["tool_calls"][0]
        assert tc["id"] == "toolu_123"
        assert tc["function"]["name"] == "get_weather"
        assert json.loads(tc["function"]["arguments"]) == {"location": "SF"}

    def test_assistant_text_and_tool_use(self):
        result = _convert_anthropic_messages_to_openai(
            None,
            [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Let me check."},
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "search",
                            "input": {"q": "test"},
                        },
                    ],
                }
            ],
        )
        msg = result[0]
        assert msg["content"] == "Let me check."
        assert len(msg["tool_calls"]) == 1

    def test_user_tool_result(self):
        result = _convert_anthropic_messages_to_openai(
            None,
            [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "fn",
                            "input": {},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_1",
                            "content": "result",
                        }
                    ],
                },
            ],
        )
        # The tool_result should become a tool role message
        tool_msg = [m for m in result if m["role"] == "tool"]
        assert len(tool_msg) == 1
        assert tool_msg[0]["tool_call_id"] == "toolu_1"
        assert tool_msg[0]["name"] == "fn"

    def test_user_tool_result_with_text(self):
        result = _convert_anthropic_messages_to_openai(
            None,
            [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "fn",
                            "input": {},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "t1",
                            "content": "65 degrees",
                        },
                        {"type": "text", "text": "What about tomorrow?"},
                    ],
                },
            ],
        )
        tool_msgs = [m for m in result if m["role"] == "tool"]
        user_msgs = [m for m in result if m["role"] == "user"]
        assert len(tool_msgs) == 1
        assert len(user_msgs) == 1
        assert "tomorrow" in user_msgs[0]["content"]

    def test_user_tool_result_list_content(self):
        result = _convert_anthropic_messages_to_openai(
            None,
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "t1",
                            "content": [{"type": "text", "text": "data"}],
                        }
                    ],
                },
            ],
        )
        tool_msgs = [m for m in result if m["role"] == "tool"]
        assert len(tool_msgs) == 1

    def test_non_list_content(self):
        result = _convert_anthropic_messages_to_openai(
            None, [{"role": "user", "content": 42}]
        )
        assert result[0]["content"] == "42"

    def test_non_list_content_other_role(self):
        result = _convert_anthropic_messages_to_openai(
            None, [{"role": "custom_role", "content": [{"type": "text", "text": "x"}]}]
        )
        assert len(result) == 1


class TestMapStopReason:
    def test_stop(self):
        assert _map_stop_reason("stop") == "end_turn"

    def test_length(self):
        assert _map_stop_reason("length") == "max_tokens"

    def test_function_call(self):
        assert _map_stop_reason("function_call") == "tool_use"

    def test_content_filter(self):
        assert _map_stop_reason("content_filter") == "end_turn"

    def test_none(self):
        assert _map_stop_reason(None) == "end_turn"

    def test_unknown(self):
        assert _map_stop_reason("xyz") == "end_turn"


class TestBuildAnthropicResponse:
    def test_text_response(self):
        giga = {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Hi!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        }
        result = _build_anthropic_response(giga, "claude-test", "rq123")
        assert result["type"] == "message"
        assert result["role"] == "assistant"
        assert result["content"][0]["type"] == "text"
        assert result["content"][0]["text"] == "Hi!"
        assert result["stop_reason"] == "end_turn"
        assert result["usage"]["input_tokens"] == 5
        assert result["usage"]["output_tokens"] == 3

    def test_function_call_response(self):
        giga = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "function_call": {
                            "name": "search",
                            "arguments": {"q": "test"},
                        },
                    },
                    "finish_reason": "function_call",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        result = _build_anthropic_response(giga, "claude-test", "rq456")
        assert result["stop_reason"] == "tool_use"
        assert result["content"][0]["type"] == "tool_use"
        assert result["content"][0]["name"] == "search"
        assert result["content"][0]["input"] == {"q": "test"}

    def test_function_call_unmaps_reserved_web_search(self):
        giga = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "function_call": {
                            "name": "__gpt2giga_user_search_web",
                            "arguments": {"query": "test"},
                        },
                    },
                    "finish_reason": "function_call",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        result = _build_anthropic_response(giga, "claude-test", "rq456")
        assert result["stop_reason"] == "tool_use"
        assert result["content"][0]["type"] == "tool_use"
        assert result["content"][0]["name"] == "web_search"

    def test_function_call_string_arguments(self):
        giga = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "function_call": {
                            "name": "fn",
                            "arguments": '{"a": 1}',
                        },
                    },
                    "finish_reason": "function_call",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        result = _build_anthropic_response(giga, "m", "rq")
        assert result["content"][0]["input"] == {"a": 1}

    def test_function_call_invalid_json_arguments(self):
        giga = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "function_call": {
                            "name": "fn",
                            "arguments": "not-json",
                        },
                    },
                    "finish_reason": "function_call",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        result = _build_anthropic_response(giga, "m", "rq")
        assert result["content"][0]["input"] == {}

    def test_empty_content(self):
        giga = {
            "choices": [
                {
                    "message": {"role": "assistant", "content": None},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": 1},
        }
        result = _build_anthropic_response(giga, "m", "rq")
        assert result["content"][0]["text"] == ""

    def test_text_response_with_reasoning(self):
        giga = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Answer: 42",
                        "reasoning_content": "Let me think... 6 * 7 = 42",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
        }
        result = _build_anthropic_response(giga, "claude-test", "rq")
        # thinking block should come first
        assert result["content"][0]["type"] == "thinking"
        assert result["content"][0]["thinking"] == "Let me think... 6 * 7 = 42"
        # text block second
        assert result["content"][1]["type"] == "text"
        assert result["content"][1]["text"] == "Answer: 42"

    def test_no_reasoning_when_absent(self):
        giga = {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Hi!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        result = _build_anthropic_response(giga, "m", "rq")
        assert len(result["content"]) == 1
        assert result["content"][0]["type"] == "text"


# ---------------------------------------------------------------------------
# Integration tests for the endpoint
# ---------------------------------------------------------------------------


class TestMessagesEndpoint:
    def test_non_stream_basic(self):
        app = make_app()
        client = TestClient(app)
        payload = {
            "model": "claude-test",
            "max_tokens": 100,
            "messages": [{"role": "user", "content": "Hello"}],
        }
        resp = client.post("/messages", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["type"] == "message"
        assert body["role"] == "assistant"
        assert body["content"][0]["type"] == "text"
        assert body["stop_reason"] == "end_turn"

    def test_non_stream_with_system(self):
        app = make_app()
        client = TestClient(app)
        payload = {
            "model": "claude-test",
            "max_tokens": 100,
            "system": "Be concise.",
            "messages": [{"role": "user", "content": "Hello"}],
        }
        resp = client.post("/messages", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["type"] == "message"

    def test_non_stream_with_tools(self):
        app = make_app(FakeGigachatFunctionCall())
        client = TestClient(app)
        payload = {
            "model": "claude-test",
            "max_tokens": 100,
            "messages": [{"role": "user", "content": "Weather?"}],
            "tools": [
                {
                    "name": "get_weather",
                    "description": "Get weather",
                    "input_schema": {
                        "type": "object",
                        "properties": {"location": {"type": "string"}},
                    },
                }
            ],
        }
        resp = client.post("/messages", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["stop_reason"] == "tool_use"
        assert body["content"][0]["type"] == "tool_use"
        assert body["content"][0]["name"] == "get_weather"

    def test_non_stream_unmaps_reserved_web_search(self):
        app = make_app(FakeGigachatFunctionCallReservedWebSearch())
        client = TestClient(app)
        payload = {
            "model": "claude-test",
            "max_tokens": 100,
            "messages": [{"role": "user", "content": "Search?"}],
            "tools": [
                {
                    "name": "web_search",
                    "description": "Search web",
                    "input_schema": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                    },
                }
            ],
        }
        resp = client.post("/messages", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["stop_reason"] == "tool_use"
        assert body["content"][0]["type"] == "tool_use"
        assert body["content"][0]["name"] == "web_search"

    def test_non_stream_with_tool_choice_specific(self):
        app = make_app(FakeGigachatFunctionCall())
        client = TestClient(app)
        payload = {
            "model": "claude-test",
            "max_tokens": 100,
            "messages": [{"role": "user", "content": "Weather?"}],
            "tools": [
                {
                    "name": "get_weather",
                    "description": "Get weather",
                    "input_schema": {
                        "type": "object",
                        "properties": {"location": {"type": "string"}},
                    },
                }
            ],
            "tool_choice": {"type": "tool", "name": "get_weather"},
        }
        resp = client.post("/messages", json=payload)
        assert resp.status_code == 200

    def test_non_stream_with_tool_choice_none(self):
        app = make_app()
        client = TestClient(app)
        payload = {
            "model": "claude-test",
            "max_tokens": 100,
            "messages": [{"role": "user", "content": "Hello"}],
            "tools": [
                {
                    "name": "fn",
                    "description": "",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ],
            "tool_choice": {"type": "none"},
        }
        resp = client.post("/messages", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["stop_reason"] == "end_turn"

    def test_non_stream_with_temperature(self):
        app = make_app()
        client = TestClient(app)
        payload = {
            "model": "claude-test",
            "max_tokens": 100,
            "temperature": 0.7,
            "top_p": 0.9,
            "messages": [{"role": "user", "content": "Hello"}],
        }
        resp = client.post("/messages", json=payload)
        assert resp.status_code == 200

    def test_non_stream_v2_mode_uses_chat_v2_backend(self):
        app = make_app(
            config=ProxyConfig.model_validate({"proxy": {"gigachat_api_mode": "v2"}})
        )
        client = TestClient(app)
        payload = {
            "model": "claude-test",
            "max_tokens": 100,
            "messages": [{"role": "user", "content": "Hello"}],
        }

        resp = client.post("/messages", json=payload)

        assert resp.status_code == 200
        assert app.state.gigachat_client.last_method == "v2"
        assert app.state.request_transformer.last_mode == "v2"

    def test_non_stream_with_stop_sequences(self):
        app = make_app()
        client = TestClient(app)
        payload = {
            "model": "claude-test",
            "max_tokens": 100,
            "stop_sequences": ["\n\nHuman:"],
            "messages": [{"role": "user", "content": "Hello"}],
        }
        resp = client.post("/messages", json=payload)
        assert resp.status_code == 200

    def test_stream_basic(self):
        app = make_app()
        client = TestClient(app)
        payload = {
            "model": "claude-test",
            "max_tokens": 100,
            "stream": True,
            "messages": [{"role": "user", "content": "Hello"}],
        }
        resp = client.post("/messages", json=payload)
        assert resp.status_code == 200

        lines = resp.text.strip().split("\n")
        events = []
        for line in lines:
            if line.startswith("event: "):
                events.append(line.replace("event: ", ""))

        assert "message_start" in events
        assert "ping" in events
        assert "content_block_start" in events
        assert "content_block_delta" in events
        assert "content_block_stop" in events
        assert "message_delta" in events
        assert "message_stop" in events

        data_lines = [
            line.replace("data: ", "") for line in lines if line.startswith("data: ")
        ]
        for data in data_lines:
            parsed = json.loads(data)
            if parsed.get("type") == "message_delta":
                assert parsed["usage"]["input_tokens"] == 10
                assert parsed["usage"]["output_tokens"] == 2
                break
        else:
            raise AssertionError("message_delta event not found")

    def test_stream_function_call(self):
        app = make_app(FakeGigachatFunctionCall())
        client = TestClient(app)
        payload = {
            "model": "claude-test",
            "max_tokens": 100,
            "stream": True,
            "messages": [{"role": "user", "content": "Weather?"}],
            "tools": [
                {
                    "name": "get_weather",
                    "description": "Get weather",
                    "input_schema": {
                        "type": "object",
                        "properties": {"location": {"type": "string"}},
                    },
                }
            ],
        }
        resp = client.post("/messages", json=payload)
        assert resp.status_code == 200

        events = []
        data_lines = []
        for line in resp.text.strip().split("\n"):
            if line.startswith("event: "):
                events.append(line.replace("event: ", ""))
            elif line.startswith("data: "):
                data_lines.append(line.replace("data: ", ""))

        assert "content_block_start" in events
        assert "content_block_delta" in events

        # Find the content_block_start data
        for d in data_lines:
            parsed = json.loads(d)
            if parsed.get("type") == "content_block_start":
                assert parsed["content_block"]["type"] == "tool_use"
                assert parsed["content_block"]["name"] == "get_weather"
                break

        # Check message_delta has tool_use stop reason
        for d in data_lines:
            parsed = json.loads(d)
            if parsed.get("type") == "message_delta":
                assert parsed["delta"]["stop_reason"] == "tool_use"
                break

    def test_stream_unmaps_reserved_web_search(self):
        app = make_app(FakeGigachatFunctionCallReservedWebSearch())
        client = TestClient(app)
        payload = {
            "model": "claude-test",
            "max_tokens": 100,
            "stream": True,
            "messages": [{"role": "user", "content": "Search?"}],
            "tools": [
                {
                    "name": "web_search",
                    "description": "Search web",
                    "input_schema": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                    },
                }
            ],
        }
        resp = client.post("/messages", json=payload)
        assert resp.status_code == 200

        data_lines = []
        for line in resp.text.strip().split("\n"):
            if line.startswith("data: "):
                data_lines.append(line.replace("data: ", ""))

        for d in data_lines:
            parsed = json.loads(d)
            if parsed.get("type") == "content_block_start":
                assert parsed["content_block"]["type"] == "tool_use"
                assert parsed["content_block"]["name"] == "web_search"
                break

    def test_multi_turn_conversation(self):
        app = make_app()
        client = TestClient(app)
        payload = {
            "model": "claude-test",
            "max_tokens": 100,
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi!"},
                {"role": "user", "content": "How are you?"},
            ],
        }
        resp = client.post("/messages", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["type"] == "message"

    def test_non_stream_with_tool_choice_auto(self):
        app = make_app()
        client = TestClient(app)
        payload = {
            "model": "claude-test",
            "max_tokens": 100,
            "messages": [{"role": "user", "content": "Hello"}],
            "tool_choice": {"type": "auto"},
        }
        resp = client.post("/messages", json=payload)
        assert resp.status_code == 200

    def test_non_stream_with_thinking(self):
        app = make_app(FakeGigachatReasoning())
        client = TestClient(app)
        payload = {
            "model": "claude-test",
            "max_tokens": 16000,
            "thinking": {"type": "enabled", "budget_tokens": 10000},
            "messages": [{"role": "user", "content": "What is 6*7?"}],
        }
        resp = client.post("/messages", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["type"] == "message"
        # First block should be thinking
        assert body["content"][0]["type"] == "thinking"
        assert "1021" in body["content"][0]["thinking"]
        # Second block should be text
        assert body["content"][1]["type"] == "text"

    def test_thinking_budget_maps_to_reasoning_effort_high(self):
        app = make_app()
        client = TestClient(app)
        payload = {
            "model": "claude-test",
            "max_tokens": 1024,
            "thinking": {"type": "enabled", "budget_tokens": 10000},
            "messages": [{"role": "user", "content": "Hi"}],
        }
        resp = client.post("/messages", json=payload)
        assert resp.status_code == 200

    def test_thinking_budget_maps_to_reasoning_effort_medium(self):
        app = make_app()
        client = TestClient(app)
        payload = {
            "model": "claude-test",
            "max_tokens": 1024,
            "thinking": {"type": "enabled", "budget_tokens": 5000},
            "messages": [{"role": "user", "content": "Hi"}],
        }
        resp = client.post("/messages", json=payload)
        assert resp.status_code == 200

    def test_thinking_budget_maps_to_reasoning_effort_low(self):
        app = make_app()
        client = TestClient(app)
        payload = {
            "model": "claude-test",
            "max_tokens": 1024,
            "thinking": {"type": "enabled", "budget_tokens": 1000},
            "messages": [{"role": "user", "content": "Hi"}],
        }
        resp = client.post("/messages", json=payload)
        assert resp.status_code == 200

    def test_stream_with_reasoning(self):
        app = make_app(FakeGigachatReasoning())
        client = TestClient(app)
        payload = {
            "model": "claude-test",
            "max_tokens": 16000,
            "stream": True,
            "thinking": {"type": "enabled", "budget_tokens": 10000},
            "messages": [{"role": "user", "content": "Solve a math problem."}],
        }
        resp = client.post("/messages", json=payload)
        assert resp.status_code == 200

        events = []
        data_lines = []
        for line in resp.text.strip().split("\n"):
            if line.startswith("event: "):
                events.append(line.replace("event: ", ""))
            elif line.startswith("data: "):
                data_lines.append(line.replace("data: ", ""))

        # Should have thinking content block events
        block_starts = [
            json.loads(d)
            for d in data_lines
            if json.loads(d).get("type") == "content_block_start"
        ]
        types = [b["content_block"]["type"] for b in block_starts]
        assert "thinking" in types

        # Should also have a thinking_delta
        deltas = [
            json.loads(d)
            for d in data_lines
            if json.loads(d).get("type") == "content_block_delta"
        ]
        delta_types = [d["delta"]["type"] for d in deltas]
        assert "thinking_delta" in delta_types
        assert "text_delta" in delta_types

        # Thinking block index should be 0, text block index should be 1
        for b in block_starts:
            if b["content_block"]["type"] == "thinking":
                assert b["index"] == 0
            elif b["content_block"]["type"] == "text":
                assert b["index"] == 1

    def test_stream_v2_mode_uses_chat_v2_backend(self):
        app = make_app(
            config=ProxyConfig.model_validate({"proxy": {"gigachat_api_mode": "v2"}})
        )
        client = TestClient(app)
        payload = {
            "model": "claude-test",
            "max_tokens": 100,
            "stream": True,
            "messages": [{"role": "user", "content": "Hello"}],
        }

        resp = client.post("/messages", json=payload)

        assert resp.status_code == 200
        assert "content_block_delta" in resp.text
        assert app.state.gigachat_client.last_method == "v2"
        assert app.state.request_transformer.last_mode == "v2"


class TestConvertAssistantTextOnly:
    """Cover the else branch where assistant has only text blocks."""

    def test_assistant_only_text_blocks(self):
        result = _convert_anthropic_messages_to_openai(
            None,
            [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Hello"},
                        {"type": "text", "text": "World"},
                    ],
                }
            ],
        )
        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        assert "tool_calls" not in result[0]
        assert "Hello" in result[0]["content"]
        assert "World" in result[0]["content"]


# ---------------------------------------------------------------------------
# Unit tests for token counting helpers
# ---------------------------------------------------------------------------


class TestExtractTextFromOpenaiMessages:
    def test_string_content(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello world"},
        ]
        texts = _extract_text_from_openai_messages(messages)
        assert texts == ["You are helpful.", "Hello world"]

    def test_empty_content_skipped(self):
        messages = [{"role": "user", "content": ""}]
        texts = _extract_text_from_openai_messages(messages)
        assert texts == []

    def test_list_content_extracts_text_parts(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Part 1"},
                    {"type": "image_url", "image_url": {"url": "http://img"}},
                    {"type": "text", "text": "Part 2"},
                ],
            }
        ]
        texts = _extract_text_from_openai_messages(messages)
        assert texts == ["Part 1", "Part 2"]

    def test_tool_calls_extracted(self):
        messages = [
            {
                "role": "assistant",
                "content": "Checking weather",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"location": "SF"}',
                        },
                    }
                ],
            }
        ]
        texts = _extract_text_from_openai_messages(messages)
        assert "Checking weather" in texts
        assert "get_weather" in texts
        assert '{"location": "SF"}' in texts

    def test_no_messages(self):
        assert _extract_text_from_openai_messages([]) == []

    def test_missing_content_key(self):
        messages = [{"role": "user"}]
        texts = _extract_text_from_openai_messages(messages)
        assert texts == []


class TestExtractToolDefinitionsText:
    def test_basic_tool(self):
        tools = [
            {
                "name": "get_weather",
                "description": "Get current weather",
                "input_schema": {
                    "type": "object",
                    "properties": {"location": {"type": "string"}},
                },
            }
        ]
        texts = _extract_tool_definitions_text(tools)
        assert len(texts) == 1
        assert "get_weather" in texts[0]
        assert "Get current weather" in texts[0]
        assert "location" in texts[0]

    def test_tool_without_schema(self):
        tools = [{"name": "noop", "description": "Does nothing"}]
        texts = _extract_tool_definitions_text(tools)
        assert len(texts) == 1
        assert "noop" in texts[0]
        assert "Does nothing" in texts[0]

    def test_empty_tools(self):
        assert _extract_tool_definitions_text([]) == []

    def test_multiple_tools(self):
        tools = [
            {"name": "a", "description": "Tool A"},
            {"name": "b", "description": "Tool B"},
        ]
        texts = _extract_tool_definitions_text(tools)
        assert len(texts) == 2


# ---------------------------------------------------------------------------
# Integration tests for count_tokens endpoint
# ---------------------------------------------------------------------------


class TestCountTokensEndpoint:
    def test_basic_count(self):
        app = make_app()
        client = TestClient(app)
        payload = {
            "model": "claude-test",
            "messages": [{"role": "user", "content": "Hello world"}],
        }
        resp = client.post("/messages/count_tokens", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert "input_tokens" in body
        assert isinstance(body["input_tokens"], int)
        assert body["input_tokens"] > 0

    def test_count_with_system(self):
        app = make_app()
        client = TestClient(app)
        payload = {
            "model": "claude-test",
            "system": "You are a helpful assistant.",
            "messages": [{"role": "user", "content": "Hi"}],
        }
        resp = client.post("/messages/count_tokens", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["input_tokens"] > 0

    def test_count_with_tools(self):
        app = make_app()
        client = TestClient(app)
        payload = {
            "model": "claude-test",
            "messages": [{"role": "user", "content": "Weather?"}],
            "tools": [
                {
                    "name": "get_weather",
                    "description": "Get current weather",
                    "input_schema": {
                        "type": "object",
                        "properties": {"location": {"type": "string"}},
                    },
                }
            ],
        }
        resp = client.post("/messages/count_tokens", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        # Should count both message tokens and tool definition tokens
        assert body["input_tokens"] > 0

    def test_count_empty_messages(self):
        app = make_app()
        client = TestClient(app)
        payload = {
            "model": "claude-test",
            "messages": [],
        }
        resp = client.post("/messages/count_tokens", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["input_tokens"] == 0

    def test_count_multi_turn(self):
        app = make_app()
        client = TestClient(app)
        payload = {
            "model": "claude-test",
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"},
                {"role": "user", "content": "How are you?"},
            ],
        }
        resp = client.post("/messages/count_tokens", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["input_tokens"] > 0

    def test_count_with_beta_query_param(self):
        """Verify endpoint works with ?beta=true query param."""
        app = make_app()
        client = TestClient(app)
        payload = {
            "model": "claude-test",
            "messages": [{"role": "user", "content": "Hello"}],
        }
        resp = client.post("/messages/count_tokens?beta=true", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert "input_tokens" in body


class TestMessageBatchesEndpoint:
    def test_batch_lifecycle_and_results(self):
        app = make_app(FakeGigachatBatches())
        giga_client = app.state.gigachat_client
        client = TestClient(app)

        payload = {
            "requests": [
                {
                    "custom_id": "req-1",
                    "params": {
                        "model": "claude-test",
                        "max_tokens": 64,
                        "messages": [{"role": "user", "content": "Hello batch"}],
                    },
                },
                {
                    "custom_id": "req-2",
                    "params": {
                        "model": "claude-test",
                        "max_tokens": 64,
                        "messages": [{"role": "user", "content": "This one errors"}],
                    },
                },
            ]
        }

        created = client.post("/messages/batches", json=payload)
        assert created.status_code == 200
        body = created.json()
        assert body["type"] == "message_batch"
        assert body["processing_status"] == "ended"
        assert body["results_url"] == "/v1/messages/batches/batch-1/results"
        assert giga_client.last_batch_method == "chat_completions"

        translated_lines = [
            json.loads(line)
            for line in giga_client.last_batch_content.decode("utf-8").splitlines()
        ]
        assert translated_lines[0]["id"] == "req-1"
        assert translated_lines[0]["request"]["messages"][0]["content"] == "Hello batch"
        assert "custom_id" not in translated_lines[0]
        assert "body" not in translated_lines[0]

        listed = client.get("/messages/batches")
        assert listed.status_code == 200
        listed_body = listed.json()
        assert listed_body["data"][0]["id"] == "batch-1"
        assert listed_body["first_id"] == "batch-1"
        assert listed_body["last_id"] == "batch-1"

        retrieved = client.get("/messages/batches/batch-1")
        assert retrieved.status_code == 200
        assert retrieved.json()["request_counts"] == {
            "canceled": 0,
            "errored": 1,
            "expired": 0,
            "processing": 0,
            "succeeded": 1,
        }

        results = client.get("/messages/batches/batch-1/results")
        assert results.status_code == 200
        lines = [json.loads(line) for line in results.text.strip().splitlines()]
        assert lines[0]["custom_id"] == "req-1"
        assert lines[0]["result"]["type"] == "succeeded"
        assert lines[0]["result"]["message"]["type"] == "message"
        assert lines[0]["result"]["message"]["content"][0]["text"] == "Batch hello"
        assert lines[1]["custom_id"] == "req-2"
        assert lines[1]["result"]["type"] == "errored"
        assert lines[1]["result"]["error"]["type"] == "error"
        assert lines[1]["result"]["error"]["error"]["message"] == "Bad batch input"

    def test_batch_create_rejects_streaming_requests(self):
        app = make_app(FakeGigachatBatches())
        client = TestClient(app)

        payload = {
            "requests": [
                {
                    "custom_id": "req-1",
                    "params": {
                        "model": "claude-test",
                        "max_tokens": 64,
                        "stream": True,
                        "messages": [{"role": "user", "content": "Hello batch"}],
                    },
                }
            ]
        }

        response = client.post("/messages/batches", json=payload)
        assert response.status_code == 400
        assert response.json()["error"]["type"] == "invalid_request_error"

    def test_batch_create_accepts_24h_completion_window(self):
        app = make_app(FakeGigachatBatches())
        client = TestClient(app)

        payload = {
            "completion_window": "24h",
            "requests": [
                {
                    "custom_id": "req-1",
                    "params": {
                        "model": "claude-test",
                        "max_tokens": 64,
                        "messages": [{"role": "user", "content": "Hello batch"}],
                    },
                }
            ],
        }

        response = client.post("/messages/batches", json=payload)

        assert response.status_code == 200
        assert response.json()["type"] == "message_batch"

    def test_batch_create_rejects_unsupported_completion_window(self):
        app = make_app(FakeGigachatBatches())
        client = TestClient(app)

        payload = {
            "completion_window": "1h",
            "requests": [
                {
                    "custom_id": "req-1",
                    "params": {
                        "model": "claude-test",
                        "max_tokens": 64,
                        "messages": [{"role": "user", "content": "Hello batch"}],
                    },
                }
            ],
        }

        response = client.post("/messages/batches", json=payload)

        assert response.status_code == 400
        assert response.json()["error"]["type"] == "invalid_request_error"
        assert "completion_window" in response.json()["error"]["message"]

    def test_batch_cancel_and_delete_surface_not_implemented(self):
        app = make_app(FakeGigachatBatches())
        client = TestClient(app)

        client.post(
            "/messages/batches",
            json={
                "requests": [
                    {
                        "custom_id": "req-1",
                        "params": {
                            "model": "claude-test",
                            "max_tokens": 64,
                            "messages": [{"role": "user", "content": "Hello batch"}],
                        },
                    }
                ]
            },
        )

        cancel = client.post("/messages/batches/batch-1/cancel")
        assert cancel.status_code == 501
        assert cancel.json()["error"]["type"] == "api_error"

        delete = client.delete("/messages/batches/batch-1")
        assert delete.status_code == 501
        assert delete.json()["error"]["type"] == "api_error"

    def test_openapi_includes_examples_for_message_batches(self):
        app = make_app(FakeGigachatBatches())

        schema = app.openapi()
        batch_examples = schema["paths"]["/messages/batches"]["post"]["requestBody"][
            "content"
        ]["application/json"]["examples"]

        assert "minimal" in batch_examples
        assert batch_examples["minimal"]["value"]["requests"][0]["custom_id"] == "req-1"
        assert "full" in batch_examples
        assert "multiple_requests" in batch_examples
