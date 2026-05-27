"""Anthropic Messages request parameter compatibility policy."""

from typing import Any, Mapping

from gpt2giga.common.client_params import ClientCompatibilityError, ClientParamStatus
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
        "metadata",
        "service_tier",
        "top_k",
    }
)

ANTHROPIC_REJECTED_PARAMS = {
    "container": "Anthropic containers are not supported.",
    "context_management": "Stateful context management is not supported.",
    "mcp_servers": "MCP server tools are not supported.",
}


def classify_anthropic_messages_parameter(name: str) -> ClientParamStatus:
    """Classify an Anthropic Messages request parameter."""
    if name in ANTHROPIC_MESSAGES_SUPPORTED_PARAMS:
        return ClientParamStatus.SUPPORTED
    if name in OPENAI_GIGACHAT_ADDITIONAL_FIELD_KEYS:
        return ClientParamStatus.SUPPORTED
    if name in ANTHROPIC_ACCEPTED_IGNORED_PARAMS:
        return ClientParamStatus.ACCEPTED_IGNORED
    return ClientParamStatus.REJECTED


def sanitize_anthropic_messages_parameters(data: Mapping[str, Any]) -> dict[str, Any]:
    """Return a sanitized Anthropic Messages payload or raise compatibility errors."""
    sanitized = dict(data)
    _sanitize_top_level_params(sanitized)
    _normalize_gigachat_extra_fields(sanitized)
    _validate_tool_choice(sanitized.get("tool_choice"))
    _validate_tools(sanitized.get("tools"))
    return sanitized


def _sanitize_top_level_params(data: dict[str, Any]) -> None:
    for name in list(data):
        if name in ANTHROPIC_ACCEPTED_IGNORED_PARAMS:
            data.pop(name, None)
            continue

        if name in ANTHROPIC_REJECTED_PARAMS:
            value = data.pop(name, None)
            if value is not None:
                _raise_anthropic_param_error(name, ANTHROPIC_REJECTED_PARAMS[name])
            continue

        if name in ANTHROPIC_MESSAGES_SUPPORTED_PARAMS:
            continue

        if name in OPENAI_GIGACHAT_ADDITIONAL_FIELD_KEYS:
            continue

        _raise_anthropic_param_error(
            name,
            f"Unsupported Anthropic request parameter: `{name}`.",
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
        _raise_anthropic_param_error(
            "extra_body",
            "`extra_body` must be an object with allowlisted GigaChat fields.",
        )

    unsupported_keys = sorted(
        key for key in extra_body if key not in OPENAI_GIGACHAT_ADDITIONAL_FIELD_KEYS
    )
    if unsupported_keys:
        unsupported = ", ".join(f"`{key}`" for key in unsupported_keys)
        _raise_anthropic_param_error(
            "extra_body",
            f"Unsupported `extra_body` field(s): {unsupported}.",
        )

    data["extra_body"] = {**sdk_style_fields, **dict(extra_body)}


def _validate_tool_choice(tool_choice: Any) -> None:
    if tool_choice is None:
        return
    if not isinstance(tool_choice, Mapping):
        _raise_anthropic_param_error("tool_choice", "`tool_choice` must be an object.")
    tool_choice_type = tool_choice.get("type")
    if tool_choice_type in {"auto", "none", "tool"}:
        return
    _raise_anthropic_param_error(
        "tool_choice",
        "Only `auto`, `none`, and forced `tool` choices are supported.",
    )


def _validate_tools(tools: Any) -> None:
    if tools is None:
        return
    if not isinstance(tools, list):
        _raise_anthropic_param_error("tools", "`tools` must be an array.")

    for index, tool in enumerate(tools):
        if not isinstance(tool, Mapping):
            _raise_anthropic_param_error(
                "tools", f"`tools[{index}]` must be an object."
            )
        tool_type = tool.get("type")
        if tool_type not in (None, "custom"):
            _raise_anthropic_param_error(
                "tools",
                "Only local function tools with `input_schema` are supported.",
            )
        if "name" not in tool or "input_schema" not in tool:
            _raise_anthropic_param_error(
                "tools",
                "Only local function tools with `name` and `input_schema` are supported.",
            )


def _raise_anthropic_param_error(param: str, message: str) -> None:
    raise ClientCompatibilityError(message, provider="anthropic", param=param)
