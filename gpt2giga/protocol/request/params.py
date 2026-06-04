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
        "frequency_penalty",
        "metadata",
        "presence_penalty",
        "prompt_cache_key",
        "prompt_cache_retention",
        "safety_identifier",
        "seed",
        "service_tier",
        "user",
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

OPENAI_REJECTED_PARAMS = {
    "audio": "Audio output is not supported; only text responses are supported.",
    "background": "Background responses are not supported.",
    "conversation": "Stateful Responses conversations are not supported.",
    "include": "Responses include expansions are not supported.",
    "logit_bias": "Token logit bias is not supported by GigaChat.",
    "logprobs": "Log probabilities are not supported by GigaChat.",
    "max_tool_calls": "Limiting tool call count is not supported.",
    "prediction": "Predicted outputs are not supported.",
    "previous_response_id": "Stateful Responses continuation is not supported.",
    "top_logprobs": "Log probabilities are not supported by GigaChat.",
    "truncation": "Responses truncation controls are not supported.",
    "web_search_options": "OpenAI web search options are not supported.",
}


def classify_openai_chat_parameter(name: str) -> ClientParamStatus:
    """Classify a Chat Completions request parameter."""
    return _classify_openai_parameter(name, OPENAI_CHAT_SUPPORTED_PARAMS)


def classify_openai_responses_parameter(name: str) -> ClientParamStatus:
    """Classify a Responses API request parameter."""
    return _classify_openai_parameter(name, OPENAI_RESPONSES_SUPPORTED_PARAMS)


def sanitize_openai_chat_parameters(data: Mapping[str, Any]) -> dict[str, Any]:
    """Return a sanitized Chat Completions payload or raise compatibility errors."""
    sanitized = dict(data)
    _sanitize_openai_payload(sanitized, OPENAI_CHAT_SUPPORTED_PARAMS)
    _normalize_gigachat_extra_fields(sanitized)
    _apply_tool_choice_policy(sanitized)
    _validate_tools(sanitized.get("tools"))
    return sanitized


def sanitize_openai_responses_parameters(
    data: Mapping[str, Any], *, allow_builtin_tools: bool = False
) -> dict[str, Any]:
    """Return a sanitized Responses API payload or raise compatibility errors."""
    sanitized = dict(data)
    _sanitize_openai_payload(sanitized, OPENAI_RESPONSES_SUPPORTED_PARAMS)
    _normalize_gigachat_extra_fields(sanitized)
    _apply_tool_choice_policy(sanitized, allow_builtin_tools=allow_builtin_tools)
    _validate_tools(sanitized.get("tools"), allow_builtin_tools=allow_builtin_tools)
    return sanitized


def _classify_openai_parameter(
    name: str, supported_params: frozenset[str]
) -> ClientParamStatus:
    if name in supported_params or name in OPENAI_GIGACHAT_ADDITIONAL_FIELD_KEYS:
        return ClientParamStatus.SUPPORTED
    if name in OPENAI_ACCEPTED_IGNORED_PARAMS:
        return ClientParamStatus.ACCEPTED_IGNORED
    if name in OPENAI_REJECTED_PARAMS or name in {
        "modalities",
        "n",
        "parallel_tool_calls",
        "store",
    }:
        return ClientParamStatus.REJECTED
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
    data: dict[str, Any], supported_params: frozenset[str]
) -> None:
    extra_fields: dict[str, Any] = {}
    for name in list(data):
        if name in OPENAI_ACCEPTED_IGNORED_PARAMS:
            data.pop(name, None)
            continue

        if name in OPENAI_REJECTED_PARAMS:
            value = data.pop(name, None)
            if value is not None:
                _raise_openai_param_error(name, OPENAI_REJECTED_PARAMS[name])
            continue

        if name == "store":
            _sanitize_store(data)
            continue

        if name == "n":
            _sanitize_n(data)
            continue

        if name == "modalities":
            _sanitize_modalities(data)
            continue

        if name == "parallel_tool_calls":
            _sanitize_parallel_tool_calls(data)
            continue

        if name in supported_params or name in OPENAI_GIGACHAT_ADDITIONAL_FIELD_KEYS:
            continue

        _pop_unknown_as_extra_field(data, name, extra_fields)

    _merge_unknown_extra_fields(data, extra_fields)


def _sanitize_store(data: dict[str, Any]) -> None:
    value = data.pop("store", None)
    if value is True:
        _raise_openai_param_error(
            "store",
            "Stored completions are not supported.",
        )


def _sanitize_n(data: dict[str, Any]) -> None:
    value = data.pop("n", None)
    if value is None:
        return
    if isinstance(value, bool) or value != 1:
        _raise_openai_param_error(
            "n",
            "Multiple completion choices are not supported; use `n=1`.",
        )


def _sanitize_modalities(data: dict[str, Any]) -> None:
    value = data.pop("modalities", None)
    if value is None:
        return
    if isinstance(value, list) and set(value) == {"text"}:
        return
    _raise_openai_param_error(
        "modalities",
        "Only text output is supported; audio modalities are not supported.",
    )


def _sanitize_parallel_tool_calls(data: dict[str, Any]) -> None:
    value = data.pop("parallel_tool_calls", None)
    if value is True:
        _raise_openai_param_error(
            "parallel_tool_calls",
            "Parallel tool calls are not supported by GigaChat.",
        )


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
        _raise_openai_param_error(
            "tool_choice",
            _tool_choice_error_message(allow_builtin_tools=allow_builtin_tools),
        )
    _raise_openai_param_error(
        "tool_choice",
        _tool_choice_error_message(allow_builtin_tools=allow_builtin_tools),
    )


def _tool_choice_error_message(*, allow_builtin_tools: bool = False) -> str:
    if allow_builtin_tools:
        return (
            "Only `auto`, `none`, forced function tool choices, and supported "
            "GigaChat built-in tool choices are supported."
        )
    return "Only `auto`, `none`, and forced function tool choices are supported."


def _validate_tools(tools: Any, *, allow_builtin_tools: bool = False) -> None:
    if tools is None:
        return
    if not isinstance(tools, list):
        _raise_openai_param_error("tools", "`tools` must be an array.")
    for index, tool in enumerate(tools):
        if not isinstance(tool, Mapping):
            _raise_openai_param_error("tools", f"`tools[{index}]` must be an object.")
        tool_type = tool.get("type")
        if tool_type != "function" and not (
            allow_builtin_tools
            and normalize_gigachat_builtin_tool_type(tool_type) is not None
        ):
            message = "Only function tools are supported."
            if allow_builtin_tools:
                message = (
                    "Only function tools and supported GigaChat built-in tools "
                    "are supported."
                )
            _raise_openai_param_error(
                "tools",
                message,
            )


def _raise_openai_param_error(param: str, message: str) -> None:
    raise ClientCompatibilityError(message, provider="openai", param=param)
