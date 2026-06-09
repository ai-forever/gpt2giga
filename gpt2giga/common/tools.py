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
_NAMESPACE_TOOL_SEPARATOR = "__"


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


def map_namespaced_tool_name_to_gigachat(namespace: str, name: str) -> str:
    """Map a Responses namespace tool name to a flat GigaChat function name."""
    separator = (
        ""
        if namespace.endswith(_NAMESPACE_TOOL_SEPARATOR)
        else (_NAMESPACE_TOOL_SEPARATOR)
    )
    return map_tool_name_to_gigachat(f"{namespace}{separator}{name}")


def split_gigachat_tool_name(
    name: str,
    *,
    request_tools: Any = None,
) -> tuple[str, str | None]:
    """Return client-visible tool name and optional Responses namespace."""
    namespace_tools = build_namespaced_tool_name_map(request_tools)
    if name in namespace_tools:
        namespace, tool_name = namespace_tools[name]
        return tool_name, namespace

    visible_name = map_tool_name_from_gigachat(name)
    if visible_name in namespace_tools:
        namespace, tool_name = namespace_tools[visible_name]
        return tool_name, namespace

    return visible_name, None


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


def build_namespaced_tool_name_map(
    tools: Any,
) -> dict[str, tuple[str, str]]:
    """Build a GigaChat function-name map for Responses namespace tools."""
    if not isinstance(tools, list):
        return {}

    name_map: dict[str, tuple[str, str]] = {}
    for tool in tools:
        if not isinstance(tool, Mapping) or tool.get("type") != "namespace":
            continue
        namespace = tool.get("name")
        nested_tools = tool.get("tools")
        if not isinstance(namespace, str) or not namespace:
            continue
        if not isinstance(nested_tools, list):
            continue

        for nested_tool in nested_tools:
            if not isinstance(nested_tool, Mapping):
                continue
            function = _function_tool_payload(
                nested_tool,
                require_parameters=False,
            )
            if function is None:
                continue
            name = function.get("name")
            if not isinstance(name, str) or not name:
                continue
            mapped_name = map_namespaced_tool_name_to_gigachat(namespace, name)
            name_map[mapped_name] = (namespace, name)

    return name_map


def iter_function_tool_payloads(data: dict, *, require_parameters: bool = True):
    """Yield flat function definitions from OpenAI function and namespace tools."""
    source, tools = _tool_source(data)
    if tools is None:
        return
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
        if tool.get("type") == "namespace":
            yield from _iter_namespace_function_payloads(
                tool,
                source,
                index,
                require_parameters=require_parameters,
            )
            continue

        if "function" in tool and not isinstance(tool["function"], Mapping):
            raise ClientCompatibilityError(
                f"`{source}[{index}].function` must be an object.",
                provider="openai",
                param=source,
            )
        function = _function_tool_payload(tool, require_parameters=require_parameters)
        if function is None:
            continue
        function = dict(function)
        function["name"] = _require_tool_name(function, source, index)
        yield function


def _iter_namespace_function_payloads(
    tool: Mapping[str, Any],
    source: str,
    index: int,
    *,
    require_parameters: bool = True,
):
    namespace = _require_tool_name(tool, source, index)
    nested_tools = tool.get("tools")
    if not isinstance(nested_tools, list):
        raise ClientCompatibilityError(
            f"`{source}[{index}].tools` must be an array.",
            provider="openai",
            param=source,
        )

    nested_source = f"{source}[{index}].tools"
    for nested_index, nested_tool in enumerate(nested_tools):
        if not isinstance(nested_tool, Mapping):
            raise ClientCompatibilityError(
                f"`{nested_source}[{nested_index}]` must be an object.",
                provider="openai",
                param=source,
            )
        function = _function_tool_payload(
            nested_tool,
            require_parameters=require_parameters,
        )
        if function is None:
            continue
        function = dict(function)
        function_name = _require_tool_name(function, nested_source, nested_index)
        function["name"] = map_namespaced_tool_name_to_gigachat(
            namespace,
            function_name,
        )
        yield function


def _function_tool_payload(
    tool: Mapping[str, Any],
    *,
    require_parameters: bool = True,
) -> Mapping[str, Any] | None:
    if "function" in tool:
        function = tool["function"]
        if not isinstance(function, Mapping):
            return None
        if require_parameters and "parameters" not in function:
            return None
        return function
    if "input_schema" in tool:
        function = dict(tool)
        function["parameters"] = function["input_schema"]
        return function
    if not require_parameters or "parameters" in tool:
        return tool
    return None


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

    for function in iter_function_tool_payloads(data):
        # Resolve $ref/$defs references as GigaChat doesn't support them
        resolved_params = resolve_schema_refs(function["parameters"])
        normalized_params = normalize_json_schema(resolved_params)
        giga_function = Function(
            name=map_tool_name_to_gigachat(function["name"]),
            description=function.get("description", ""),
            parameters=FunctionParameters(**normalized_params),
        )
        functions.append(giga_function)
    return functions
