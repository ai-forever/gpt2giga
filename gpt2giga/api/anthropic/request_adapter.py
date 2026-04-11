"""Anthropic transport adapter over canonical internal contracts."""

from __future__ import annotations

import json
import uuid
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

    if tool_choice_type == "tool":
        options["function_call"] = {"name": tool_choice.get("name")}

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
