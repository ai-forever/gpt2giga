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
                    non_null_variants = [v for v in variants if v.get("type") != "null"]
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
    """
    if not isinstance(schema, dict):
        return schema

    result = dict(schema)

    # Handle array-style type field: type: ['string', 'null'] -> type: 'string'
    if "type" in result and isinstance(result["type"], list):
        non_null_types = [t for t in result["type"] if t != "null"]
        if non_null_types:
            result["type"] = non_null_types[0]
        elif result["type"]:
            result["type"] = result["type"][0]

    # Обрабатываем anyOf, oneOf - GigaChat SDK не поддерживает эти конструкции
    for key in ("anyOf", "oneOf"):
        if key in result and isinstance(result[key], list):
            # Фильтруем null типы
            filtered = [
                item
                for item in result[key]
                if not (isinstance(item, dict) and item.get("type") == "null")
            ]

            # Удаляем anyOf/oneOf - GigaChat SDK его не поддерживает
            del result[key]

            if len(filtered) >= 1:
                single = normalize_json_schema(filtered[0])
                for k, v in single.items():
                    # Не перезаписываем существующие поля (description, default)
                    if k not in result:
                        result[k] = v

    # Обрабатываем allOf (без удаления null)
    if "allOf" in result and isinstance(result["allOf"], list):
        result["allOf"] = [normalize_json_schema(item) for item in result["allOf"]]

    # Если это объект без properties, добавляем пустые properties
    schema_type = result.get("type")
    if schema_type == "object" and "properties" not in result:
        result["properties"] = {}

    # Рекурсивно обрабатываем properties
    if "properties" in result and isinstance(result["properties"], dict):
        result["properties"] = {
            key: normalize_json_schema(value)
            for key, value in result["properties"].items()
        }

    # Обрабатываем items для массивов
    if "items" in result:
        if isinstance(result["items"], dict):
            result["items"] = normalize_json_schema(result["items"])
        elif isinstance(result["items"], list):
            result["items"] = [normalize_json_schema(item) for item in result["items"]]

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
