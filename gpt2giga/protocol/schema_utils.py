"""
Utilities for JSON Schema resolution and transformation.

GigaChat doesn't support $ref/$defs and anyOf/oneOf constructs,
so schemas need to be resolved and simplified before use.
"""

from typing import Any, Dict


def resolve_schema_refs(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resolves $ref references and anyOf/oneOf in JSON schema.

    GigaChat doesn't support $ref/$defs and anyOf/oneOf, so we need to
    expand the schema and simplify Optional types.

    Args:
        schema: JSON schema that may contain $ref, $defs, anyOf, oneOf

    Returns:
        Resolved schema without $ref/$defs references
    """

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

        elif isinstance(obj, list):
            return [resolve(item, defs) for item in obj]

        return obj

    defs = schema.get("$defs", {})
    return resolve(schema, defs)
