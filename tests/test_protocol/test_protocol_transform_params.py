import pytest
from gigachat.models import Function, FunctionParameters
from loguru import logger

from gpt2giga.common.client_params import ClientCompatibilityError, ClientParamStatus
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import RequestTransformer
from gpt2giga.protocol.request.params import (
    classify_openai_chat_parameter,
    classify_openai_responses_parameter,
)


@pytest.fixture(autouse=True)
def _clear_pass_model_env(monkeypatch):
    monkeypatch.delenv("GPT2GIGA_PASS_MODEL", raising=False)
    monkeypatch.delenv("GPT2GIGA_DEFAULT_MAX_TOKENS", raising=False)
    monkeypatch.delenv("GPT2GIGA_DISABLE_REASONING", raising=False)


def test_transform_chat_parameters_temperature_and_top_p():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_chat_parameters({"temperature": 0, "model": "gpt-x"})
    # при temperature=0 должен быть top_p=0, model сохраняется по умолчанию
    assert out.get("top_p") == 0
    assert out.get("model") == "gpt-x"


def test_transform_chat_parameters_max_tokens_and_tools():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    data = {
        "max_output_tokens": 128,
        "tools": [
            {"type": "function", "function": {"name": "sum", "parameters": {}}},
            {"type": "function", "name": "alt", "parameters": {}},
        ],
    }
    out = rt.transform_chat_parameters(data)
    assert out.get("max_tokens") == 128
    assert "functions" in out and len(out["functions"]) == 2


def test_transform_chat_parameters_keeps_sdk_function_models():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    out = rt.transform_chat_parameters(
        {
            "model": "gpt-x",
            "functions": [
                Function(
                    name="get_weather",
                    parameters=FunctionParameters(
                        type="object",
                        properties={"city": {"type": "string"}},
                        required=["city"],
                    ),
                )
            ],
        }
    )

    assert out["functions"] == [
        {
            "name": "get_weather",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string", "description": ""}},
                "required": ["city"],
            },
        }
    ]


def test_transform_common_parameters_positive_temperature():
    """Тест что положительная temperature сохраняется"""
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_chat_parameters({"temperature": 0.7, "model": "gpt-x"})
    assert out.get("temperature") == 0.7
    assert "top_p" not in out


def test_transform_common_parameters_without_temperature_does_not_add_top_p():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_chat_parameters({"model": "gpt-x"})
    assert "top_p" not in out


def test_transform_chat_parameters_omits_unset_default_max_tokens():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    out = rt.transform_chat_parameters({"model": "gpt-x"})

    assert "max_tokens" not in out


def test_transform_chat_parameters_applies_configured_default_max_tokens():
    cfg = ProxyConfig(proxy=ProxySettings(default_max_tokens=128000))
    rt = RequestTransformer(cfg, logger=logger)

    out = rt.transform_chat_parameters({"model": "gpt-x"})

    assert out.get("max_tokens") == 128000


def test_transform_common_parameters_preserves_explicit_top_p_without_temperature():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_chat_parameters({"model": "gpt-x", "top_p": 0.9})
    assert out.get("top_p") == 0.9


def test_transform_common_parameters_pass_model_true():
    """Тест что model сохраняется при pass_model=True"""
    cfg = ProxyConfig(proxy=ProxySettings(pass_model=True))
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_chat_parameters({"model": "gpt-x"})
    assert out.get("model") == "gpt-x"


def test_transform_common_parameters_pass_model_false():
    """Тест что model удаляется при pass_model=False."""
    cfg = ProxyConfig(proxy=ProxySettings(pass_model=False))
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_chat_parameters({"model": "gpt-x"})
    assert "model" not in out


def test_transform_chat_parameters_maps_extra_body_to_additional_fields():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_chat_parameters(
        {"model": "gpt-x", "extra_body": {"profanity_check": False}}
    )
    assert out.get("additional_fields") == {"profanity_check": False}
    assert "extra_body" not in out


