"""Anthropic transport adapter over canonical internal contracts."""

from __future__ import annotations

import json
import uuid
from copy import deepcopy
from typing import Any

from gpt2giga.api.anthropic.request import _extract_tool_definitions_text
from gpt2giga.core.contracts import (
    NormalizedChatRequest,
    NormalizedMessage,
    NormalizedTool,
)
from gpt2giga.providers.gigachat.content_utils import ensure_json_object_str
from gpt2giga.providers.gigachat.tool_mapping import convert_tool_to_giga_functions


def _build_normalized_tools(payload: dict[str, Any]) -> list[NormalizedTool]:
    tools = payload.get("tools")
    if not isinstance(tools, list):
        return []
    return [
        NormalizedTool(
            name=str(tool.get("name", "")),
            description=tool.get("description"),
            parameters=tool.get("input_schema", {"type": "object", "properties": {}}),
            raw={
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": tool.get(
                        "input_schema", {"type": "object", "properties": {}}
                    ),
                },
            },
        )
        for tool in tools
        if isinstance(tool, dict)
    ]


def _build_system_messages(system: Any) -> list[NormalizedMessage]:
    if not system:
        return []
    if isinstance(system, str):
        return [NormalizedMessage(role="system", content=system)]
    if isinstance(system, list):
        texts = [
            block.get("text", "")
            for block in system
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        if texts:
            return [NormalizedMessage(role="system", content="\n".join(texts))]
    return []


def _convert_assistant_content(
    content_blocks: list[dict[str, Any]],
) -> list[NormalizedMessage]:
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []

    for block in content_blocks:
        block_type = block.get("type")
        if block_type == "text":
            text_parts.append(block.get("text", ""))
        elif block_type == "tool_use":
            tool_calls.append(
                {
                    "id": block.get("id", f"call_{uuid.uuid4()}"),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(
                            block.get("input", {}),
                            ensure_ascii=False,
                        ),
                    },
                }
            )

    return [
        NormalizedMessage(
            role="assistant",
            content="\n".join(text_parts) if text_parts else "",
            tool_calls=tool_calls,
        )
    ]


def _convert_user_content(
    content_blocks: list[dict[str, Any]],
    *,
    tool_use_names: dict[str, str],
) -> list[NormalizedMessage]:
    text_parts: list[str] = []
    content_parts: list[dict[str, Any]] = []
    normalized_messages: list[NormalizedMessage] = []
    has_images = False

    for block in content_blocks:
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text", "")
            text_parts.append(text)
            content_parts.append({"type": "text", "text": text})
            continue

        if block_type == "image":
            has_images = True
            source = block.get("source", {})
            if source.get("type") == "base64":
                media_type = source.get("media_type", "image/png")
                data = source.get("data", "")
                content_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{data}"},
                    }
                )
            elif source.get("type") == "url":
                content_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": source.get("url", "")},
                    }
                )
            continue

        if block_type == "tool_result":
            result_content = block.get("content", "")
            if isinstance(result_content, list):
                text_items = [
                    part.get("text", "")
                    for part in result_content
                    if isinstance(part, dict) and part.get("type") == "text"
                ]
                result_content = "\n".join(text_items)
            tool_use_id = str(block.get("tool_use_id", ""))
            normalized_messages.append(
                NormalizedMessage(
                    role="tool",
                    name=tool_use_names.get(tool_use_id, ""),
                    tool_call_id=tool_use_id,
                    content=ensure_json_object_str(result_content),
                )
            )

    if has_images and content_parts:
        normalized_messages.insert(
            0,
            NormalizedMessage(role="user", content=content_parts),
        )
    elif text_parts:
        normalized_messages.insert(
            0,
            NormalizedMessage(role="user", content="\n".join(text_parts)),
        )

    return normalized_messages


def _build_normalized_messages(
    system: Any,
    messages: list[dict[str, Any]],
) -> list[NormalizedMessage]:
    normalized_messages = _build_system_messages(system)
    tool_use_names: dict[str, str] = {}

    for message in messages:
        if not isinstance(message, dict):
            continue

        role = str(message.get("role", "user"))
        content = message.get("content", "")

        if isinstance(content, str):
            normalized_messages.append(NormalizedMessage(role=role, content=content))
            continue

        if not isinstance(content, list):
            normalized_messages.append(
                NormalizedMessage(role=role, content=str(content))
            )
            continue

        if role == "assistant":
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_use_names[str(block.get("id", ""))] = str(
                        block.get("name", "")
                    )
            normalized_messages.extend(_convert_assistant_content(content))
            continue

        if role == "user":
            normalized_messages.extend(
                _convert_user_content(content, tool_use_names=tool_use_names)
            )
            continue

        normalized_messages.append(NormalizedMessage(role=role, content=str(content)))

    return normalized_messages


