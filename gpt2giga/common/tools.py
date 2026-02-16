from gigachat.models import Function, FunctionParameters

from gpt2giga.common.json_schema import normalize_json_schema, resolve_schema_refs


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
                name=function["name"],
                description=function.get("description", ""),
                parameters=FunctionParameters(**normalized_params),
            )
        elif "parameters" in tool:
            # Resolve $ref/$defs references as GigaChat doesn't support them
            resolved_params = resolve_schema_refs(tool["parameters"])
            normalized_params = normalize_json_schema(resolved_params)
            giga_function = Function(
                name=tool["name"],
                description=tool.get("description", ""),
                parameters=FunctionParameters(**normalized_params),
            )
        else:
            # Skip tools without parameters (e.g., custom/freeform tools like apply_patch)
            continue
        functions.append(giga_function)
    return functions
