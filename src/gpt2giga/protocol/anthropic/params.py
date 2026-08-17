"""Anthropic Messages request parameter compatibility policy."""

from collections.abc import Mapping
from typing import Any

from gpt2giga.common.client_params import ClientCompatibilityError, ClientParamStatus
from gpt2giga.common.tools import normalize_gigachat_builtin_tool_type
from gpt2giga.protocol.request.params import OPENAI_GIGACHAT_ADDITIONAL_FIELD_KEYS

ANTHROPIC_MESSAGES_SUPPORTED_PARAMS = frozenset(
    {
        "extra_body",
        "extra_headers",
        "extra_query",
        "max_tokens",
        "messages",
        "model",
        "output_config",
        "output_format",
        "stop_sequences",
        "stream",
        "system",
        "temperature",
        "thinking",
        "tool_choice",
        "tools",
        "top_p",
    }
)

ANTHROPIC_ACCEPTED_IGNORED_PARAMS = frozenset(
    {
        "anthropic-beta",
        "betas",
        "container",
        "context_management",
        "mcp_servers",
        "metadata",
        "service_tier",
        "top_k",
    }
)
_ANTHROPIC_NAMED_BUILTIN_TOOLS = frozenset(
    {
        "WebSearch",
        "WebFetch",
        "CodeExecution",
    }
)


def classify_anthropic_messages_parameter(name: str) -> ClientParamStatus:
    """Classify an Anthropic Messages request parameter."""
    if name in ANTHROPIC_MESSAGES_SUPPORTED_PARAMS:
        return ClientParamStatus.SUPPORTED
    if name in OPENAI_GIGACHAT_ADDITIONAL_FIELD_KEYS:
        return ClientParamStatus.SUPPORTED
    if name in ANTHROPIC_ACCEPTED_IGNORED_PARAMS:
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


def sanitize_anthropic_messages_parameters(data: Mapping[str, Any]) -> dict[str, Any]:
    """Return a sanitized Anthropic Messages payload or raise compatibility errors."""
    sanitized = dict(data)
    _sanitize_top_level_params(sanitized)
    _normalize_gigachat_extra_fields(sanitized)
    _sanitize_tool_choice(sanitized)
    _sanitize_tools(sanitized)
    return sanitized


def _sanitize_top_level_params(data: dict[str, Any]) -> None:
    extra_fields: dict[str, Any] = {}
    for name in list(data):
        if name in ANTHROPIC_ACCEPTED_IGNORED_PARAMS:
            data.pop(name, None)
            continue

        if name in ANTHROPIC_MESSAGES_SUPPORTED_PARAMS:
            continue

        if name in OPENAI_GIGACHAT_ADDITIONAL_FIELD_KEYS:
            continue

        _pop_unknown_as_extra_field(data, name, extra_fields)

    _merge_unknown_extra_fields(data, extra_fields)


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
        _raise_anthropic_param_error(
            "extra_body",
            "`extra_body` must be an object.",
        )

    data["extra_body"] = {**sdk_style_fields, **dict(extra_body)}


def _sanitize_tool_choice(data: dict[str, Any]) -> None:
    tool_choice = data.get("tool_choice")
    if tool_choice is None:
        return
    if not isinstance(tool_choice, Mapping):
        data.pop("tool_choice", None)
        return
    tool_choice_type = tool_choice.get("type")
    if tool_choice_type in {"auto", "none"}:
        return
    if tool_choice_type == "tool":
        if _is_non_empty_string(tool_choice.get("name")):
            return
        data.pop("tool_choice", None)
        return
    data.pop("tool_choice", None)


def _sanitize_tools(data: dict[str, Any]) -> None:
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
        if normalize_gigachat_builtin_tool_type(tool_type) is not None:
            sanitized_tools.append(dict(tool))
            continue
        if tool_type in (None, "custom") and tool.get("name") in (
            _ANTHROPIC_NAMED_BUILTIN_TOOLS
        ):
            sanitized_tools.append(dict(tool))
            continue
        if tool_type not in (None, "custom"):
            continue
        if not _is_non_empty_string(tool.get("name")):
            continue
        sanitized_tool = dict(tool)
        if not isinstance(sanitized_tool.get("input_schema"), Mapping):
            parameters = sanitized_tool.get("parameters")
            if isinstance(parameters, Mapping):
                sanitized_tool["input_schema"] = parameters
        if not isinstance(sanitized_tool.get("input_schema"), Mapping):
            sanitized_tool["input_schema"] = {"type": "object", "properties": {}}
        else:
            sanitized_tool["input_schema"] = dict(sanitized_tool["input_schema"])
        sanitized_tools.append(sanitized_tool)

    if sanitized_tools:
        data["tools"] = sanitized_tools
    else:
        data.pop("tools", None)


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _raise_anthropic_param_error(param: str, message: str) -> None:
    raise ClientCompatibilityError(message, provider="anthropic", param=param)
