"""
Тесты для поддержки structured output через json_schema → function calling.

GigaChat не поддерживает response_format: json_schema напрямую,
поэтому мы эмулируем это через function calling.
"""
from types import SimpleNamespace

from loguru import logger

from gpt2giga.config import ProxyConfig
from gpt2giga.protocol import (
    RESPONSE_FORMAT_FUNCTION_NAME,
    RequestTransformer,
    ResponseProcessor,
    convert_response_format_to_function,
    is_json_schema_response,
)


class TestConvertResponseFormatToFunction:
    """Тесты для convert_response_format_to_function"""

    def test_returns_none_for_none(self):
        assert convert_response_format_to_function(None) is None

    def test_returns_none_for_text_type(self):
        assert convert_response_format_to_function({"type": "text"}) is None

    def test_returns_none_for_json_object_type(self):
        assert convert_response_format_to_function({"type": "json_object"}) is None

    def test_converts_json_schema_to_function(self):
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "user_info",
                "description": "User information",
                "schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "age": {"type": "integer"},
                    },
                    "required": ["name", "age"],
                },
            },
        }

        func = convert_response_format_to_function(response_format)

        assert func is not None
        assert func["name"] == "user_info"
        assert func["description"] == "User information"
        assert func["parameters"]["type"] == "object"
        assert "name" in func["parameters"]["properties"]
        assert "age" in func["parameters"]["properties"]

    def test_uses_default_function_name(self):
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "schema": {"type": "object"},
            },
        }

        func = convert_response_format_to_function(response_format)

        assert func["name"] == RESPONSE_FORMAT_FUNCTION_NAME
        assert func["description"] == "Return structured JSON response"


class TestIsJsonSchemaResponse:
    """Тесты для is_json_schema_response"""

    def test_returns_false_for_none_format(self):
        assert is_json_schema_response("any_name", None) is False

    def test_returns_false_for_text_type(self):
        assert is_json_schema_response("any_name", {"type": "text"}) is False

    def test_returns_false_for_wrong_function_name(self):
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": "expected_name"},
        }
        assert is_json_schema_response("wrong_name", response_format) is False

    def test_returns_true_for_matching_name(self):
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": "user_info"},
        }
        assert is_json_schema_response("user_info", response_format) is True

    def test_returns_true_for_default_name(self):
        response_format = {
            "type": "json_schema",
            "json_schema": {},
        }
        assert is_json_schema_response(RESPONSE_FORMAT_FUNCTION_NAME, response_format) is True


class TestTransformChatParametersJsonSchema:
    """Тесты для transform_chat_parameters с json_schema"""

    def test_json_schema_converted_to_function(self):
        cfg = ProxyConfig()
        rt = RequestTransformer(cfg, logger=logger)

        data = {
            "messages": [{"role": "user", "content": "Get user info"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "user_info",
                    "schema": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                    },
                },
            },
        }

        out = rt.transform_chat_parameters(data)

        # Проверяем, что функция добавлена
        assert "functions" in out
        assert len(out["functions"]) == 1
        assert out["functions"][0]["name"] == "user_info"

        # Проверяем, что function_call установлен
        assert "function_call" in out
        assert out["function_call"]["name"] == "user_info"

        # Проверяем, что response_format НЕ установлен (так как конвертирован)
        assert "response_format" not in out

        # Проверяем, что response_format сохранён для обратной конвертации
        assert rt._current_response_format is not None
        assert rt._current_response_format["type"] == "json_schema"

    def test_json_schema_added_to_existing_functions(self):
        cfg = ProxyConfig()
        rt = RequestTransformer(cfg, logger=logger)

        data = {
            "messages": [{"role": "user", "content": "test"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "parameters": {"type": "object"},
                    },
                }
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "result",
                    "schema": {"type": "object"},
                },
            },
        }

        out = rt.transform_chat_parameters(data)

        # Проверяем, что обе функции присутствуют
        assert len(out["functions"]) == 2
        names = [f["name"] for f in out["functions"]]
        assert "get_weather" in names
        assert "result" in names

    def test_text_response_format_passthrough(self):
        cfg = ProxyConfig()
        rt = RequestTransformer(cfg, logger=logger)

        data = {
            "messages": [{"role": "user", "content": "test"}],
            "response_format": {"type": "text"},
        }

        out = rt.transform_chat_parameters(data)

        assert out.get("response_format", {}).get("type") == "text"
        assert "functions" not in out
        assert rt._current_response_format is not None

    def test_no_response_format_clears_state(self):
        cfg = ProxyConfig()
        rt = RequestTransformer(cfg, logger=logger)

        # Сначала запрос с json_schema
        rt.transform_chat_parameters({
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "test", "schema": {}},
            }
        })
        assert rt._current_response_format is not None

        # Потом запрос без response_format
        rt.transform_chat_parameters({})
        assert rt._current_response_format is None