def test_transform_responses_parameters_maps_extra_body_to_additional_fields():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_responses_parameters(
        {
            "model": "gpt-x",
            "input": "hello",
            "extra_body": {"profanity_check": False},
        }
    )
    assert out.get("additional_fields") == {"profanity_check": False}
    assert "extra_body" not in out


def test_transform_responses_parameters_accepts_flat_forced_function_tool_choice():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_responses_parameters(
        {
            "model": "gpt-x",
            "input": "hello",
            "tools": [
                {
                    "type": "function",
                    "name": "lookup",
                    "parameters": {"type": "object", "properties": {}},
                }
            ],
            "tool_choice": {"type": "function", "name": "lookup"},
        }
    )

    assert out["function_call"] == {"name": "lookup"}


def test_transform_responses_parameters_ignores_builtin_tools_in_v1_mode():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    out = rt.transform_responses_parameters(
        {
            "model": "gpt-x",
            "input": "search",
            "tools": [{"type": "web_search"}],
        }
    )

    assert "tools" not in out
    assert "functions" not in out


def test_transform_responses_parameters_accepts_builtin_tools_in_v2_mode():
    cfg = ProxyConfig(proxy=ProxySettings(gigachat_api_mode="v2"))
    rt = RequestTransformer(cfg, logger=logger)

    out = rt.transform_responses_parameters(
        {
            "model": "gpt-x",
            "input": "search",
            "tools": [
                {
                    "type": "web_search_preview",
                    "indexes": ["web"],
                    "flags": ["trusted"],
                },
                {
                    "type": "image_generation",
                    "size": "1024x1024",
                },
            ],
            "tool_choice": {"type": "web_search_preview"},
        }
    )

    assert out["_gpt2giga_builtin_tools"] == [
        {"web_search": {"indexes": ["web"], "flags": ["trusted"]}},
        {"image_generate": {"size": "1024x1024"}},
    ]
    assert out["_gpt2giga_tool_config"] == {
        "mode": "tool",
        "tool_name": "web_search",
    }


def test_transform_common_parameters_merges_extra_body_with_additional_fields():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_chat_parameters(
        {
            "model": "gpt-x",
            "extra_body": {
                "profanity_check": False,
                "repetition_penalty": 1.1,
            },
            "additional_fields": {"profanity_check": True},
        }
    )
    assert out.get("additional_fields") == {
        "profanity_check": True,
        "repetition_penalty": 1.1,
    }
    assert "extra_body" not in out


def test_transform_common_parameters_maps_sdk_style_extra_fields_to_additional_fields():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_chat_parameters(
        {"model": "gpt-x", "messages": [], "profanity_check": False}
    )

    assert out.get("additional_fields") == {"profanity_check": False}
    assert "profanity_check" not in out


def test_transform_common_parameters_maps_unknown_sdk_style_extra_to_additional_fields():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_chat_parameters(
        {"model": "gpt-x", "messages": [], "custom_flag": "on"}
    )

    assert out.get("additional_fields") == {"custom_flag": "on"}
    assert "custom_flag" not in out


def test_transform_common_parameters_merges_sdk_and_literal_extra_body():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_chat_parameters(
        {
            "model": "gpt-x",
            "profanity_check": True,
            "extra_body": {
                "profanity_check": False,
                "repetition_penalty": 1.2,
            },
        }
    )

    assert out.get("additional_fields") == {
        "profanity_check": False,
        "repetition_penalty": 1.2,
    }


def test_transform_common_parameters_accepts_custom_extra_body():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    out = rt.transform_chat_parameters(
        {"model": "gpt-x", "extra_body": {"custom_flag": "on"}}
    )

    assert out.get("additional_fields") == {"custom_flag": "on"}


