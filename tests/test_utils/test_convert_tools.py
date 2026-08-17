from gigachat.models import Function

from gpt2giga.common.tools import (
    build_gigachat_builtin_tool_payload,
    iter_function_tool_payloads,
    normalize_gigachat_builtin_tool_type,
    split_gigachat_tool_name,
)


def test_iter_function_tool_payloads_preserves_native_schema():
    schema = {
        "$defs": {"value": {"type": ["string", "null"]}},
        "type": "object",
        "properties": {
            "value": {"$ref": "#/$defs/value"},
            "choice": {
                "anyOf": [{"type": "integer"}, {"type": "number"}],
                "enum": [1, 2.5, None],
            },
            "tuple": {
                "type": "array",
                "prefixItems": [{"type": "string"}],
                "items": False,
            },
        },
        "unevaluatedProperties": False,
    }
    data = {
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "native_schema",
                    "description": "Preserve the schema.",
                    "parameters": schema,
                },
            }
        ]
    }

    [payload] = list(iter_function_tool_payloads(data))

    assert payload["parameters"] == schema


def test_gigachat_function_model_preserves_native_schema():
    schema = {
        "anyOf": [
            {"type": "object", "properties": {"city": {"type": "string"}}},
            {"type": "object", "properties": {"lat": {"type": "number"}}},
        ],
        "x-provider-keyword": {"enabled": True},
    }

    function = Function.model_validate(
        {"name": "lookup", "description": None, "parameters": schema}
    )

    assert function.parameters.model_dump(by_alias=True, exclude_none=True) == schema


def test_iter_function_tool_payloads_keeps_empty_schema_empty():
    data = {
        "functions": [
            {
                "name": "no_args",
                "description": "No arguments.",
                "parameters": {},
            }
        ]
    }

    [payload] = list(iter_function_tool_payloads(data))

    assert payload["parameters"] == {}


def test_iter_function_tool_payloads_flattens_namespace_tools():
    data = {
        "tools": [
            {
                "type": "namespace",
                "name": "mcp__playwright",
                "tools": [
                    {
                        "type": "function",
                        "name": "browser_navigate",
                        "description": "Navigate",
                        "parameters": {
                            "type": "object",
                            "properties": {"url": {"type": "string"}},
                        },
                    }
                ],
            }
        ]
    }

    [payload] = list(iter_function_tool_payloads(data))

    assert payload["name"] == "mcp__playwright__browser_navigate"
    assert split_gigachat_tool_name(
        payload["name"],
        request_tools=data["tools"],
    ) == ("browser_navigate", "mcp__playwright")


def test_iter_function_tool_payloads_skips_non_functions():
    data = {
        "tools": [
            {"type": "web_search_preview", "parameters": {"type": "object"}},
            {
                "type": "custom",
                "name": "apply_patch",
                "format": {"type": "grammar", "syntax": "lark"},
            },
            {"type": "function", "function": {"name": "missing_parameters"}},
            {
                "type": "function",
                "function": {"name": "valid", "parameters": {}},
            },
        ]
    }

    assert [payload["name"] for payload in iter_function_tool_payloads(data)] == [
        "valid"
    ]


def test_normalize_gigachat_builtin_tool_type_maps_provider_aliases():
    cases = {
        "web_search_preview": "web_search",
        "web_search_2025_08_26": "web_search",
        "code_execution_20250825": "code_interpreter",
        "codeExecution": "code_interpreter",
        "googleSearch": "web_search",
        "googleSearchRetrieval": "web_search",
        "urlContext": "url_content_extraction",
        "image_generation": "image_generate",
        "model_3d_generate": "model_3d_generate",
    }

    assert {
        tool_type: normalize_gigachat_builtin_tool_type(tool_type)
        for tool_type in cases
    } == cases


def test_build_gigachat_builtin_tool_payload_maps_gemini_alias_config():
    payload = build_gigachat_builtin_tool_payload(
        {
            "type": "urlContext",
            "urlContext": {"max_uses": 2},
            "name": "url_context",
        }
    )

    assert payload == {"url_content_extraction": {"max_uses": 2}}
