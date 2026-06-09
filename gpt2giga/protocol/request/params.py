"""OpenAI request parameter compatibility policy."""

from typing import Any, Mapping

from gpt2giga.common.client_params import ClientCompatibilityError, ClientParamStatus
from gpt2giga.common.tools import normalize_gigachat_builtin_tool_type

OPENAI_GIGACHAT_ADDITIONAL_FIELD_KEYS = frozenset(
    {
        "flags",
        "function_ranker",
        "profanity_check",
        "repetition_penalty",
        "storage",
        "update_interval",
    }
)

OPENAI_ACCEPTED_IGNORED_PARAMS = frozenset(
    {
        "audio",
        "background",
        "conversation",
        "frequency_penalty",
        "include",
        "logit_bias",
        "logprobs",
        "max_tool_calls",
        "metadata",
        "modalities",
        "n",
        "parallel_tool_calls",
        "prediction",
        "presence_penalty",
        "previous_response_id",
        "prompt_cache_key",
        "prompt_cache_retention",
        "safety_identifier",
        "seed",
        "service_tier",
        "store",
        "top_logprobs",
        "truncation",
        "user",
        "web_search_options",
    }
)

OPENAI_COMMON_SUPPORTED_PARAMS = frozenset(
    {
        "additional_fields",
        "extra_body",
        "extra_headers",
        "extra_query",
        "function_call",
        "functions",
        "max_output_tokens",
        "max_tokens",
        "model",
        "reasoning",
        "reasoning_effort",
        "response_format",
        "stop",
        "stream",
        "temperature",
        "tool_choice",
        "tools",
        "top_p",
    }
)

OPENAI_CHAT_SUPPORTED_PARAMS = OPENAI_COMMON_SUPPORTED_PARAMS | frozenset(
    {
        "max_completion_tokens",
        "messages",
    }
)

OPENAI_RESPONSES_SUPPORTED_PARAMS = OPENAI_COMMON_SUPPORTED_PARAMS | frozenset(
    {
        "input",
        "instructions",
        "text",
    }
)


def classify_openai_chat_parameter(name: str) -> ClientParamStatus:
    """Classify a Chat Completions request parameter."""
    return _classify_openai_parameter(name, OPENAI_CHAT_SUPPORTED_PARAMS)


def classify_openai_responses_parameter(name: str) -> ClientParamStatus:
    """Classify a Responses API request parameter."""
    return _classify_openai_parameter(name, OPENAI_RESPONSES_SUPPORTED_PARAMS)


def sanitize_openai_chat_parameters(
    data: Mapping[str, Any],
    *,
    allow_builtin_tools: bool = False,
    allow_namespace_tools: bool = False,
) -> dict[str, Any]:
    """Return a sanitized Chat Completions payload or raise compatibility errors."""
    sanitized = dict(data)
    _sanitize_openai_payload(sanitized, OPENAI_CHAT_SUPPORTED_PARAMS)
    _normalize_gigachat_extra_fields(sanitized)
    _sanitize_tools(
        sanitized,
        allow_builtin_tools=allow_builtin_tools,
        allow_namespace_tools=allow_namespace_tools,
        allow_function_like_tools=allow_namespace_tools,
    )
    _sanitize_functions(sanitized)
    _apply_tool_choice_policy(sanitized, allow_builtin_tools=allow_builtin_tools)
    return sanitized


def sanitize_openai_responses_parameters(
    data: Mapping[str, Any],
    *,
    allow_builtin_tools: bool = False,
    allow_stateful: bool = False,
) -> dict[str, Any]:
    """Return a sanitized Responses API payload or raise compatibility errors."""
    sanitized = dict(data)
    _sanitize_openai_payload(
        sanitized,
        OPENAI_RESPONSES_SUPPORTED_PARAMS,
        allow_stateful_responses=allow_stateful,
    )
    _normalize_gigachat_extra_fields(sanitized)
    _sanitize_tools(
        sanitized,
        allow_builtin_tools=allow_builtin_tools,
        allow_namespace_tools=True,
        allow_function_like_tools=True,
    )
    _sanitize_functions(sanitized)
    _apply_tool_choice_policy(sanitized, allow_builtin_tools=allow_builtin_tools)
    return sanitized


def _classify_openai_parameter(
    name: str, supported_params: frozenset[str]
) -> ClientParamStatus:
    if name in supported_params or name in OPENAI_GIGACHAT_ADDITIONAL_FIELD_KEYS:
        return ClientParamStatus.SUPPORTED
    if name in OPENAI_ACCEPTED_IGNORED_PARAMS:
        return ClientParamStatus.ACCEPTED_IGNORED
    return ClientParamStatus.SUPPORTED


def _merge_unknown_extra_fields(
    data: dict[str, Any], extra_fields: dict[str, Any]
) -> None:
    if not extra_fields:
        return

    extra_body = data.get("extra_body")
    if extra_body is None:
        data["extra_body"] = extra_fields
    elif isinstance(extra_body, Mapping):
        data["extra_body"] = {**extra_fields, **dict(extra_body)}


def _pop_unknown_as_extra_field(
    data: dict[str, Any],
    name: str,
    extra_fields: dict[str, Any],
) -> None:
    extra_fields[name] = data.pop(name)


def _sanitize_openai_payload(
    data: dict[str, Any],
    supported_params: frozenset[str],
    *,
    allow_stateful_responses: bool = False,
) -> None:
    extra_fields: dict[str, Any] = {}
    for name in list(data):
        if name in OPENAI_ACCEPTED_IGNORED_PARAMS:
            if name == "previous_response_id" and allow_stateful_responses:
                if data.get(name) is None:
                    data.pop(name, None)
                continue
            if name == "store" and allow_stateful_responses:
                _sanitize_store(data, allow_true=True)
                continue
            data.pop(name, None)
            continue

        if name in supported_params or name in OPENAI_GIGACHAT_ADDITIONAL_FIELD_KEYS:
            continue

        _pop_unknown_as_extra_field(data, name, extra_fields)

    _merge_unknown_extra_fields(data, extra_fields)