def test_transform_common_parameters_rejects_non_object_extra_body():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    with pytest.raises(ClientCompatibilityError) as exc_info:
        rt.transform_chat_parameters(
            {"model": "gpt-x", "extra_body": ["not", "an", "object"]}
        )

    assert exc_info.value.param == "extra_body"


def test_transform_chat_parameters_maps_max_completion_tokens():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_chat_parameters({"model": "gpt-x", "max_completion_tokens": 128})

    assert out.get("max_tokens") == 128
    assert "max_completion_tokens" not in out


@pytest.mark.parametrize("conflict_param", ["max_tokens", "max_output_tokens"])
def test_transform_chat_parameters_ignores_conflicting_max_completion_tokens(
    conflict_param,
):
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    out = rt.transform_chat_parameters(
        {
            "model": "gpt-x",
            "max_completion_tokens": 128,
            conflict_param: 64,
        }
    )

    assert out["max_tokens"] == 64
    assert "max_completion_tokens" not in out


def test_transform_common_parameters_drops_extra_headers_and_extra_query():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_chat_parameters(
        {
            "model": "gpt-x",
            "extra_headers": {"x-me": "kus"},
            "extra_query": {"beta": "true"},
        }
    )
    assert "extra_headers" not in out
    assert "extra_query" not in out


def test_transform_responses_parameters_uses_common():
    """Тест что transform_responses_parameters использует общую логику"""
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    data = {
        "temperature": 0.5,
        "max_output_tokens": 256,
        "model": "gpt-y",
        "tools": [
            {"type": "function", "function": {"name": "fn", "parameters": {}}},
        ],
    }
    out = rt.transform_responses_parameters(data)
    assert out.get("temperature") == 0.5
    assert out.get("max_tokens") == 256
    assert out.get("model") == "gpt-y"
    assert "functions" in out


def test_enable_reasoning_adds_reasoning_effort_high_by_default():
    cfg = ProxyConfig(proxy=ProxySettings(enable_reasoning=True))
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_chat_parameters({"model": "gpt-x"})
    assert out.get("reasoning_effort") == "high"


def test_enable_reasoning_does_not_override_explicit_reasoning_effort():
    cfg = ProxyConfig(proxy=ProxySettings(enable_reasoning=True))
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_chat_parameters({"model": "gpt-x", "reasoning_effort": "low"})
    assert out.get("reasoning_effort") == "low"


def test_disable_reasoning_removes_explicit_and_default_reasoning():
    cfg = ProxyConfig(
        proxy=ProxySettings(enable_reasoning=True, disable_reasoning=True)
    )
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_chat_parameters(
        {
            "model": "gpt-x",
            "reasoning": {"effort": "high"},
            "reasoning_effort": "low",
        }
    )
    assert "reasoning" not in out
    assert "reasoning_effort" not in out


def test_transform_responses_parameters_maps_reasoning_object_to_reasoning_effort():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_responses_parameters(
        {"model": "gpt-x", "reasoning": {"effort": "high"}}
    )
    assert out.get("reasoning_effort") == "high"
    assert "reasoning" not in out


def test_disable_reasoning_removes_responses_reasoning_object():
    cfg = ProxyConfig(proxy=ProxySettings(disable_reasoning=True))
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_responses_parameters(
        {"model": "gpt-x", "reasoning": {"effort": "high"}}
    )
    assert "reasoning" not in out
    assert "reasoning_effort" not in out


def test_disable_reasoning_strips_reasoning_from_additional_fields():
    cfg = ProxyConfig(proxy=ProxySettings(disable_reasoning=True))
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_chat_parameters(
        {
            "model": "gpt-x",
            "extra_body": {
                "model_options": {
                    "reasoning": {"effort": "high"},
                    "top_p": 0.2,
                },
                "profanity_check": False,
                "reasoning": {"effort": "high"},
            },
            "additional_fields": {
                "reasoning_effort": "low",
                "storage": True,
            },
        }
    )
    assert out.get("additional_fields") == {
        "model_options": {"top_p": 0.2},
        "profanity_check": False,
        "storage": True,
    }