class TestResponseProcessorJsonSchema:
    """Тесты для ResponseProcessor с json_schema"""

    def test_json_schema_function_call_converted_to_content(self):
        rp = ResponseProcessor(logger)

        response_format = {
            "type": "json_schema",
            "json_schema": {"name": "user_info"},
        }

        # Синтетический ответ GigaChat с function_call от виртуальной функции
        giga_resp = SimpleNamespace(
            dict=lambda: {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "function_call": {
                                "name": "user_info",
                                "arguments": {"name": "John", "age": 30},
                            },
                        },
                        "finish_reason": "function_call",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            }
        )

        out = rp.process_response(
            giga_resp, gpt_model="gpt-4o", response_id="test123", response_format=response_format
        )

        choice = out["choices"][0]

        # Проверяем, что function_call преобразован в content
        assert "tool_calls" not in choice["message"]
        assert "function_call" not in choice["message"]
        assert choice["message"]["content"] == '{"name": "John", "age": 30}'
        assert choice["finish_reason"] == "stop"

    def test_regular_function_call_not_converted(self):
        rp = ResponseProcessor(logger)

        response_format = {
            "type": "json_schema",
            "json_schema": {"name": "user_info"},
        }

        # Ответ с другой функцией (не виртуальной)
        giga_resp = SimpleNamespace(
            dict=lambda: {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "function_call": {
                                "name": "get_weather",
                                "arguments": {"city": "Moscow"},
                            },
                        },
                        "finish_reason": "function_call",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            }
        )

        out = rp.process_response(
            giga_resp, gpt_model="gpt-4o", response_id="test123", response_format=response_format
        )

        choice = out["choices"][0]

        # Проверяем, что function_call остался как tool_call
        assert "tool_calls" in choice["message"]
        assert choice["message"]["tool_calls"][0]["function"]["name"] == "get_weather"
        assert choice["finish_reason"] == "tool_calls"

    def test_no_response_format_behaves_normally(self):
        rp = ResponseProcessor(logger)

        giga_resp = SimpleNamespace(
            dict=lambda: {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Hello!",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            }
        )

        out = rp.process_response(
            giga_resp, gpt_model="gpt-4o", response_id="test123", response_format=None
        )

        assert out["choices"][0]["message"]["content"] == "Hello!"


class TestStreamProcessorJsonSchema:
    """Тесты для streaming с json_schema"""

    def test_json_schema_stream_chunk_converted(self):
        rp = ResponseProcessor(logger)

        response_format = {
            "type": "json_schema",
            "json_schema": {"name": "result"},
        }

        giga_resp = SimpleNamespace(
            dict=lambda: {
                "choices": [
                    {
                        "delta": {
                            "role": "assistant",
                            "function_call": {
                                "name": "result",
                                "arguments": {"data": "test"},
                            },
                        },
                        "finish_reason": "function_call",
                    }
                ],
                "usage": None,
            }
        )

        out = rp.process_stream_chunk(
            giga_resp, gpt_model="gpt-4o", response_id="test123", response_format=response_format
        )

        choice = out["choices"][0]
        assert choice["delta"]["content"] == '{"data": "test"}'
        assert choice["finish_reason"] == "stop"
