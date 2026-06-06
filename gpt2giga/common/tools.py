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
_GIGACHAT_BUILTIN_TOOL_TYPE_ALIASES = {
    "code_interpreter": "code_interpreter",
    "image_generate": "image_generate",
    "image_generation": "image_generate",
    "model_3d_generate": "model_3d_generate",
    "url_content_extraction": "url_content_extraction",
}
_GIGACHAT_WEB_SEARCH_TOOL_PREFIX = "web_search"


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


def normalize_gigachat_builtin_tool_type(tool_type: Any) -> str | None:
    """Return a GigaChat v2 built-in tool field name for a Responses tool type."""
    if not isinstance(tool_type, str):
        return None

    normalized = tool_type.strip()
    if normalized.startswith(_GIGACHAT_WEB_SEARCH_TOOL_PREFIX):
        return "web_search"
    return _GIGACHAT_BUILTIN_TOOL_TYPE_ALIASES.get(normalized)


def build_gigachat_builtin_tool_payload(tool: Mapping[str, Any]) -> dict[str, Any]:
    """Build a GigaChat v2 ChatTool payload from a Responses built-in tool."""
    tool_type = tool.get("type")
    field_name = normalize_gigachat_builtin_tool_type(tool_type)
    if field_name is None:
        return {}

    config: dict[str, Any] = {}
    nested_config = tool.get(field_name)
    if isinstance(nested_config, Mapping):
        config.update(nested_config)

    if isinstance(tool_type, str) and tool_type != field_name:
        alias_config = tool.get(tool_type)
        if isinstance(alias_config, Mapping):
            config.update(alias_config)

    structural_keys = {"type", "function", field_name}
    if isinstance(tool_type, str):
        structural_keys.add(tool_type)
    for key, value in tool.items():
        if key not in structural_keys:
            config.setdefault(key, value)

    return {field_name: config}


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
        if normalize_gigachat_builtin_tool_type(tool.get("type")) is not None:
            continue
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
