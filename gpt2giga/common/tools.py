from gigachat.models import Function, FunctionParameters

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


def convert_tool_to_giga_functions(data: dict):
    functions = []
    tools = data.get("tools", []) or data.get("functions", [])
    for tool in tools:
        if tool.get("function"):
            function = tool["function"]
            if "parameters" not in function:
                # Skip tools without parameters (e.g., custom/freeform tools)
                continue
            # Resolve $ref/$defs references as GigaChat doesn't support them
            resolved_params = resolve_schema_refs(function["parameters"])
            normalized_params = normalize_json_schema(resolved_params)
            giga_function = Function(
                name=map_tool_name_to_gigachat(function["name"]),
                description=function.get("description", ""),
                parameters=FunctionParameters(**normalized_params),
            )
        elif "parameters" in tool:
            # Resolve $ref/$defs references as GigaChat doesn't support them
            resolved_params = resolve_schema_refs(tool["parameters"])
            normalized_params = normalize_json_schema(resolved_params)
            giga_function = Function(
                name=map_tool_name_to_gigachat(tool["name"]),
                description=tool.get("description", ""),
                parameters=FunctionParameters(**normalized_params),
            )
        else:
            # Skip tools without parameters (e.g., custom/freeform tools like apply_patch)
            continue
        functions.append(giga_function)
    return functions
