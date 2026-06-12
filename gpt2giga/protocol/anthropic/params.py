"""Anthropic Messages request parameter compatibility policy."""

from typing import Any, Mapping

from gpt2giga.common.client_params import ClientCompatibilityError, ClientParamStatus
from gpt2giga.common.json_schema import normalize_tool_parameters_schema
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
    validate_anthropic_content_blocks(
        sanitized.get("system"), sanitized.get("messages")
    )
    return sanitized


def validate_anthropic_content_blocks(system: Any, messages: Any) -> None:
    """Validate Anthropic request content blocks against the supported matrix."""
    _validate_system_content_blocks(system)

    if not isinstance(messages, list):
        return

    for message_index, message in enumerate(messages):
        if not isinstance(message, Mapping):
            continue
        role = message.get("role", "user")
        content = message.get("content")
        if not isinstance(content, list):
            continue

        if role == "user":
            allowed = frozenset({"text", "image", "tool_result"})
        elif role == "assistant":
            allowed = frozenset({"text", "tool_use"})
        else:
            continue

        for block_index, block in enumerate(content):
            _validate_content_block(
                block,
                allowed,
                path=f"messages[{message_index}].content[{block_index}]",
            )


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
        if tool_type not in (None, "custom"):
            continue
        if not _is_non_empty_string(tool.get("name")):
            continue
        sanitized_tool = dict(tool)
        if not isinstance(sanitized_tool.get("input_schema"), Mapping):
            sanitized_tool["input_schema"] = {"type": "object", "properties": {}}
        else:
            sanitized_tool["input_schema"] = normalize_tool_parameters_schema(
                sanitized_tool["input_schema"]
            )
        sanitized_tools.append(sanitized_tool)

    if sanitized_tools:
        data["tools"] = sanitized_tools
    else:
        data.pop("tools", None)


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _validate_system_content_blocks(system: Any) -> None:
    if system is None or isinstance(system, str):
        return
    if not isinstance(system, list):
        return

    for block_index, block in enumerate(system):
        _validate_content_block(
            block,
            frozenset({"text"}),
            path=f"system[{block_index}]",
        )


def _validate_content_block(
    block: Any,
    allowed_types: frozenset[str],
    *,
    path: str,
) -> None:
    if not isinstance(block, Mapping):
        return

    block_type = block.get("type")
    if block_type not in allowed_types:
        return

    if block_type == "text":
        _validate_text_block(block, path)
    elif block_type == "image":
        _validate_image_block(block, path)
    elif block_type == "tool_use":
        _validate_tool_use_block(block, path)
    elif block_type == "tool_result":
        _validate_tool_result_block(block, path)


def _validate_text_block(_block: Mapping[str, Any], _path: str) -> None:
    return


def _validate_image_block(block: Mapping[str, Any], path: str) -> None:
    source = block.get("source")
    if not isinstance(source, Mapping):
        return

    source_type = source.get("type")
    if source_type not in {"base64", "url"}:
        return


def _validate_tool_use_block(_block: Mapping[str, Any], _path: str) -> None:
    return


def _validate_tool_result_block(block: Mapping[str, Any], path: str) -> None:
    content = block.get("content")
    if not isinstance(content, list):
        return

    for part_index, part in enumerate(content):
        _validate_content_block(
            part,
            frozenset({"text"}),
            path=f"{path}.content[{part_index}]",
        )


def _raise_anthropic_param_error(param: str, message: str) -> None:
    raise ClientCompatibilityError(message, provider="anthropic", param=param)
