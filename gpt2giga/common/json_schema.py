_GIGACHAT_ALLOWED_SCHEMA_FORMATS = frozenset({"date", "date-time", "time"})
_JSON_SCHEMA_TYPES = frozenset(
    {"array", "boolean", "integer", "null", "number", "object", "string"}
)


def _normalize_schema_type(value):
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _JSON_SCHEMA_TYPES:
            return normalized
        return value

    if isinstance(value, list):
        return [_normalize_schema_type(item) for item in value]

    return value


def _schema_type_is_null(schema: object) -> bool:
    if not isinstance(schema, dict):
        return False
    schema_type = _normalize_schema_type(schema.get("type"))
    if schema_type == "null":
        return True
    if isinstance(schema_type, list):
        return bool(schema_type) and all(item == "null" for item in schema_type)
    return False


def _infer_missing_type(schema: dict, *, default: str = "string") -> str:
    if "properties" in schema or "additionalProperties" in schema:
        return "object"
    if "items" in schema:
        return "array"

    enum = schema.get("enum")
    if isinstance(enum, list):
        for item in enum:
            if isinstance(item, str):
                return "string"
            if isinstance(item, bool):
                return "boolean"
            if isinstance(item, int):
                return "integer"
            if isinstance(item, float):
                return "number"

    return default


def _ensure_object_properties(schema: dict) -> None:
    if schema.get("type") == "object" and "properties" not in schema:
        schema["properties"] = {}


def _ensure_concrete_property_schema(schema: dict) -> dict:
    if "type" not in schema:
        schema = dict(schema)
        schema["type"] = _infer_missing_type(schema, default="object")
    _ensure_object_properties(schema)
    return schema


def _merge_schema_dict(target: dict, source: dict) -> dict:
    merged = dict(target)
    for key, value in source.items():
        if key == "properties" and isinstance(value, dict):
            existing = merged.get(key)
            if isinstance(existing, dict):
                merged[key] = {**value, **existing}
            else:
                merged[key] = value
            continue
        if key == "required" and isinstance(value, list):
            existing = merged.get(key)
            if isinstance(existing, list):
                merged[key] = [
                    *existing,
                    *[item for item in value if item not in existing],
                ]
            else:
                merged[key] = value
            continue
        if key not in merged:
            merged[key] = value
    return merged


def resolve_schema_refs(schema: dict) -> dict:
    """Resolve $ref references and anyOf/oneOf in JSON schema.

    GigaChat doesn't support $ref/$defs and anyOf/oneOf, so we need to expand the
    schema and simplify Optional types.
    """
    from typing import Any, Dict

    def resolve(obj: Any, defs: Dict[str, Any]) -> Any:
        if isinstance(obj, dict):
            # Handle $ref
            if "$ref" in obj:
                ref_path = obj["$ref"]
                # Parse reference like '#/$defs/Step'
                if ref_path.startswith("#/$defs/"):
                    ref_name = ref_path.split("/")[-1]
                    if ref_name in defs:
                        # Return resolved definition (recursively resolve)
                        resolved = defs[ref_name].copy()
                        return resolve(resolved, defs)
                return obj

            # Handle anyOf/oneOf (typically from Optional types)
            # Pydantic generates: anyOf: [{actual_type}, {type: "null"}]
            for union_key in ("anyOf", "oneOf"):
                if union_key in obj:
                    variants = obj[union_key]
                    # Find non-null variant
                    non_null_variants = [
                        v for v in variants if not _schema_type_is_null(v)
                    ]
                    if non_null_variants:
                        # Take the first non-null variant and merge with other props
                        result = resolve(non_null_variants[0], defs)
                        # Preserve other properties like 'default', 'title', 'description'
                        for key, value in obj.items():
                            if key not in (union_key, "$defs") and key not in result:
                                result[key] = resolve(value, defs)
                        return result
                    # If all are null, just return null type
                    return {"type": "null"}

            # Recursively process dict, skipping $defs
            return {
                key: resolve(value, defs)
                for key, value in obj.items()
                if key != "$defs"
            }

        if isinstance(obj, list):
            return [resolve(item, defs) for item in obj]

        return obj

    defs = schema.get("$defs", {})
    return resolve(schema, defs)


