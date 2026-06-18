"""Tool-call arbitration helpers for Fusion runs."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from gpt2giga.protocols.normalized import NormalizedTool, NormalizedToolCall
from gpt2giga.providers.fusion.schemas import FusionPanelResult

MAX_TOOL_ARGUMENTS_JSON_LENGTH = 65_536


@dataclass(frozen=True)
class ToolCallPolicy:
    """Resolved Fusion tool-call policy for one request."""

    allow_tool_calls: bool
    require_tool_call: bool
    forced_tool_name: str | None
    allowed_tool_names: frozenset[str]
    max_tool_calls: int
    reason: str | None = None


@dataclass(frozen=True)
class ToolValidationResult:
    """Result of validating one final Fusion tool call."""

    valid: bool
    tool_call: NormalizedToolCall | None = None
    reason: str | None = None


def build_panel_tool_reference(
    tools: list[NormalizedTool],
    tools_mode: str,
) -> str | None:
    """Build reference-only tool schema text for panel-stage prompts."""
    if not tools or tools_mode == "off":
        return None
    return (
        "Tool schemas are reference-only in the panel stage. Do not execute "
        "tools or emit real tool calls. If a tool is necessary, propose one "
        "tool_call_candidate JSON object for the judge/finalizer.\n"
        f"{_json_dumps(_tool_schema_payload(tools))}"
    )


def build_judge_tool_arbitration_prompt(
    *,
    tools: list[NormalizedTool],
    panel_results: list[FusionPanelResult],
    tool_choice: Any,
    tools_mode: str,
    max_tool_calls: int,
) -> str | None:
    """Build judge/finalizer tool arbitration instructions."""
    policy = resolve_tool_call_policy(
        tools=tools,
        tools_mode=tools_mode,
        tool_choice=tool_choice,
        max_tool_calls=max_tool_calls,
    )
    if not tools and not policy.require_tool_call:
        return None

    if not policy.allow_tool_calls:
        return (
            "Tool arbitration mode forbids final tool calls. Return "
            "final_tool_call=null and provide a text final_answer."
        )

    payload = {
        "mode": tools_mode,
        "tool_choice": tool_choice,
        "require_tool_call": policy.require_tool_call,
        "forced_tool_name": policy.forced_tool_name,
        "max_tool_calls": policy.max_tool_calls,
        "allowed_tool_names": sorted(policy.allowed_tool_names),
        "tool_schemas": _tool_schema_payload(tools),
        "panel_tool_candidates": [
            candidate.to_json_dict()
            for candidate in panel_tool_candidates(panel_results)
        ],
    }
    return (
        "Tool arbitration instructions:\n"
        "- Only the judge/finalizer may return a real final_tool_call.\n"
        "- Panel candidates are advisory only and must not be forwarded "
        "without validation.\n"
        "- If returning final_tool_call, choose a tool from allowed_tool_names "
        "and satisfy tool_choice.\n"
        "- If no valid tool call is needed and require_tool_call=false, return "
        "final_tool_call=null and a text final_answer.\n"
        f"{_json_dumps(payload)}"
    )


def resolve_tool_call_policy(
    *,
    tools: list[NormalizedTool],
    tools_mode: str,
    tool_choice: Any,
    max_tool_calls: int = 1,
) -> ToolCallPolicy:
    """Resolve whether Fusion may or must emit a final tool call."""
    allowed_names = frozenset(tool.name for tool in tools if tool.name)
    effective_max_tool_calls = max_tool_calls if max_tool_calls > 0 else 1
    require_tool_call = _tool_choice_requires_tool(tool_choice)
    forced_name = _forced_tool_name(tool_choice)

    if tools_mode == "off":
        return ToolCallPolicy(
            allow_tool_calls=False,
            require_tool_call=require_tool_call,
            forced_tool_name=forced_name,
            allowed_tool_names=allowed_names,
            max_tool_calls=effective_max_tool_calls,
            reason="tools_mode_off",
        )
    if not allowed_names:
        return ToolCallPolicy(
            allow_tool_calls=False,
            require_tool_call=require_tool_call,
            forced_tool_name=forced_name,
            allowed_tool_names=allowed_names,
            max_tool_calls=effective_max_tool_calls,
            reason="no_tools",
        )
    if _tool_choice_disables_tools(tool_choice):
        return ToolCallPolicy(
            allow_tool_calls=False,
            require_tool_call=False,
            forced_tool_name=None,
            allowed_tool_names=allowed_names,
            max_tool_calls=effective_max_tool_calls,
            reason="tool_choice_none",
        )

    return ToolCallPolicy(
        allow_tool_calls=True,
        require_tool_call=require_tool_call,
        forced_tool_name=forced_name,
        allowed_tool_names=allowed_names,
        max_tool_calls=effective_max_tool_calls,
    )


def panel_tool_candidates(
    panel_results: list[FusionPanelResult],
) -> list[NormalizedToolCall]:
    """Extract advisory tool candidates from panel results."""
    candidates: list[NormalizedToolCall] = []
    for result in panel_results:
        if result.status != "ok":
            continue
        candidates.extend(
            _annotated_candidate(tool_call, panel=result)
            for tool_call in result.tool_calls
            if tool_call.name
        )
        candidates.extend(
            _annotated_candidate(tool_call, panel=result)
            for tool_call in _tool_candidates_from_text(result.content)
            if tool_call.name
        )
    return candidates


def first_allowed_tool_call(
    tool_calls: list[NormalizedToolCall],
    *,
    request_tools: list[NormalizedTool],
    tools_mode: str,
    tool_choice: Any,
    max_tool_calls: int = 1,
) -> NormalizedToolCall | None:
    """Return the first final tool call allowed by the request policy."""
    for tool_call in tool_calls:
        result = validate_tool_call_arguments(
            tool_call,
            request_tools=request_tools,
            tools_mode=tools_mode,
            tool_choice=tool_choice,
            max_tool_calls=max_tool_calls,
        )
        if result.valid:
            return result.tool_call
    return None


def tool_call_allowed(
    tool_call: NormalizedToolCall,
    *,
    request_tools: list[NormalizedTool],
    tools_mode: str,
    tool_choice: Any,
    max_tool_calls: int = 1,
) -> bool:
    """Return whether a final tool call satisfies Fusion arbitration policy."""
    return validate_tool_call_arguments(
        tool_call,
        request_tools=request_tools,
        tools_mode=tools_mode,
        tool_choice=tool_choice,
        max_tool_calls=max_tool_calls,
    ).valid


def validate_tool_call_arguments(
    tool_call: NormalizedToolCall,
    *,
    request_tools: list[NormalizedTool],
    tools_mode: str,
    tool_choice: Any,
    max_tool_calls: int = 1,
) -> ToolValidationResult:
    """Validate a final tool call name and arguments against request schemas."""
    policy = resolve_tool_call_policy(
        tools=request_tools,
        tools_mode=tools_mode,
        tool_choice=tool_choice,
        max_tool_calls=max_tool_calls,
    )
    if not policy.allow_tool_calls:
        return ToolValidationResult(valid=False, reason=policy.reason or "forbidden")
    if not tool_call.name or tool_call.name not in policy.allowed_tool_names:
        return ToolValidationResult(valid=False, reason="tool_not_allowed")
    if policy.forced_tool_name and tool_call.name != policy.forced_tool_name:
        return ToolValidationResult(valid=False, reason="forced_tool_mismatch")

    tool = next(
        (candidate for candidate in request_tools if candidate.name == tool_call.name),
        None,
    )
    if tool is None:
        return ToolValidationResult(valid=False, reason="tool_not_found")

    arguments, parse_error = _normalized_tool_arguments(tool_call.arguments)
    if parse_error is not None:
        return ToolValidationResult(valid=False, reason=parse_error)

    try:
        serialized = json.dumps(arguments, ensure_ascii=True, sort_keys=True)
    except (TypeError, ValueError):
        return ToolValidationResult(valid=False, reason="arguments_not_json")
    if len(serialized) > MAX_TOOL_ARGUMENTS_JSON_LENGTH:
        return ToolValidationResult(valid=False, reason="arguments_too_large")

    schema = _tool_parameters_validation_schema(tool.parameters)
    schema_error = _validate_schema_value(arguments, schema, path="arguments")
    if schema_error is not None:
        return ToolValidationResult(valid=False, reason=schema_error)

    return ToolValidationResult(
        valid=True,
        tool_call=tool_call.model_copy(update={"arguments": arguments}),
    )


def tool_choice_requires_tool(
    *,
    request_tools: list[NormalizedTool],
    tools_mode: str,
    tool_choice: Any,
    max_tool_calls: int = 1,
) -> bool:
    """Return whether the client requested a required final tool call."""
    policy = resolve_tool_call_policy(
        tools=request_tools,
        tools_mode=tools_mode,
        tool_choice=tool_choice,
        max_tool_calls=max_tool_calls,
    )
    return policy.require_tool_call


def _tool_schema_payload(tools: list[NormalizedTool]) -> list[dict[str, Any]]:
    return [
        {
            "type": tool.type,
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        }
        for tool in tools
    ]


def _tool_candidates_from_text(content: str | None) -> list[NormalizedToolCall]:
    if not content:
        return []
    payload = _load_json_candidate_payload(content)
    if payload is None:
        return []

    raw_candidates: list[Any]
    if isinstance(payload, Mapping):
        if "tool_call_candidates" in payload:
            value = payload["tool_call_candidates"]
            raw_candidates = value if isinstance(value, list) else [value]
        elif "tool_call_candidate" in payload:
            raw_candidates = [payload["tool_call_candidate"]]
        else:
            raw_candidates = [payload]
    elif isinstance(payload, list):
        raw_candidates = payload
    else:
        return []

    candidates: list[NormalizedToolCall] = []
    for item in raw_candidates:
        if not isinstance(item, Mapping):
            continue
        candidate = _tool_call_from_mapping(item)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _load_json_candidate_payload(content: str) -> Any:
    text = _strip_code_fence(content)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None


def _tool_call_from_mapping(value: Mapping[str, Any]) -> NormalizedToolCall | None:
    function = value.get("function")
    function_data = function if isinstance(function, Mapping) else {}
    name = value.get("name") or function_data.get("name")
    if not isinstance(name, str) or not name:
        return None
    arguments = value.get("arguments")
    if arguments is None:
        arguments = value.get("input")
    if arguments is None:
        arguments = function_data.get("arguments")
    return NormalizedToolCall(
        id=_string_or_none(value.get("id") or value.get("call_id")),
        type=_string_or_none(value.get("type")) or "function",
        name=name,
        arguments=arguments,
    )


def _annotated_candidate(
    tool_call: NormalizedToolCall,
    *,
    panel: FusionPanelResult,
) -> NormalizedToolCall:
    candidate = tool_call.model_copy(deep=True)
    candidate.raw_extensions = {
        **candidate.raw_extensions,
        "fusion_panel_model": panel.model,
        "fusion_panel_role": panel.role,
    }
    return candidate


def _tool_choice_disables_tools(tool_choice: Any) -> bool:
    if isinstance(tool_choice, str):
        return tool_choice.strip().lower() == "none"
    if isinstance(tool_choice, Mapping):
        choice_type = _string_or_none(tool_choice.get("type"))
        return choice_type is not None and choice_type.lower() == "none"
    return False


def _tool_choice_requires_tool(tool_choice: Any) -> bool:
    if isinstance(tool_choice, str):
        return tool_choice.strip().lower() in {"any", "required"}
    if isinstance(tool_choice, Mapping):
        choice_type = _string_or_none(tool_choice.get("type"))
        if choice_type is None:
            return False
        choice_type = choice_type.lower()
        if choice_type in {"any", "required", "function", "tool"}:
            return True
    return False


def _forced_tool_name(tool_choice: Any) -> str | None:
    if isinstance(tool_choice, Mapping):
        function = tool_choice.get("function")
        if isinstance(function, Mapping):
            name = _string_or_none(function.get("name"))
            if name:
                return name
        name = _string_or_none(tool_choice.get("name"))
        if name:
            return name
    if isinstance(tool_choice, str):
        choice = tool_choice.strip()
        if choice and choice.lower() not in {"auto", "none", "any", "required"}:
            return choice
    return None


def _strip_code_fence(content: str) -> str:
    text = content.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _normalized_tool_arguments(value: Any) -> tuple[Any, str | None]:
    if value is None:
        return {}, None
    if isinstance(value, str):
        try:
            return json.loads(value), None
        except json.JSONDecodeError:
            return None, "arguments_malformed_json"
    return value, None


def _tool_parameters_validation_schema(schema: Any) -> Mapping[str, Any]:
    if not isinstance(schema, Mapping) or not schema:
        return {"type": "object", "properties": {}}
    if not any(
        key in schema
        for key in (
            "type",
            "properties",
            "required",
            "additionalProperties",
            "allOf",
            "anyOf",
            "oneOf",
        )
    ):
        return {"type": "object", "properties": {}, **schema}
    return schema


def _validate_schema_value(
    value: Any,
    schema: Mapping[str, Any],
    *,
    path: str,
) -> str | None:
    if not isinstance(schema, Mapping):
        return None

    composition_error = _validate_composition_keywords(value, schema, path=path)
    if composition_error is not None:
        return composition_error

    if "const" in schema and value != schema["const"]:
        return f"{path}.const"
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        return f"{path}.enum"

    schema_type = _schema_type(schema)
    if schema_type is not None and not _matches_schema_type(value, schema_type):
        return f"{path}.type"
    if isinstance(schema_type, list) and value is None and "null" in schema_type:
        return None

    effective_type = _single_non_null_type(schema_type)
    if effective_type == "object":
        return _validate_object_schema(value, schema, path=path)
    if effective_type == "array":
        return _validate_array_schema(value, schema, path=path)
    if effective_type == "string":
        return _validate_string_schema(value, schema, path=path)
    if effective_type in {"integer", "number"}:
        return _validate_number_schema(value, schema, path=path)
    return None


def _validate_object_schema(
    value: Any,
    schema: Mapping[str, Any],
    *,
    path: str,
) -> str | None:
    if not isinstance(value, Mapping):
        return f"{path}.type"

    min_properties = schema.get("minProperties")
    if isinstance(min_properties, int) and len(value) < min_properties:
        return f"{path}.minProperties"
    max_properties = schema.get("maxProperties")
    if isinstance(max_properties, int) and len(value) > max_properties:
        return f"{path}.maxProperties"

    required = schema.get("required")
    if isinstance(required, list):
        for key in required:
            if isinstance(key, str) and key not in value:
                return f"{path}.{key}.required"

    properties = schema.get("properties")
    if isinstance(properties, Mapping):
        for key, property_schema in properties.items():
            if key not in value:
                continue
            if isinstance(property_schema, Mapping):
                error = _validate_schema_value(
                    value[key],
                    property_schema,
                    path=f"{path}.{key}",
                )
                if error is not None:
                    return error

    additional = schema.get("additionalProperties")
    if additional is False and isinstance(properties, Mapping):
        allowed = {str(key) for key in properties}
        for key in value:
            if str(key) not in allowed:
                return f"{path}.{key}.additionalProperties"
    if isinstance(additional, Mapping):
        known_properties = set(properties) if isinstance(properties, Mapping) else set()
        for key, item in value.items():
            if key in known_properties:
                continue
            error = _validate_schema_value(item, additional, path=f"{path}.{key}")
            if error is not None:
                return error
    return None


def _validate_array_schema(
    value: Any,
    schema: Mapping[str, Any],
    *,
    path: str,
) -> str | None:
    if not isinstance(value, list):
        return f"{path}.type"
    min_items = schema.get("minItems")
    if isinstance(min_items, int) and len(value) < min_items:
        return f"{path}.minItems"
    max_items = schema.get("maxItems")
    if isinstance(max_items, int) and len(value) > max_items:
        return f"{path}.maxItems"
    if schema.get("uniqueItems") is True and not _array_items_are_unique(value):
        return f"{path}.uniqueItems"
    items = schema.get("items")
    if isinstance(items, Mapping):
        for index, item in enumerate(value):
            error = _validate_schema_value(item, items, path=f"{path}[{index}]")
            if error is not None:
                return error
    return None


def _validate_string_schema(
    value: Any,
    schema: Mapping[str, Any],
    *,
    path: str,
) -> str | None:
    if not isinstance(value, str):
        return f"{path}.type"
    min_length = schema.get("minLength")
    if isinstance(min_length, int) and len(value) < min_length:
        return f"{path}.minLength"
    max_length = schema.get("maxLength")
    if isinstance(max_length, int) and len(value) > max_length:
        return f"{path}.maxLength"
    pattern = schema.get("pattern")
    if isinstance(pattern, str):
        try:
            if re.search(pattern, value) is None:
                return f"{path}.pattern"
        except re.error:
            return f"{path}.pattern"
    return None


def _validate_number_schema(
    value: Any,
    schema: Mapping[str, Any],
    *,
    path: str,
) -> str | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return f"{path}.type"
    minimum = schema.get("minimum")
    if isinstance(minimum, (int, float)) and value < minimum:
        return f"{path}.minimum"
    maximum = schema.get("maximum")
    if isinstance(maximum, (int, float)) and value > maximum:
        return f"{path}.maximum"
    exclusive_minimum = schema.get("exclusiveMinimum")
    if isinstance(exclusive_minimum, (int, float)) and value <= exclusive_minimum:
        return f"{path}.exclusiveMinimum"
    exclusive_maximum = schema.get("exclusiveMaximum")
    if isinstance(exclusive_maximum, (int, float)) and value >= exclusive_maximum:
        return f"{path}.exclusiveMaximum"
    multiple_of = schema.get("multipleOf")
    if (
        isinstance(multiple_of, (int, float))
        and not isinstance(multiple_of, bool)
        and multiple_of > 0
    ):
        quotient = value / multiple_of
        if not math.isclose(quotient, round(quotient), rel_tol=1e-12, abs_tol=1e-12):
            return f"{path}.multipleOf"
    return None


def _validate_composition_keywords(
    value: Any,
    schema: Mapping[str, Any],
    *,
    path: str,
) -> str | None:
    all_of = schema.get("allOf")
    if isinstance(all_of, list):
        for subschema in all_of:
            if not isinstance(subschema, Mapping):
                continue
            error = _validate_schema_value(value, subschema, path=path)
            if error is not None:
                return error

    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        valid_count = _matching_subschema_count(value, any_of, path=path)
        if valid_count == 0:
            return f"{path}.anyOf"

    one_of = schema.get("oneOf")
    if isinstance(one_of, list):
        valid_count = _matching_subschema_count(value, one_of, path=path)
        if valid_count != 1:
            return f"{path}.oneOf"

    not_schema = schema.get("not")
    if isinstance(not_schema, Mapping):
        if _validate_schema_value(value, not_schema, path=path) is None:
            return f"{path}.not"

    return None


def _matching_subschema_count(
    value: Any,
    schemas: list[Any],
    *,
    path: str,
) -> int:
    return sum(
        1
        for subschema in schemas
        if isinstance(subschema, Mapping)
        and _validate_schema_value(value, subschema, path=path) is None
    )


def _array_items_are_unique(value: list[Any]) -> bool:
    seen: set[str] = set()
    for item in value:
        try:
            marker = json.dumps(item, ensure_ascii=True, sort_keys=True)
        except (TypeError, ValueError):
            marker = repr(item)
        if marker in seen:
            return False
        seen.add(marker)
    return True


def _schema_type(schema: Mapping[str, Any]) -> str | list[str] | None:
    value = schema.get("type")
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    if "properties" in schema or "required" in schema:
        return "object"
    if "items" in schema:
        return "array"
    return None


def _matches_schema_type(value: Any, schema_type: str | list[str]) -> bool:
    candidates = schema_type if isinstance(schema_type, list) else [schema_type]
    return any(
        _matches_single_schema_type(value, candidate) for candidate in candidates
    )


def _matches_single_schema_type(value: Any, schema_type: str) -> bool:
    if schema_type == "null":
        return value is None
    if schema_type == "object":
        return isinstance(value, Mapping)
    if schema_type == "array":
        return isinstance(value, list)
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return True


def _single_non_null_type(schema_type: str | list[str] | None) -> str | None:
    if schema_type is None:
        return None
    if isinstance(schema_type, str):
        return schema_type
    for item in schema_type:
        if item != "null":
            return item
    return schema_type[0] if schema_type else None
