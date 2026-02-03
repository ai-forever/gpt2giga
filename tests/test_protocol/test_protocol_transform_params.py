from loguru import logger

from gpt2giga.config import ProxyConfig, ProxySettings
from gpt2giga.protocol import RequestTransformer


def test_transform_chat_parameters_temperature_and_top_p():
    cfg = ProxyConfig()
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_chat_parameters({"temperature": 0, "model": "gpt-x"})
    # при temperature=0 должен быть top_p=0 и без model (pass_model False по умолчанию)
    assert out.get("top_p") == 0
    assert "model" not in out


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


def test_transform_common_parameters_pass_model_true():
    """Тест что model сохраняется при pass_model=True"""
    cfg = ProxyConfig(proxy=ProxySettings(pass_model=True))
    rt = RequestTransformer(cfg, logger=logger)
    out = rt.transform_chat_parameters({"model": "gpt-x"})
    assert out.get("model") == "gpt-x"


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
    assert "model" not in out
    assert "functions" in out


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
    cfg = ProxyConfig()
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


def test_transform_responses_parameters_text_json_schema():
    """Тест обработки text.format.json_schema в responses API"""
    cfg = ProxyConfig()
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


def test_resolve_schema_refs_nested_pydantic():
    """Тест разрешения $ref/$defs для вложенных Pydantic моделей"""
    # Схема с $ref и $defs (как генерирует Pydantic для вложенных моделей)
    schema_with_refs = {
        "$defs": {
            "Step": {
                "properties": {
                    "explanation": {"title": "Explanation", "type": "string"},
                    "output": {"title": "Output", "type": "string"},
                },
                "required": ["explanation", "output"],
                "title": "Step",
                "type": "object",
            }
        },
        "properties": {
            "steps": {
                "items": {"$ref": "#/$defs/Step"},
                "title": "Steps",
                "type": "array",
            },
            "final_answer": {"title": "Final Answer", "type": "string"},
        },
        "required": ["steps", "final_answer"],
        "title": "MathResponse",
        "type": "object",
    }

    resolved = RequestTransformer._resolve_schema_refs(schema_with_refs)

    # $defs должны быть удалены
    assert "$defs" not in resolved
    # $ref должен быть заменен на inline определение
    assert "$ref" not in resolved["properties"]["steps"]["items"]
    assert resolved["properties"]["steps"]["items"]["type"] == "object"
    assert "explanation" in resolved["properties"]["steps"]["items"]["properties"]
    assert "output" in resolved["properties"]["steps"]["items"]["properties"]


def test_resolve_schema_refs_no_refs():
    """Тест что схема без $ref не изменяется"""
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    resolved = RequestTransformer._resolve_schema_refs(schema)
    assert resolved == schema


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


def test_resolve_schema_refs_anyof_optional():
    """Тест разрешения anyOf для Optional типов (Pydantic)"""
    # Pydantic генерирует anyOf для Optional[List[X]]
    schema_with_anyof = {
        "$defs": {
            "SubStep": {
                "type": "object",
                "properties": {
                    "detail": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["detail", "confidence"],
            }
        },
        "type": "object",
        "properties": {
            "substeps": {
                "anyOf": [
                    {"items": {"$ref": "#/$defs/SubStep"}, "type": "array"},
                    {"type": "null"},
                ],
                "default": None,
                "title": "Substeps",
            }
        },
    }

    resolved = RequestTransformer._resolve_schema_refs(schema_with_anyof)

    # $defs должны быть удалены
    assert "$defs" not in resolved
    # anyOf должен быть заменен на первый не-null тип
    substeps = resolved["properties"]["substeps"]
    assert "anyOf" not in substeps
    assert substeps["type"] == "array"
    # $ref должен быть разрешен
    assert "$ref" not in substeps["items"]
    assert substeps["items"]["type"] == "object"
    # Сохраненные свойства
    assert substeps["default"] is None
    assert substeps["title"] == "Substeps"


def test_resolve_schema_refs_oneof():
    """Тест разрешения oneOf"""
    schema_with_oneof = {
        "type": "object",
        "properties": {
            "value": {
                "oneOf": [
                    {"type": "string"},
                    {"type": "null"},
                ],
                "title": "Value",
            }
        },
    }

    resolved = RequestTransformer._resolve_schema_refs(schema_with_oneof)

    # oneOf должен быть заменен на первый не-null тип
    value = resolved["properties"]["value"]
    assert "oneOf" not in value
    assert value["type"] == "string"
    assert value["title"] == "Value"