def test_apply_json_schema_as_function():
    """Тест метода _apply_json_schema_as_function"""
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    transformed = {}
    rt._apply_json_schema_as_function(
        transformed,
        schema_name="TestSchema",
        schema={"type": "object", "properties": {"name": {"type": "string"}}},
    )
    assert "functions" in transformed
    assert len(transformed["functions"]) == 1
    assert transformed["functions"][0]["name"] == "TestSchema"
    assert transformed["function_call"] == {"name": "TestSchema"}


def test_transform_chat_parameters_json_schema_response_format():
    """Тест обработки response_format с json_schema"""
    cfg = ProxyConfig(proxy=ProxySettings(structured_output_mode="function_call"))
    rt = RequestTransformer(cfg, logger=logger)
    data = {
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "OutputFormat",
                "schema": {"type": "object"},
            },
        }
    }
    out = rt.transform_chat_parameters(data)
    assert "functions" in out
    assert out["functions"][0]["name"] == "OutputFormat"
    assert out["function_call"] == {"name": "OutputFormat"}


def test_transform_chat_parameters_json_schema_native_response_format():
    """Native SO forwards response_format to GigaChat without synthetic functions."""
    cfg = ProxyConfig(proxy=ProxySettings(structured_output_mode="native"))
    rt = RequestTransformer(cfg, logger=logger)
    data = {
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "OutputFormat",
                "schema": {"type": "object"},
                "strict": True,
            },
        }
    }
    out = rt.transform_chat_parameters(data)
    assert out["response_format"] == {
        "type": "json_schema",
        "schema": {"type": "object", "properties": {}},
        "strict": True,
    }
    assert "functions" not in out
    assert "function_call" not in out


def test_transform_chat_parameters_rejects_json_object_response_format():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    with pytest.raises(ClientCompatibilityError) as exc_info:
        rt.transform_chat_parameters(
            {
                "model": "GigaChat-2-Max",
                "messages": [{"role": "user", "content": "return json"}],
                "response_format": {"type": "json_object"},
            }
        )

    assert exc_info.value.param == "response_format.type"
    assert exc_info.value.code == "unsupported_response_format"


def test_transform_chat_parameters_native_keeps_user_tools_as_functions():
    """Native SO should not disable normal OpenAI tools conversion."""
    cfg = ProxyConfig(proxy=ProxySettings(structured_output_mode="native"))
    rt = RequestTransformer(cfg, logger=logger)
    data = {
        "response_format": {
            "type": "json_schema",
            "json_schema": {"schema": {"type": "object"}},
        },
        "tools": [{"type": "function", "function": {"name": "sum"}}],
    }
    out = rt.transform_chat_parameters(data)
    assert out["response_format"] == {
        "type": "json_schema",
        "schema": {"type": "object", "properties": {}},
    }
    assert out["functions"] == [{"name": "sum"}]
    assert "function_call" not in out


def test_openai_parameter_classifier_marks_known_states():
    assert classify_openai_chat_parameter("messages") == ClientParamStatus.SUPPORTED
    assert classify_openai_chat_parameter("user") == ClientParamStatus.ACCEPTED_IGNORED
    assert classify_openai_chat_parameter("profanity_check") == (
        ClientParamStatus.SUPPORTED
    )
    assert classify_openai_chat_parameter("logprobs") == (
        ClientParamStatus.ACCEPTED_IGNORED
    )
    assert classify_openai_chat_parameter("custom_flag") == ClientParamStatus.SUPPORTED
    assert classify_openai_responses_parameter("input") == ClientParamStatus.SUPPORTED
    assert classify_openai_responses_parameter("include") == (
        ClientParamStatus.ACCEPTED_IGNORED
    )
    assert classify_openai_responses_parameter("previous_response_id") == (
        ClientParamStatus.ACCEPTED_IGNORED
    )