def _thinking_to_reasoning_effort(thinking: Any) -> str | None:
    if not isinstance(thinking, dict) or thinking.get("type") != "enabled":
        return None

    budget = thinking.get("budget_tokens", 10000)
    if budget >= 8000:
        return "high"
    if budget >= 3000:
        return "medium"
    return "low"


def build_normalized_chat_request(
    payload: dict[str, Any],
    *,
    logger: Any = None,
) -> NormalizedChatRequest:
    """Build a canonical internal request from an Anthropic Messages payload."""
    request_payload = dict(payload)
    tools = _build_normalized_tools(request_payload)
    tool_choice = request_payload.get("tool_choice")
    tool_choice_type = (
        str(tool_choice.get("type", "")) if isinstance(tool_choice, dict) else ""
    )
    if tool_choice_type == "none":
        tools = []

    options: dict[str, Any] = {}
    if "max_tokens" in request_payload:
        options["max_tokens"] = request_payload["max_tokens"]
    if "temperature" in request_payload:
        options["temperature"] = request_payload["temperature"]
    if "top_p" in request_payload:
        options["top_p"] = request_payload["top_p"]
    if "stop_sequences" in request_payload:
        options["stop"] = request_payload["stop_sequences"]

    reasoning_effort = _thinking_to_reasoning_effort(request_payload.get("thinking"))
    if reasoning_effort is not None:
        options["reasoning_effort"] = reasoning_effort

    if tools:
        tool_payload = {"tools": [tool.to_openai_tool() for tool in tools]}
        options["functions"] = convert_tool_to_giga_functions(tool_payload)
        if logger is not None:
            logger.debug(f"Functions count: {len(options['functions'])}")

    if tool_choice_type == "tool" and isinstance(tool_choice, dict):
        tool_name = tool_choice.get("name")
        if isinstance(tool_name, str) and tool_name:
            options["function_call"] = {"name": tool_name}

    return NormalizedChatRequest(
        model=str(request_payload.get("model", "unknown")),
        messages=_build_normalized_messages(
            request_payload.get("system"),
            request_payload.get("messages", []),
        ),
        stream=bool(request_payload.get("stream", False)),
        tools=tools,
        options=options,
    )


def build_token_count_texts(payload: dict[str, Any]) -> list[str]:
    """Extract token-count text inputs from an Anthropic Messages payload."""
    request = build_normalized_chat_request(payload)
    texts: list[str] = []

    for message in request.messages:
        content = message.content
        if isinstance(content, str):
            if content:
                texts.append(content)
            continue
        if isinstance(content, list):
            texts.extend(
                part.get("text", "")
                for part in content
                if isinstance(part, dict)
                and part.get("type") == "text"
                and isinstance(part.get("text"), str)
                and part.get("text")
            )

    if isinstance(payload.get("tools"), list):
        texts.extend(_extract_tool_definitions_text(payload["tools"]))

    return texts


def serialize_normalized_chat_request(
    request: NormalizedChatRequest,
) -> tuple[dict[str, Any], list[str]]:
    """Render a canonical chat request as an Anthropic Messages payload."""
    system_texts: list[str] = []
    messages: list[dict[str, Any]] = []

    for message in request.messages:
        if message.role == "system":
            system_text = _stringify_message_content(message.content)
            if system_text:
                system_texts.append(system_text)
            continue

        if message.role == "assistant":
            blocks = _assistant_message_to_anthropic_blocks(message)
            _append_anthropic_message(messages, role="assistant", content=blocks)
            continue

        if message.role == "user":
            blocks = _user_message_to_anthropic_blocks(message)
            _append_anthropic_message(messages, role="user", content=blocks)
            continue

        if message.role in {"tool", "function"}:
            _append_anthropic_message(
                messages,
                role="user",
                content=[_tool_message_to_anthropic_block(message)],
            )
            continue

        text = _stringify_message_content(message.content)
        if text:
            _append_anthropic_message(
                messages,
                role=message.role,
                content=[{"type": "text", "text": text}],
            )

    payload: dict[str, Any] = {
        "model": request.model,
        "messages": messages,
    }
    warnings: list[str] = []

    if system_texts:
        payload["system"] = "\n\n".join(system_texts)
    if request.stream:
        payload["stream"] = True

    _set_if_present(payload, "max_tokens", request.options, "max_tokens")
    _set_if_present(payload, "temperature", request.options, "temperature")
    _set_if_present(payload, "top_p", request.options, "top_p")

    stop_sequences = request.options.get("stop")
    if stop_sequences is not None:
        payload["stop_sequences"] = deepcopy(stop_sequences)

    reasoning_effort = request.options.get("reasoning_effort")
    if reasoning_effort in {"low", "medium", "high"}:
        budget_tokens = {"low": 1024, "medium": 4000, "high": 10000}[reasoning_effort]
        payload["thinking"] = {
            "type": "enabled",
            "budget_tokens": budget_tokens,
        }

    if request.tools:
        payload["tools"] = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": deepcopy(tool.parameters),
            }
            for tool in request.tools
        ]

    function_call = request.options.get("function_call")
    if isinstance(function_call, dict):
        tool_name = function_call.get("name")
        if isinstance(tool_name, str) and tool_name:
            payload["tool_choice"] = {"type": "tool", "name": tool_name}

    ignored_options = sorted(
        set(request.options)
        - {
            "function_call",
            "functions",
            "max_tokens",
            "reasoning_effort",
            "stop",
            "temperature",
            "top_p",
        }
    )
    if ignored_options:
        warnings.append(
            "Anthropic translation ignored unsupported options: "
            + ", ".join(ignored_options)
        )

    return payload, warnings


