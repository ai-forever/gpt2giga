def resolve_schema_refs(schema: dict) -> dict:
    """Resolve `$ref` references and simplify nullable unions."""
    from typing import Any

    def resolve(obj: Any, defs: dict[str, Any]) -> Any:
        if isinstance(obj, dict):
            if "$ref" in obj:
                ref_path = obj["$ref"]
                if ref_path.startswith("#/$defs/"):
                    ref_name = ref_path.split("/")[-1]
                    if ref_name in defs:
                        resolved = defs[ref_name].copy()
                        return resolve(resolved, defs)
                return obj

            for union_key in ("anyOf", "oneOf"):
                if union_key in obj:
                    variants = obj[union_key]
                    non_null_variants = [v for v in variants if v.get("type") != "null"]
                    if non_null_variants:
                        result = resolve(non_null_variants[0], defs)
                        for key, value in obj.items():
                            if key not in (union_key, "$defs") and key not in result:
                                result[key] = resolve(value, defs)
                        return result
                    return {"type": "null"}

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
    """Normalize JSON Schema for GigaChat compatibility."""
    if not isinstance(schema, dict):
        return schema

    result = dict(schema)

    if "type" in result and isinstance(result["type"], list):
        non_null_types = [t for t in result["type"] if t != "null"]
        if non_null_types:
            result["type"] = non_null_types[0]
        elif result["type"]:
            result["type"] = result["type"][0]

    for key in ("anyOf", "oneOf"):
        if key in result and isinstance(result[key], list):
            filtered = [
                item
                for item in result[key]
                if not (isinstance(item, dict) and item.get("type") == "null")
            ]

            del result[key]

            if filtered:
                single = normalize_json_schema(filtered[0])
                for nested_key, nested_value in single.items():
                    if nested_key not in result:
                        result[nested_key] = nested_value

    if "allOf" in result and isinstance(result["allOf"], list):
        result["allOf"] = [normalize_json_schema(item) for item in result["allOf"]]

    if result.get("type") == "object" and "properties" not in result:
        result["properties"] = {}

    if "properties" in result and isinstance(result["properties"], dict):
        result["properties"] = {
            key: normalize_json_schema(value)
            for key, value in result["properties"].items()
        }

    if "items" in result:
        if isinstance(result["items"], dict):
            result["items"] = normalize_json_schema(result["items"])
        elif isinstance(result["items"], list):
            result["items"] = [normalize_json_schema(item) for item in result["items"]]

    if "additionalProperties" in result and isinstance(
        result["additionalProperties"], dict
    ):
        result["additionalProperties"] = normalize_json_schema(
            result["additionalProperties"]
        )

    for key in ("$defs", "definitions"):
        if key in result and isinstance(result[key], dict):
            result[key] = {
                def_key: normalize_json_schema(def_value)
                for def_key, def_value in result[key].items()
            }

    return result