@pytest.mark.parametrize(
    ("body", "param"),
    [
        ({"logprobs": True}, "logprobs"),
        ({"top_logprobs": 2}, "top_logprobs"),
        ({"modalities": ["text", "audio"]}, "modalities"),
        ({"audio": {"voice": "alloy"}}, "audio"),
        ({"prediction": {"type": "content", "content": "hi"}}, "prediction"),
        ({"n": 2}, "n"),
        ({"parallel_tool_calls": True}, "parallel_tool_calls"),
        ({"web_search_options": {"search_context_size": "low"}}, "web_search_options"),
    ],
)
def test_transform_chat_parameters_ignores_unsupported_openai_params(body, param):
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    out = rt.transform_chat_parameters({"model": "gpt-x", **body})

    assert param not in out


def test_transform_chat_parameters_ignores_metadata_params_and_n_one():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_chat_parameters(
        {
            "model": "gpt-x",
            "messages": [],
            "metadata": {"trace": "local"},
            "user": "user-1",
            "service_tier": "auto",
            "n": 1,
            "store": False,
            "modalities": ["text"],
            "parallel_tool_calls": False,
        }
    )

    assert "metadata" not in out
    assert "user" not in out
    assert "service_tier" not in out
    assert "n" not in out
    assert "store" not in out
    assert "modalities" not in out
    assert "parallel_tool_calls" not in out


def test_transform_chat_parameters_ignores_store_true():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    out = rt.transform_chat_parameters({"model": "gpt-x", "store": True})

    assert "store" not in out


def test_transform_chat_parameters_ignores_builtin_tools_in_v1_mode():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    out = rt.transform_chat_parameters(
        {"model": "gpt-x", "tools": [{"type": "web_search"}]}
    )

    assert "tools" not in out
    assert "functions" not in out


def test_transform_chat_parameters_ignores_namespace_tools_in_v1_mode():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    out = rt.transform_chat_parameters(
        {
            "model": "gpt-x",
            "tools": [
                {
                    "type": "namespace",
                    "name": "mcp__playwright",
                    "tools": [
                        {
                            "type": "function",
                            "name": "browser_navigate",
                            "parameters": {"type": "object"},
                        }
                    ],
                }
            ],
        }
    )

    assert "tools" not in out
    assert "functions" not in out


def test_transform_responses_parameters_accepts_namespace_tools():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    out = rt.transform_responses_parameters(
        {
            "model": "gpt-x",
            "input": "open",
            "tools": [
                {
                    "type": "namespace",
                    "name": "mcp__playwright",
                    "tools": [
                        {
                            "type": "function",
                            "name": "browser_navigate",
                            "parameters": {"type": "object"},
                        }
                    ],
                }
            ],
        }
    )

    assert out["functions"][0]["name"] == "mcp__playwright__browser_navigate"


def test_transform_responses_parameters_accepts_input_schema_tools():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    out = rt.transform_responses_parameters(
        {
            "model": "gpt-x",
            "input": "run",
            "tools": [
                {
                    "name": "Bash",
                    "description": "Run shell command.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"command": {"type": "string"}},
                    },
                }
            ],
        }
    )

    assert out["functions"][0]["name"] == "Bash"
    assert out["functions"][0]["parameters"]["properties"]["command"]["type"] == (
        "string"
    )


def test_transform_chat_parameters_applies_tool_choice_policy():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    forced = rt.transform_chat_parameters(
        {
            "model": "gpt-x",
            "tools": [
                {
                    "type": "function",
                    "function": {"name": "sum", "parameters": {}},
                }
            ],
            "tool_choice": {"type": "function", "function": {"name": "sum"}},
        }
    )
    none = rt.transform_chat_parameters(
        {
            "model": "gpt-x",
            "tools": [
                {
                    "type": "function",
                    "function": {"name": "sum", "parameters": {}},
                }
            ],
            "tool_choice": "none",
        }
    )

    assert forced["function_call"] == {"name": "sum"}
    assert "tool_choice" not in forced
    assert "tools" not in none
    assert "functions" not in none