def normalize_json_schema(schema: dict) -> dict:
    """Нормализует JSON Schema для совместимости с GigaChat.

    - GigaChat требует, чтобы у каждого объекта (type: "object") были properties.
      Если properties отсутствуют, добавляем пустой объект.
    - GigaChat не поддерживает anyOf/oneOf с type: null (Optional типы).
      Удаляем null варианты и упрощаем схему.
    - JSON Schema также поддерживает type: ['string', 'null'] для nullable типов.
      Преобразуем в одиночный тип (первый не-null).
    - GigaChat принимает только форматы date/date-time/time. Остальные format
      значения удаляем.
    """
    if not isinstance(schema, dict):
        return schema

    result = dict(schema)

    if "type" in result:
        result["type"] = _normalize_schema_type(result["type"])

    # Handle array-style type field: type: ['string', 'null'] -> type: 'string'
    if "type" in result and isinstance(result["type"], list):
        non_null_types = [t for t in result["type"] if t != "null"]
        if non_null_types:
            result["type"] = non_null_types[0]
        elif result["type"]:
            result["type"] = result["type"][0]

    if "format" in result and result["format"] not in _GIGACHAT_ALLOWED_SCHEMA_FORMATS:
        result.pop("format", None)

    # Обрабатываем anyOf, oneOf - GigaChat SDK не поддерживает эти конструкции
    for key in ("anyOf", "oneOf"):
        if key in result and isinstance(result[key], list):
            # Фильтруем null типы
            filtered = [item for item in result[key] if not _schema_type_is_null(item)]

            # Удаляем anyOf/oneOf - GigaChat SDK его не поддерживает
            del result[key]

            if len(filtered) >= 1:
                single = normalize_json_schema(filtered[0])
                for k, v in single.items():
                    # Не перезаписываем существующие поля (description, default)
                    if k not in result:
                        result[k] = v

    # Обрабатываем allOf - GigaChat не поддерживает композицию схем
    if "allOf" in result and isinstance(result["allOf"], list):
        normalized_items = [
            normalize_json_schema(item)
            for item in result["allOf"]
            if isinstance(item, dict)
        ]
        del result["allOf"]
        merged_all_of: dict = {}
        for item in normalized_items:
            merged_all_of = _merge_schema_dict(merged_all_of, item)
        result = _merge_schema_dict(result, merged_all_of)

    # Если это объект без properties, добавляем пустые properties
    schema_type = result.get("type")
    _ensure_object_properties(result)

    # Рекурсивно обрабатываем properties
    if "properties" in result and isinstance(result["properties"], dict):
        normalized_properties = {}
        for key, value in result["properties"].items():
            normalized_value = normalize_json_schema(value)
            if isinstance(normalized_value, dict):
                normalized_value = _ensure_concrete_property_schema(normalized_value)
            normalized_properties[key] = normalized_value
        result["properties"] = normalized_properties

    # Обрабатываем items для массивов
    if "items" in result:
        if isinstance(result["items"], dict):
            result["items"] = normalize_json_schema(result["items"])
        elif isinstance(result["items"], list):
            normalized_items = [normalize_json_schema(item) for item in result["items"]]
            result["items"] = normalized_items[0] if normalized_items else {}

    if schema_type == "array":
        items = result.get("items")
        if not isinstance(items, dict):
            result["items"] = {"type": "string"}
        elif "type" not in items:
            result["items"] = dict(items)
            result["items"]["type"] = _infer_missing_type(result["items"])
            _ensure_object_properties(result["items"])

    # Обрабатываем additionalProperties если это схема
    if "additionalProperties" in result and isinstance(
        result["additionalProperties"], dict
    ):
        result["additionalProperties"] = normalize_json_schema(
            result["additionalProperties"]
        )

    # Обрабатываем $defs / definitions
    for key in ("$defs", "definitions"):
        if key in result and isinstance(result[key], dict):
            result[key] = {
                def_key: normalize_json_schema(def_value)
                for def_key, def_value in result[key].items()
            }

    return result


def normalize_tool_parameters_schema(schema: object) -> dict:
    """Normalize a root function/tool parameters schema for GigaChat."""
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}

    result = normalize_json_schema(resolve_schema_refs(schema))
    if not isinstance(result, dict) or not result:
        return {"type": "object", "properties": {}}

    if "type" not in result:
        result = dict(result)
        result["type"] = "object"

    if result.get("type") == "object":
        result = dict(result)
        result.setdefault("properties", {})

    return result
