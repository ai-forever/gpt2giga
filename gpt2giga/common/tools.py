from collections.abc import Mapping
from typing import Any

from gigachat.models import Function, FunctionParameters

from gpt2giga.common.client_params import ClientCompatibilityError
from gpt2giga.common.json_schema import normalize_json_schema, resolve_schema_refs

_RESERVED_GIGACHAT_TOOL_NAME_MAP = {
    # У GigaChat есть встроенный tool под названием "web_search".
    # Если пользователь передает custom tool с таким же названием, это может вызвать конфликт на стороне GigaChat.
    "web_search": "__gpt2giga_user_search_web",
}
_RESERVED_GIGACHAT_TOOL_NAME_MAP_REVERSE = {
    v: k for k, v in _RESERVED_GIGACHAT_TOOL_NAME_MAP.items()
}


def map_tool_name_to_gigachat(name: str) -> str:
    """Map user tool name to a safe GigaChat function name.

    Args:
        name: Tool/function name as provided by the client.

    Returns:
        Name safe to send to GigaChat (may be unchanged).
    """
    return _RESERVED_GIGACHAT_TOOL_NAME_MAP.get(name, name)


def map_tool_name_from_gigachat(name: str) -> str:
    """Map GigaChat function name back to the user-visible name.

    Args:
        name: Tool/function name coming from GigaChat.

    Returns:
        Name to return to the client (may be unchanged).
    """
    return _RESERVED_GIGACHAT_TOOL_NAME_MAP_REVERSE.get(name, name)


def _tool_source(data: dict) -> tuple[str, Any]:
    if "tools" in data:
        tools = data.get("tools")
        if tools not in (None, []):
            return "tools", tools
        if "functions" not in data:
            return "tools", tools
    return "functions", data.get("functions", [])


def _require_tool_name(definition: Mapping, source: str, index: int) -> str:
    name = definition.get("name")
    if not isinstance(name, str) or not name:
        raise ClientCompatibilityError(
            f"`{source}[{index}].name` must be a non-empty string.",
            provider="openai",
            param=source,
        )
    return name


def convert_tool_to_giga_functions(data: dict):
    functions = []
    source, tools = _tool_source(data)
    if tools is None:
        return functions
    if not isinstance(tools, list):
        raise ClientCompatibilityError(
            f"`{source}` must be an array.",
            provider="openai",
            param=source,
        )

    for index, tool in enumerate(tools):
        if not isinstance(tool, Mapping):
            raise ClientCompatibilityError(
                f"`{source}[{index}]` must be an object.",
                provider="openai",
                param=source,
            )
        if "function" in tool:
            function = tool["function"]
            if not isinstance(function, Mapping):
                raise ClientCompatibilityError(
                    f"`{source}[{index}].function` must be an object.",
                    provider="openai",
                    param=source,
                )
            if "parameters" not in function:
                # Skip tools without parameters (e.g., custom/freeform tools)
                continue
            # Resolve $ref/$defs references as GigaChat doesn't support them
            resolved_params = resolve_schema_refs(function["parameters"])
            normalized_params = normalize_json_schema(resolved_params)
            giga_function = Function(
                name=map_tool_name_to_gigachat(
                    _require_tool_name(function, source, index)
                ),
                description=function.get("description", ""),
                parameters=FunctionParameters(**normalized_params),
            )
        elif "parameters" in tool:
            # Resolve $ref/$defs references as GigaChat doesn't support them
            resolved_params = resolve_schema_refs(tool["parameters"])
            normalized_params = normalize_json_schema(resolved_params)
            giga_function = Function(
                name=map_tool_name_to_gigachat(_require_tool_name(tool, source, index)),
                description=tool.get("description", ""),
                parameters=FunctionParameters(**normalized_params),
            )
        else:
            # Skip tools without parameters (e.g., custom/freeform tools like apply_patch)
            continue
        functions.append(giga_function)
    return functions
