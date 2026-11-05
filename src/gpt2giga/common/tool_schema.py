"""Opt-in, lossy tool-schema adaptation for the GigaChat schema subset."""

from copy import deepcopy
from typing import Any


def normalize_tool_schema(schema: Any) -> Any:
    """Collapse unions without modifying input schemas or literal JSON values."""
    if not isinstance(schema, dict):
        return deepcopy(schema)
    result = deepcopy(schema)
    for keyword in ("anyOf", "oneOf"):
        variants = result.get(keyword)
        if not isinstance(variants, list) or not variants:
            continue
        branches = [normalize_tool_schema(item) for item in variants]
        branches = [
            item
            for item in branches
            if isinstance(item, dict) and item.get("type") != "null"
        ]
        if not branches:
            continue
        objects = [
            item
            for item in branches
            if item.get("type") == "object" or "properties" in item
        ]
        selected = _merge_objects(objects) if objects else branches[0]
        result.pop(keyword)
        # Sibling constraints and annotations apply to the union as a whole.
        result = {**selected, **result}

    types = result.get("type")
    if isinstance(types, list) and types:
        result["type"] = next((item for item in types if item != "null"), types[0])
    for keyword in (
        "properties",
        "$defs",
        "definitions",
        "patternProperties",
        "dependentSchemas",
    ):
        children = result.get(keyword)
        if isinstance(children, dict):
            result[keyword] = {
                name: normalize_tool_schema(child) for name, child in children.items()
            }
    for keyword in (
        "items",
        "additionalProperties",
        "contains",
        "not",
        "if",
        "then",
        "else",
        "propertyNames",
        "unevaluatedProperties",
        "unevaluatedItems",
    ):
        child = result.get(keyword)
        if isinstance(child, dict):
            result[keyword] = normalize_tool_schema(child)
        elif isinstance(child, list):
            result[keyword] = [normalize_tool_schema(item) for item in child]
    for keyword in ("allOf", "prefixItems"):
        children = result.get(keyword)
        if isinstance(children, list):
            result[keyword] = [normalize_tool_schema(child) for child in children]
    if result.get("type") == "object" or "properties" in result:
        result.setdefault("type", "object")
        result.setdefault("properties", {})
    return result


def _merge_objects(branches: list[dict]) -> dict:
    result = deepcopy(branches[0])
    properties: dict = {}
    required = list(branches[0].get("required", []))
    for branch in branches:
        required = [name for name in required if name in branch.get("required", [])]
        for name, prop in branch.get("properties", {}).items():
            if name not in properties:
                properties[name] = deepcopy(prop)
                continue
            previous = properties[name]
            merged = normalize_tool_schema({"anyOf": [previous, prop]})
            if isinstance(previous, dict) and isinstance(prop, dict):
                if "enum" in previous and "enum" in prop:
                    merged["enum"] = deepcopy(previous["enum"])
                    for value in prop["enum"]:
                        if value not in merged["enum"]:
                            merged["enum"].append(deepcopy(value))
                else:
                    merged.pop("enum", None)
            properties[name] = merged
    result.update(type="object", properties=properties)
    if required or any("required" in branch for branch in branches):
        result["required"] = required
    return result