def _append_anthropic_message(
    messages: list[dict[str, Any]],
    *,
    role: str,
    content: list[dict[str, Any]],
) -> None:
    if not content:
        return
    if messages and messages[-1]["role"] == role:
        messages[-1]["content"].extend(content)
        return
    messages.append({"role": role, "content": content})


def _assistant_message_to_anthropic_blocks(
    message: NormalizedMessage,
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    text = _stringify_message_content(message.content)
    if text:
        blocks.append({"type": "text", "text": text})

    for tool_call in message.tool_calls:
        if not isinstance(tool_call, dict):
            continue
        function = tool_call.get("function")
        if not isinstance(function, dict):
            continue
        blocks.append(
            {
                "type": "tool_use",
                "id": tool_call.get("id", f"call_{uuid.uuid4()}"),
                "name": function.get("name", ""),
                "input": _decode_json_object(function.get("arguments")),
            }
        )

    return blocks


def _user_message_to_anthropic_blocks(
    message: NormalizedMessage,
) -> list[dict[str, Any]]:
    content = message.content
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if not isinstance(content, list):
        text = _stringify_message_content(content)
        return [{"type": "text", "text": text}] if text else []

    blocks: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        part_type = part.get("type")
        if part_type == "text":
            part_text: Any = part.get("text")
            if isinstance(part_text, str) and part_text:
                blocks.append({"type": "text", "text": part_text})
            continue
        if part_type == "image_url":
            image_url = part.get("image_url")
            if not isinstance(image_url, dict):
                continue
            url = image_url.get("url")
            if not isinstance(url, str) or not url:
                continue
            source = _image_url_to_anthropic_source(url)
            if source is not None:
                blocks.append({"type": "image", "source": source})
            continue
        raise ValueError(f"Unsupported Anthropic content part type: {part_type}")
    return blocks


def _tool_message_to_anthropic_block(
    message: NormalizedMessage,
) -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool_use_id": message.tool_call_id or f"toolu_{uuid.uuid4()}",
        "content": _decode_json_value(message.content),
    }


def _image_url_to_anthropic_source(url: str) -> dict[str, Any] | None:
    if url.startswith("data:") and ";base64," in url:
        prefix, data = url.split(",", 1)
        media_type = prefix[5:].split(";", 1)[0] or "image/png"
        return {
            "type": "base64",
            "media_type": media_type,
            "data": data,
        }
    return {"type": "url", "url": url}


def _stringify_message_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [
            part.get("text", "")
            for part in content
            if isinstance(part, dict)
            and part.get("type") == "text"
            and isinstance(part.get("text"), str)
        ]
        return "\n".join(text for text in texts if text)
    if content is None:
        return ""
    return str(content)


def _decode_json_object(value: Any) -> dict[str, Any]:
    decoded = _decode_json_value(value)
    if isinstance(decoded, dict):
        return decoded
    return {"value": decoded}


def _decode_json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return deepcopy(value)
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _set_if_present(
    payload: dict[str, Any],
    payload_key: str,
    options: dict[str, Any],
    option_key: str,
) -> None:
    value = options.get(option_key)
    if value is not None:
        payload[payload_key] = deepcopy(value)
