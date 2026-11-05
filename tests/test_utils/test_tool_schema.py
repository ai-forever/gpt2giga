from copy import deepcopy

import pytest
from loguru import logger

from gpt2giga.models.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import RequestTransformer
from gpt2giga.common.tool_schema import normalize_tool_schema


@pytest.mark.parametrize("backend", ["v1", "v2"])
@pytest.mark.parametrize("field", ["tools", "functions"])
async def test_opt_in_tool_schema_normalization(backend, field):
    schema = {
        "type": "object",
        "properties": {
            "notify": {
                "anyOf": [
                    {"type": "boolean"},
                    {"type": "array", "items": {"type": "string"}},
                ]
            },
            "operations": {
                "type": "array",
                "items": {
                    "oneOf": [
                        {
                            "type": "object",
                            "properties": {
                                "op": {"type": "string", "enum": ["a"]},
                                "a": {"type": "string"},
                            },
                            "required": ["op", "a"],
                        },
                        {
                            "type": "object",
                            "properties": {
                                "op": {"type": "string", "enum": ["b"]},
                                "b": {"type": "number"},
                            },
                            "required": ["op", "b"],
                        },
                    ]
                },
            },
            "connector": {"anyOf": [{"type": "string"}, {"type": "object"}]},
            "nullable": {"type": ["null", "string"]},
            "arguments": {"type": "object"},
            "literal": {"type": "object", "default": {"anyOf": [1, 2]}},
        },
    }
    original = deepcopy(schema)
    fn = {"name": "example", "parameters": schema}
    data = {
        "model": "GigaChat-2",
        "messages": [{"role": "user", "content": "ok"}],
        field: [fn if field == "functions" else {"type": "function", "function": fn}],
    }
    for enabled in (False, True):
        config = ProxyConfig(proxy=ProxySettings(normalize_tool_schemas=enabled))
        transformer = RequestTransformer(config, logger)
        if backend == "v1":
            result = await transformer.prepare_chat(data)
            params = result["functions"][0].parameters.model_dump(
                by_alias=True, exclude_none=True
            )
        else:
            result = await transformer.prepare_chat_completion(data)
            params = result.tools[0].functions.specifications[0].parameters
        if not enabled:
            assert params == original
            continue
        props = params["properties"]
        assert props["notify"] == {"type": "boolean"}
        operation = props["operations"]["items"]
        assert operation["required"] == ["op"]
        assert operation["properties"]["op"]["enum"] == ["a", "b"]
        assert set(operation["properties"]) == {"op", "a", "b"}
        assert props["connector"] == {"type": "object", "properties": {}}
        assert props["nullable"] == {"type": "string"}
        assert props["arguments"] == {"type": "object", "properties": {}}
        assert props["literal"]["default"] == {"anyOf": [1, 2]}
    assert schema == original


def test_normalization_setting_from_environment(monkeypatch):
    monkeypatch.setenv("GPT2GIGA_NORMALIZE_TOOL_SCHEMAS", "true")
    assert ProxySettings().normalize_tool_schemas is True


@pytest.mark.parametrize(
    "schema, expected",
    [
        (
            {
                "anyOf": [{"type": "null"}, {"type": "integer"}, {"type": "string"}],
                "description": "Count",
            },
            {"type": "integer", "description": "Count"},
        ),
        ({"anyOf": [{"type": "null"}]}, {"anyOf": [{"type": "null"}]}),
        ({"oneOf": []}, {"oneOf": []}),
        ({"type": ["null"]}, {"type": "null"}),
        (
            {"$ref": "#/$defs/value", "$defs": {"value": {"type": ["string", "null"]}}},
            {"$ref": "#/$defs/value", "$defs": {"value": {"type": "string"}}},
        ),
        (
            {
                "type": "object",
                "properties": {"anyOf": {"type": "string"}, "type": {"type": "number"}},
                "examples": [{"oneOf": []}],
            },
            {
                "type": "object",
                "properties": {"anyOf": {"type": "string"}, "type": {"type": "number"}},
                "examples": [{"oneOf": []}],
            },
        ),
    ],
)
def test_schema_edge_cases(schema, expected):
    original = deepcopy(schema)
    assert normalize_tool_schema(schema) == expected
    assert schema == original


@pytest.mark.parametrize("backend", ["v1", "v2", "responses_v1", "responses_v2"])
@pytest.mark.parametrize(
    "requested, configured, pass_model, forced, normalized",
    [
        ("GigaChat-2", "GigaChat-3", True, None, True),
        ("GigaChat-2-Pro", None, True, None, True),
        ("GigaChat-2-Max", None, True, None, True),
        ("GigaChat-3", "GigaChat-2", True, None, False),
        ("GigaChat-3-Ultra", "GigaChat-2", True, None, False),
        ("GigaChat-20", None, True, None, False),
        ("custom-model", "GigaChat-2", True, None, False),
        (None, "GigaChat-2", True, None, True),
        (None, "GigaChat-3", True, None, False),
        (None, None, True, None, False),
        ("GigaChat-2", "GigaChat-3", False, None, False),
        ("GigaChat-3", "GigaChat-2", False, None, True),
        ("GigaChat-2", None, True, "GigaChat-3", False),
        ("GigaChat-3", None, True, "GigaChat-2", True),
    ],
)
async def test_normalization_uses_effective_model(
    backend, requested, configured, pass_model, forced, normalized
):
    from gpt2giga.models.config import GigaChatCLI

    if backend.startswith("responses") and forced:
        pytest.skip("Responses has no forced-model override")
    schema = {
        "type": "object",
        "properties": {"value": {"anyOf": [{"type": "string"}, {"type": "number"}]}},
    }
    config = ProxyConfig(
        proxy=ProxySettings(normalize_tool_schemas=True, pass_model=pass_model),
        gigachat=GigaChatCLI(model=configured),
    )
    transformer = RequestTransformer(config, logger)
    data = {
        "model": requested,
        "messages": [{"role": "user", "content": "ok"}],
        "input": "ok",
        "tools": [
            {
                "type": "function",
                "function": {"name": "example", "parameters": deepcopy(schema)},
            }
        ],
    }
    if backend.startswith("responses"):
        data["tools"] = [
            {"type": "function", "name": "example", "parameters": deepcopy(schema)}
        ]
        method = (
            transformer.prepare_response_chat
            if backend == "responses_v1"
            else transformer.prepare_response_chat_completion
        )
        result = await method(data)
    else:
        method = (
            transformer.prepare_chat
            if backend == "v1"
            else transformer.prepare_chat_completion
        )
        result = await method(data, forced_model=forced)
    if backend.endswith("v1"):
        actual = result["functions"][0].parameters.model_dump(
            by_alias=True, exclude_none=True
        )
    else:
        actual = result.tools[0].functions.specifications[0].parameters
    assert actual == (normalize_tool_schema(schema) if normalized else schema)
