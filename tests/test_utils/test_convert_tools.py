from gpt2giga.utils import convert_tool_to_giga_functions, normalize_json_schema


def test_normalize_json_schema_adds_properties_to_object():
    """Тест: добавляет properties к объекту без properties"""
    schema = {"type": "object"}
    result = normalize_json_schema(schema)
    assert result == {"type": "object", "properties": {}}


def test_normalize_json_schema_nested_object():
    """Тест: рекурсивно добавляет properties к вложенным объектам"""
    schema = {
        "type": "object",
        "properties": {
            "glob": {"type": "object"},  # нет properties
            "name": {"type": "string"},
        },
    }
    result = normalize_json_schema(schema)
    assert result["properties"]["glob"] == {"type": "object", "properties": {}}
    assert result["properties"]["name"] == {"type": "string"}


def test_normalize_json_schema_array_items():
    """Тест: обрабатывает items в массивах"""
    schema = {
        "type": "array",
        "items": {"type": "object"},
    }
    result = normalize_json_schema(schema)
    assert result["items"] == {"type": "object", "properties": {}}


def test_normalize_json_schema_anyof():
    """Тест: anyOf разворачивается в первый тип (GigaChat SDK не поддерживает anyOf)"""
    schema = {
        "anyOf": [
            {"type": "object"},
            {"type": "string"},
        ]
    }
    result = normalize_json_schema(schema)
    # anyOf удаляется, берётся первый тип (object с properties)
    assert "anyOf" not in result
    assert result["type"] == "object"
    assert result["properties"] == {}


def test_normalize_json_schema_preserves_existing_properties():
    """Тест: не перезаписывает существующие properties"""
    schema = {
        "type": "object",
        "properties": {"foo": {"type": "string"}},
    }
    result = normalize_json_schema(schema)
    assert result["properties"]["foo"] == {"type": "string"}


def test_normalize_json_schema_removes_null_from_anyof():
    """Тест: удаляет type: null из anyOf и разворачивает единственный оставшийся тип"""
    schema = {
        "anyOf": [
            {"type": "string"},
            {"type": "null"},
        ],
        "default": None,
        "description": "Optional string parameter",
    }
    result = normalize_json_schema(schema)
    # anyOf должен быть удален, тип должен быть развернут
    assert "anyOf" not in result
    assert result["type"] == "string"
    # description и default должны сохраниться
    assert result["description"] == "Optional string parameter"
    assert result["default"] is None


def test_normalize_json_schema_removes_null_from_oneof():
    """Тест: удаляет type: null из oneOf"""
    schema = {
        "oneOf": [
            {"type": "integer"},
            {"type": "null"},
        ],
    }
    result = normalize_json_schema(schema)
    assert "oneOf" not in result
    assert result["type"] == "integer"


def test_normalize_json_schema_anyof_multiple_non_null():
    """Тест: если после удаления null остается несколько типов, берём первый
    (GigaChat SDK не поддерживает anyOf)"""
    schema = {
        "anyOf": [
            {"type": "string"},
            {"type": "integer"},
            {"type": "null"},
        ],
    }
    result = normalize_json_schema(schema)
    # anyOf удаляется, берётся первый не-null тип
    assert "anyOf" not in result
    assert result["type"] == "string"


def test_normalize_json_schema_nested_anyof_with_null():
    """Тест: обрабатывает вложенные anyOf с null в properties"""
    schema = {
        "type": "object",
        "properties": {
            "glob": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "null"},
                ],
                "default": None,
                "description": "Glob pattern",
            }
        },
    }
    result = normalize_json_schema(schema)
    glob_param = result["properties"]["glob"]
    assert "anyOf" not in glob_param
    assert glob_param["type"] == "string"
    assert glob_param["description"] == "Glob pattern"
    assert glob_param["default"] is None


def test_normalize_json_schema_anyof_with_object_adds_properties():
    """Тест: когда anyOf содержит object, он получает properties"""
    schema = {
        "anyOf": [
            {"additionalProperties": True, "type": "object"},
            {"type": "null"},
        ],
        "default": None,
        "description": "Data object",
    }
    result = normalize_json_schema(schema)
    assert "anyOf" not in result
    assert result["type"] == "object"
    assert result["properties"] == {}
    assert result["description"] == "Data object"


def test_normalize_json_schema_anyof_string_or_object():
    """Тест: anyOf с string и object берёт первый тип (string)"""
    schema = {
        "anyOf": [
            {"type": "string"},
            {"additionalProperties": True, "type": "object"},
            {"type": "null"},
        ],
        "default": None,
    }
    result = normalize_json_schema(schema)
    assert "anyOf" not in result
    assert result["type"] == "string"
    # string не требует properties
    assert "properties" not in result


def test_convert_tool_with_nested_object_without_properties():
    """Тест: convert_tool_to_giga_functions нормализует схемы с вложенными объектами без properties"""
    data = {
        "tools": [
            {
                "function": {
                    "name": "glob_search",
                    "description": "Search files with glob pattern",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "glob": {
                                "type": "object",  # Нет properties - должно быть нормализовано
                                "description": "Glob options",
                            }
                        },
                    },
                }
            }
        ]
    }
    out = convert_tool_to_giga_functions(data)
    assert len(out) == 1
    # Проверяем что properties добавлены к glob
    params = (
        out[0].parameters.model_dump()
        if hasattr(out[0].parameters, "model_dump")
        else dict(out[0].parameters)
    )
    assert "properties" in params["properties"]["glob"]
    assert params["properties"]["glob"]["properties"] == {}


def test_convert_from_tools_function_objects():
    data = {
        "tools": [
            {
                "function": {
                    "name": "fn1",
                    "description": "desc1",
                    "parameters": {"type": "object", "properties": {}},
                }
            }
        ]
    }
    out = convert_tool_to_giga_functions(data)
    assert len(out) == 1
    assert out[0].name == "fn1"


def test_convert_from_functions_list():
    data = {
        "functions": [
            {
                "name": "fn2",
                "description": "desc2",
                "parameters": {
                    "type": "object",
                    "properties": {"a": {"type": "string"}},
                },
            }
        ]
    }
    out = convert_tool_to_giga_functions(data)
    assert len(out) == 1
    assert out[0].name == "fn2"


def test_convert_skips_tools_without_parameters():
    """Test that tools without parameters (e.g., custom/freeform tools) are skipped."""
    data = {
        "tools": [
            {
                "type": "custom",
                "name": "apply_patch",
                "description": "Freeform tool without parameters",
                "format": {"type": "grammar", "syntax": "lark"},
            },
            {
                "type": "function",
                "name": "valid_tool",
                "description": "Tool with parameters",
                "parameters": {
                    "type": "object",
                    "properties": {"arg": {"type": "string"}},
                },
            },
        ]
    }
    out = convert_tool_to_giga_functions(data)
    assert len(out) == 1
    assert out[0].name == "valid_tool"


def test_convert_skips_function_wrapper_without_parameters():
    """Test that function wrappers without parameters are skipped."""
    data = {
        "tools": [
            {
                "function": {
                    "name": "no_params_fn",
                    "description": "Function without parameters",
                }
            },
            {
                "function": {
                    "name": "valid_fn",
                    "description": "Function with parameters",
                    "parameters": {"type": "object", "properties": {}},
                }
            },
        ]
    }
    out = convert_tool_to_giga_functions(data)
    assert len(out) == 1
    assert out[0].name == "valid_fn"
