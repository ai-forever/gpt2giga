"""Anthropic request conversion helpers."""

import json
import uuid
from typing import Any, Optional

from gpt2giga.providers.gigachat.content_utils import ensure_json_object_str
from gpt2giga.providers.gigachat.tool_mapping import convert_tool_to_giga_functions


def _convert_anthropic_tools_to_openai(tools: list[dict]) -> list[dict]:
    """Convert Anthropic tool definitions to OpenAI format."""
    openai_tools: list[dict] = []
    for tool in tools:
        openai_tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get(
                        "input_schema", {"type": "object", "properties": {}}
                    ),
                },
            }
        )
    return openai_tools


def _convert_anthropic_messages_to_openai(
    system: Optional[Any],
    messages: list[dict],
) -> list[dict]:
    """Convert Anthropic messages to OpenAI messages format."""
    openai_messages: list[dict] = []
    tool_use_names: dict[str, str] = {}

    if system:
        if isinstance(system, str):
            openai_messages.append({"role": "system", "content": system})
        elif isinstance(system, list):
            texts = [
                block.get("text", "")
                for block in system
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            if texts:
                openai_messages.append({"role": "system", "content": "\n".join(texts)})

    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")

        if isinstance(content, str):
            openai_messages.append({"role": role, "content": content})
            continue

        if not isinstance(content, list):
            openai_messages.append({"role": role, "content": str(content)})
            continue

        if role == "assistant":
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_use_names[block.get("id", "")] = block.get("name", "")
            _convert_assistant_blocks(content, openai_messages)
        elif role == "user":
            _convert_user_blocks(content, openai_messages, tool_use_names)
        else:
            openai_messages.append({"role": role, "content": str(content)})

    return openai_messages


def _convert_assistant_blocks(
    content_blocks: list[dict],
    openai_messages: list[dict],
) -> None:
    """Convert Anthropic assistant content blocks to OpenAI format."""
    text_parts: list[str] = []
    tool_uses: list[dict] = []

    for block in content_blocks:
        block_type = block.get("type")
        if block_type == "text":
            text_parts.append(block.get("text", ""))
        elif block_type == "tool_use":
            tool_uses.append(block)

    if tool_uses:
        tool_calls = [
            {
                "id": tool_use.get("id", f"call_{uuid.uuid4()}"),
                "type": "function",
                "function": {
                    "name": tool_use["name"],
                    "arguments": json.dumps(
                        tool_use.get("input", {}), ensure_ascii=False
                    ),
                },
            }
            for tool_use in tool_uses
        ]
        openai_messages.append(
            {
                "role": "assistant",
                "content": "\n".join(text_parts) if text_parts else "",
                "tool_calls": tool_calls,
            }
        )
        return

    openai_messages.append({"role": "assistant", "content": "\n".join(text_parts)})


def _convert_user_blocks(
    content_blocks: list[dict],
    openai_messages: list[dict],
    tool_use_names: Optional[dict[str, str]] = None,
) -> None:
    """Convert Anthropic user content blocks to OpenAI format."""
    text_parts: list[str] = []
    openai_content_parts: list[dict] = []
    tool_results: list[dict] = []
    has_images = False

    for block in content_blocks:
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text", "")
            text_parts.append(text)
            openai_content_parts.append({"type": "text", "text": text})
        elif block_type == "image":
            has_images = True
            source = block.get("source", {})
            if source.get("type") == "base64":
                media_type = source.get("media_type", "image/png")
                data = source.get("data", "")
                openai_content_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{data}"},
                    }
                )
            elif source.get("type") == "url":
                openai_content_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": source.get("url", "")},
                    }
                )
        elif block_type == "tool_result":
            tool_results.append(block)

    names = tool_use_names or {}
    for tool_result in tool_results:
        tool_result_content = tool_result.get("content", "")
        if isinstance(tool_result_content, list):
            parts = [
                part.get("text", "")
                for part in tool_result_content
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            tool_result_content = "\n".join(parts)
        tool_use_id = tool_result.get("tool_use_id", "")
        openai_messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_use_id,
                "name": names.get(tool_use_id, ""),
                "content": ensure_json_object_str(tool_result_content),
            }
        )

    if has_images and openai_content_parts:
        openai_messages.append({"role": "user", "content": openai_content_parts})
    elif text_parts:
        openai_messages.append({"role": "user", "content": "\n".join(text_parts)})


def _build_openai_data_from_anthropic_request(
    data: dict[str, Any],
    logger: Any,
) -> dict[str, Any]:
    """Translate an Anthropic Messages request into an OpenAI-style payload."""
    openai_data: dict[str, Any] = {
        "model": data.get("model", "unknown"),
        "messages": _convert_anthropic_messages_to_openai(
            data.get("system"), data.get("messages", [])
        ),
    }

    if "max_tokens" in data:
        openai_data["max_tokens"] = data["max_tokens"]
    if "temperature" in data:
        openai_data["temperature"] = data["temperature"]
    if "top_p" in data:
        openai_data["top_p"] = data["top_p"]
    if "stop_sequences" in data:
        openai_data["stop"] = data["stop_sequences"]

    thinking = data.get("thinking")
    if thinking and isinstance(thinking, dict) and thinking.get("type") == "enabled":
        budget = thinking.get("budget_tokens", 10000)
        if budget >= 8000:
            openai_data["reasoning_effort"] = "high"
        elif budget >= 3000:
            openai_data["reasoning_effort"] = "medium"
        else:
            openai_data["reasoning_effort"] = "low"

    if "tools" in data and data["tools"]:
        openai_data["tools"] = _convert_anthropic_tools_to_openai(data["tools"])
        openai_data["functions"] = convert_tool_to_giga_functions(openai_data)
        if logger:
            logger.debug(f"Functions count: {len(openai_data['functions'])}")

    tool_choice = data.get("tool_choice")
    if tool_choice and isinstance(tool_choice, dict):
        tool_choice_type = tool_choice.get("type")
        if tool_choice_type == "tool":
            openai_data["function_call"] = {"name": tool_choice.get("name")}
        elif tool_choice_type == "none":
            openai_data.pop("tools", None)
            openai_data.pop("functions", None)

    return openai_data


def _extract_text_from_openai_messages(messages: list[dict]) -> list[str]:
    """Extract text strings from OpenAI-formatted messages for token counting."""
    texts: list[str] = []
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            if content:
                texts.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = part.get("text", "")
                    if text:
                        texts.append(text)
        for tool_call in message.get("tool_calls", []):
            function = tool_call.get("function", {})
            name = function.get("name", "")
            arguments = function.get("arguments", "")
            if name:
                texts.append(name)
            if arguments:
                texts.append(arguments)
    return texts


def _extract_tool_definitions_text(tools: list[dict]) -> list[str]:
    """Extract text from Anthropic tool definitions for token counting."""
    texts: list[str] = []
    for tool in tools:
        parts: list[str] = []
        name = tool.get("name", "")
        if name:
            parts.append(name)
        description = tool.get("description", "")
        if description:
            parts.append(description)
        schema = tool.get("input_schema")
        if schema:
            parts.append(json.dumps(schema, ensure_ascii=False))
        if parts:
            texts.append(" ".join(parts))
    return texts
