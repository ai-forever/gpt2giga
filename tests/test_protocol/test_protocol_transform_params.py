import pytest
from loguru import logger

from gpt2giga.common.client_params import ClientCompatibilityError, ClientParamStatus
from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import RequestTransformer
from gpt2giga.protocol.request.params import (
    classify_openai_chat_parameter,
    classify_openai_responses_parameter,
)


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
            "extra_body": {"custom_flag": "on"},
        }
    )
    assert out.get("additional_fields") == {"custom_flag": "on"}
    assert "extra_body" not in out


def test_transform_common_parameters_merges_extra_body_with_additional_fields():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_chat_parameters(
        {
            "model": "gpt-x",
            "extra_body": {"temperature": 0.2, "custom_flag": "from-extra-body"},
            "additional_fields": {"custom_flag": "from-additional-fields"},
        }
    )
    assert out.get("additional_fields") == {
        "temperature": 0.2,
        "custom_flag": "from-additional-fields",
    }
    assert "extra_body" not in out


def test_transform_common_parameters_leaves_sdk_style_extra_fields_top_level():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_chat_parameters(
        {"model": "gpt-x", "messages": [], "profanity_check": False}
    )

    assert out.get("profanity_check") is False
    assert "additional_fields" not in out


def test_transform_chat_parameters_does_not_map_max_completion_tokens_yet():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_chat_parameters({"model": "gpt-x", "max_completion_tokens": 128})

    assert out.get("max_completion_tokens") == 128
    assert "max_tokens" not in out


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


def test_transform_responses_parameters_maps_reasoning_object_to_reasoning_effort():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_responses_parameters(
        {"model": "gpt-x", "reasoning": {"effort": "high"}}
    )
    assert out.get("reasoning_effort") == "high"
    assert "reasoning" not in out


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
        "schema": {"type": "object"},
        "strict": True,
    }
    assert "functions" not in out
    assert "function_call" not in out


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
        "schema": {"type": "object"},
    }
    assert out["functions"] == [{"name": "sum"}]
    assert "function_call" not in out


def test_openai_parameter_classifier_marks_known_states():
    assert classify_openai_chat_parameter("messages") == ClientParamStatus.SUPPORTED
    assert classify_openai_chat_parameter("user") == ClientParamStatus.ACCEPTED_IGNORED
    assert classify_openai_chat_parameter("profanity_check") == (
        ClientParamStatus.SUPPORTED
    )
    assert classify_openai_chat_parameter("logprobs") == ClientParamStatus.REJECTED
    assert classify_openai_responses_parameter("input") == ClientParamStatus.SUPPORTED
    assert classify_openai_responses_parameter("include") == ClientParamStatus.REJECTED
    assert classify_openai_responses_parameter("previous_response_id") == (
        ClientParamStatus.REJECTED
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
        ({"unknown_param": "value"}, "unknown_param"),
    ],
)
def test_transform_chat_parameters_rejects_unsupported_openai_params(body, param):
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    with pytest.raises(ClientCompatibilityError) as exc_info:
        rt.transform_chat_parameters({"model": "gpt-x", **body})

    assert exc_info.value.provider == "openai"
    assert exc_info.value.param == param
    assert exc_info.value.status_code == 400


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


def test_transform_chat_parameters_rejects_store_true():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    with pytest.raises(ClientCompatibilityError) as exc_info:
        rt.transform_chat_parameters({"model": "gpt-x", "store": True})

    assert exc_info.value.param == "store"


def test_transform_chat_parameters_rejects_builtin_tools():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    with pytest.raises(ClientCompatibilityError) as exc_info:
        rt.transform_chat_parameters(
            {"model": "gpt-x", "tools": [{"type": "web_search"}]}
        )

    assert exc_info.value.param == "tools"
    assert "Only function tools" in exc_info.value.message


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


def test_transform_responses_parameters_rejects_stateful_params():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    with pytest.raises(ClientCompatibilityError) as exc_info:
        rt.transform_responses_parameters(
            {
                "model": "gpt-x",
                "input": "hello",
                "previous_response_id": "resp_1",
            }
        )

    assert exc_info.value.param == "previous_response_id"


@pytest.mark.parametrize("param", ["include", "max_tool_calls", "truncation"])
def test_transform_responses_parameters_rejects_unsupported_controls(param):
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)

    with pytest.raises(ClientCompatibilityError) as exc_info:
        rt.transform_responses_parameters(
            {
                "model": "gpt-x",
                "input": "hello",
                param: ["foo"] if param == "include" else "auto",
            }
        )

    assert exc_info.value.param == param


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
        "schema": {"type": "object"},
        "strict": True,
    }
    assert "functions" not in out
    assert "function_call" not in out


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
