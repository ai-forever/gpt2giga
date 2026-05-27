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

ANTHROPIC_SUPPORTED_REQUEST_CONTENT_BLOCKS = frozenset(
    {"text", "image", "tool_use", "tool_result"}
)
ANTHROPIC_UNSUPPORTED_CONTENT_BLOCK_MESSAGES = {
    "citation": "Anthropic citation blocks are not supported in request content.",
    "citations": "Anthropic citation blocks are not supported in request content.",
    "container_upload": "Anthropic container upload blocks are not supported.",
    "document": "Anthropic document blocks require Files API attachment mapping, which is not supported.",
    "file": "Anthropic file blocks require Files API attachment mapping, which is not supported.",
    "redacted_thinking": "Anthropic redacted thinking blocks cannot be forwarded to GigaChat.",
    "search_result": "Anthropic search result blocks are not supported.",
    "thinking": "Anthropic thinking input blocks cannot be forwarded to GigaChat.",
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
            _raise_anthropic_param_error(
                f"messages[{message_index}]",
                f"`messages[{message_index}]` must be an object.",
            )
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
    if tool_choice_type in {"auto", "none"}:
        return
    if tool_choice_type == "tool":
        if not _is_non_empty_string(tool_choice.get("name")):
            _raise_anthropic_param_error(
                "tool_choice",
                "`tool_choice.name` must be a non-empty string for forced `tool` choices.",
            )
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
        if not _is_non_empty_string(tool.get("name")) or not isinstance(
            tool.get("input_schema"), Mapping
        ):
            _raise_anthropic_param_error(
                "tools",
                "Only local function tools with non-empty `name` and object `input_schema` are supported.",
            )


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
        _raise_anthropic_param_error(path, f"`{path}` must be an object.")

    block_type = block.get("type")
    if block_type not in allowed_types:
        _raise_unsupported_content_block(block_type, path)

    if block_type == "text":
        _validate_text_block(block, path)
    elif block_type == "image":
        _validate_image_block(block, path)
    elif block_type == "tool_use":
        _validate_tool_use_block(block, path)
    elif block_type == "tool_result":
        _validate_tool_result_block(block, path)


def _validate_text_block(block: Mapping[str, Any], path: str) -> None:
    if block.get("citations"):
        _raise_anthropic_param_error(
            f"{path}.citations",
            "Anthropic citations are not supported in request content. "
            "Supported request content blocks are `text`, `image`, `tool_use`, and `tool_result`.",
        )


def _validate_image_block(block: Mapping[str, Any], path: str) -> None:
    source = block.get("source")
    if not isinstance(source, Mapping):
        _raise_anthropic_param_error(
            f"{path}.source",
            "Anthropic image blocks require a `source` object.",
        )

    source_type = source.get("type")
    if source_type not in {"base64", "url"}:
        _raise_anthropic_param_error(
            f"{path}.source.type",
            "Only Anthropic image source types `base64` and `url` are supported.",
        )


def _validate_tool_use_block(block: Mapping[str, Any], path: str) -> None:
    if not block.get("name"):
        _raise_anthropic_param_error(
            f"{path}.name",
            "Anthropic `tool_use` blocks require a `name`.",
        )


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


def _raise_unsupported_content_block(block_type: Any, path: str) -> None:
    if (
        isinstance(block_type, str)
        and block_type in ANTHROPIC_UNSUPPORTED_CONTENT_BLOCK_MESSAGES
    ):
        reason = ANTHROPIC_UNSUPPORTED_CONTENT_BLOCK_MESSAGES[block_type]
        label = f"`{block_type}`"
    elif block_type is None:
        reason = "Anthropic content blocks must include a `type` field."
        label = "missing"
    else:
        reason = f"Unsupported Anthropic content block type: `{block_type}`."
        label = f"`{block_type}`"

    _raise_anthropic_param_error(
        path,
        f"{reason} Unsupported block at `{path}`: {label}. "
        "Supported request content blocks are `text`, `image`, `tool_use`, and `tool_result`.",
    )


def _raise_anthropic_param_error(param: str, message: str) -> None:
    raise ClientCompatibilityError(message, provider="anthropic", param=param)
