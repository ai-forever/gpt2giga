from gigachat.models import Function, FunctionParameters

from gpt2giga.core.schema.json_schema import normalize_json_schema, resolve_schema_refs

_RESERVED_GIGACHAT_TOOL_NAME_MAP = {
    # GigaChat has a built-in tool named `web_search`.
    # Remap user-defined tools to avoid collisions.
    "web_search": "__gpt2giga_user_search_web",
}
_RESERVED_GIGACHAT_TOOL_NAME_MAP_REVERSE = {
    value: key for key, value in _RESERVED_GIGACHAT_TOOL_NAME_MAP.items()
}


def map_tool_name_to_gigachat(name: str) -> str:
    """Map a user-visible tool name to a safe GigaChat name."""
    return _RESERVED_GIGACHAT_TOOL_NAME_MAP.get(name, name)


def map_tool_name_from_gigachat(name: str) -> str:
    """Map a GigaChat tool name back to the external one."""
    return _RESERVED_GIGACHAT_TOOL_NAME_MAP_REVERSE.get(name, name)


def convert_tool_to_giga_functions(data: dict):
    """Convert OpenAI-style tools into GigaChat SDK function objects."""
    functions = []
    tools = data.get("tools", []) or data.get("functions", [])
    for tool in tools:
        if tool.get("function"):
            function = tool["function"]
            if "parameters" not in function:
                continue
            resolved_params = resolve_schema_refs(function["parameters"])
            normalized_params = normalize_json_schema(resolved_params)
            giga_function = Function(
                name=map_tool_name_to_gigachat(function["name"]),
                description=function.get("description", ""),
                parameters=FunctionParameters(**normalized_params),
            )
        elif "parameters" in tool:
            resolved_params = resolve_schema_refs(tool["parameters"])
            normalized_params = normalize_json_schema(resolved_params)
            giga_function = Function(
                name=map_tool_name_to_gigachat(tool["name"]),
                description=tool.get("description", ""),
                parameters=FunctionParameters(**normalized_params),
            )
        else:
            continue
        functions.append(giga_function)
    return functions