def _sanitize_store(data: dict[str, Any], *, allow_true: bool = False) -> None:
    value = data.get("store")
    if allow_true:
        if value is None:
            data.pop("store", None)
            return
        if isinstance(value, bool):
            return
        data.pop("store", None)
        return

    value = data.pop("store", None)
    if value is True:
        return


def _normalize_gigachat_extra_fields(data: dict[str, Any]) -> None:
    sdk_style_fields = {}
    for key in OPENAI_GIGACHAT_ADDITIONAL_FIELD_KEYS:
        if key in data:
            sdk_style_fields[key] = data.pop(key)

    extra_body = data.get("extra_body")
    if extra_body is None:
        if sdk_style_fields:
            data["extra_body"] = sdk_style_fields
        return

    if not isinstance(extra_body, Mapping):
        _raise_openai_param_error(
            "extra_body",
            "`extra_body` must be an object.",
        )

    data["extra_body"] = {**sdk_style_fields, **dict(extra_body)}


def _apply_tool_choice_policy(
    data: dict[str, Any], *, allow_builtin_tools: bool = False
) -> None:
    if "tool_choice" not in data:
        return

    tool_choice = data.pop("tool_choice")
    if tool_choice in (None, "auto"):
        return
    if tool_choice == "none":
        data.pop("tools", None)
        data.pop("functions", None)
        return
    if isinstance(tool_choice, Mapping):
        choice_type = tool_choice.get("type")
        if choice_type == "auto":
            return
        if choice_type == "none":
            data.pop("tools", None)
            data.pop("functions", None)
            return
        if choice_type == "function":
            function = tool_choice.get("function")
            if isinstance(function, Mapping) and function.get("name"):
                data["function_call"] = {"name": function["name"]}
                return
            if tool_choice.get("name"):
                data["function_call"] = {"name": tool_choice["name"]}
                return
        builtin_tool_name = (
            normalize_gigachat_builtin_tool_type(choice_type)
            if allow_builtin_tools
            else None
        )
        if builtin_tool_name:
            data["_gpt2giga_tool_config"] = {
                "mode": "tool",
                "tool_name": builtin_tool_name,
            }
            return
        return


def _sanitize_tools(
    data: dict[str, Any],
    *,
    allow_builtin_tools: bool = False,
    allow_namespace_tools: bool = False,
    allow_function_like_tools: bool = False,
) -> None:
    tools = data.get("tools")
    if tools is None:
        return
    if not isinstance(tools, list):
        data.pop("tools", None)
        return

    sanitized_tools = []
    for tool in tools:
        if not isinstance(tool, Mapping):
            continue
        tool_type = tool.get("type")
        if tool_type is None and allow_function_like_tools:
            if _is_function_like_tool(tool):
                sanitized_tools.append(dict(tool))
            continue
        if tool_type == "namespace" and allow_namespace_tools:
            namespace_tool = _sanitize_namespace_tool(
                tool,
                allow_function_like_tools=allow_function_like_tools,
            )
            if namespace_tool:
                sanitized_tools.append(namespace_tool)
            continue
        if normalize_gigachat_builtin_tool_type(tool_type) is not None:
            if allow_builtin_tools:
                sanitized_tools.append(dict(tool))
            continue
        if tool_type == "function" and _is_function_tool(tool):
            sanitized_tools.append(dict(tool))

    if sanitized_tools:
        data["tools"] = sanitized_tools
    else:
        data.pop("tools", None)


def _sanitize_namespace_tool(
    tool: Mapping[str, Any],
    *,
    allow_function_like_tools: bool = False,
) -> dict[str, Any] | None:
    name = tool.get("name")
    if not isinstance(name, str) or not name:
        return None

    nested_tools = tool.get("tools")
    if not isinstance(nested_tools, list):
        return None

    sanitized_nested_tools = []
    for nested_tool in nested_tools:
        if not isinstance(nested_tool, Mapping):
            continue
        nested_type = nested_tool.get("type")
        if nested_type is None and allow_function_like_tools:
            if _is_function_like_tool(nested_tool):
                sanitized_nested_tools.append(dict(nested_tool))
            continue
        if nested_type == "function" and _is_function_tool(nested_tool):
            sanitized_nested_tools.append(dict(nested_tool))

    if not sanitized_nested_tools:
        return None

    sanitized_tool = dict(tool)
    sanitized_tool["tools"] = sanitized_nested_tools
    return sanitized_tool


def _sanitize_functions(data: dict[str, Any]) -> None:
    functions = data.get("functions")
    if functions is None:
        return
    if not isinstance(functions, list):
        data.pop("functions", None)
        return

    sanitized_functions = [
        dict(function)
        for function in functions
        if isinstance(function, Mapping) and _is_non_empty_string(function.get("name"))
    ]
    if sanitized_functions:
        data["functions"] = sanitized_functions
    else:
        data.pop("functions", None)


def _is_function_tool(tool: Mapping[str, Any]) -> bool:
    function = tool.get("function")
    if isinstance(function, Mapping):
        return _is_non_empty_string(function.get("name"))
    return _is_function_like_tool(tool)


def _is_function_like_tool(tool: Mapping[str, Any]) -> bool:
    name = tool.get("name")
    if not _is_non_empty_string(name):
        return False
    return "parameters" in tool or "input_schema" in tool


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _raise_openai_param_error(param: str, message: str) -> None:
    raise ClientCompatibilityError(message, provider="openai", param=param)