def test_transform_responses_parameters_ignores_stateful_params_in_v1_mode():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    out = rt.transform_responses_parameters(
        {
            "model": "gpt-x",
            "input": "hello",
            "previous_response_id": "resp_1",
        }
    )

    assert "previous_response_id" not in out


def test_transform_responses_parameters_allows_stateful_params_in_v2_mode():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    out = rt.transform_responses_parameters(
        {
            "model": "gpt-x",
            "input": "hello",
            "previous_response_id": "resp_1",
            "store": True,
        },
        allow_builtin_tools=True,
    )

    assert out["previous_response_id"] == "resp_1"
    assert out["store"] is True


@pytest.mark.parametrize("param", ["max_tool_calls", "truncation"])
def test_transform_responses_parameters_ignores_unsupported_controls(param):
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    out = rt.transform_responses_parameters(
        {
            "model": "gpt-x",
            "input": "hello",
            param: "auto",
        }
    )

    assert param not in out


def test_transform_responses_parameters_ignores_include():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    out = rt.transform_responses_parameters(
        {
            "model": "gpt-x",
            "input": "hello",
            "include": ["reasoning.encrypted_content"],
        }
    )

    assert "include" not in out


def test_transform_responses_parameters_text_json_schema():
    """Тест обработки text.format.json_schema в responses API"""
    cfg = ProxyConfig(proxy=ProxySettings(structured_output_mode="function_call"))
    rt = RequestTransformer(cfg, logger=logger)
    data = {
        "text": {
            "format": {
                "type": "json_schema",
                "name": "ResponseSchema",
                "schema": {"type": "object"},
            }
        }
    }
    out = rt.transform_responses_parameters(data)
    assert "functions" in out
    assert out["functions"][0]["name"] == "ResponseSchema"
    assert out["function_call"] == {"name": "ResponseSchema"}


def test_transform_responses_parameters_text_json_schema_native():
    """Native SO maps Responses API text.format to GigaChat response_format."""
    cfg = ProxyConfig(proxy=ProxySettings(structured_output_mode="native"))
    rt = RequestTransformer(cfg, logger=logger)
    data = {
        "text": {
            "format": {
                "type": "json_schema",
                "name": "ResponseSchema",
                "schema": {"type": "object"},
                "strict": True,
            }
        }
    }
    out = rt.transform_responses_parameters(data)
    assert out["response_format"] == {
        "type": "json_schema",
        "schema": {"type": "object", "properties": {}},
        "strict": True,
    }
    assert "functions" not in out
    assert "function_call" not in out


def test_transform_responses_parameters_rejects_json_object_response_format():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    with pytest.raises(ClientCompatibilityError) as exc_info:
        rt.transform_responses_parameters(
            {
                "model": "GigaChat-2-Max",
                "input": "return json",
                "text": {"format": {"type": "json_object"}},
            }
        )

    assert exc_info.value.param == "text.format.type"
    assert exc_info.value.code == "unsupported_response_format"


def test_apply_json_schema_resolves_refs():
    """Тест что _apply_json_schema_as_function разрешает $ref"""
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    transformed = {}

    schema_with_refs = {
        "$defs": {
            "Item": {
                "type": "object",
                "properties": {"value": {"type": "integer"}},
            }
        },
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {"$ref": "#/$defs/Item"},
            }
        },
    }

    rt._apply_json_schema_as_function(
        transformed, schema_name="TestSchema", schema=schema_with_refs
    )

    params = transformed["functions"][0]["parameters"]
    # Проверяем, что $defs удален и $ref разрешен
    assert "$defs" not in params
    assert "$ref" not in params["properties"]["items"]["items"]
    assert params["properties"]["items"]["items"]["type"] == "object"
