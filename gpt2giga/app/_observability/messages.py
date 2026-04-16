"""Payload extraction and message normalization helpers."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from .models import RequestAuditMessage


def extract_model_from_payload(payload: Mapping[str, Any]) -> str | None:
    """Extract a normalized model identifier from a provider payload."""
    model = payload.get("model")
    if isinstance(model, str) and model:
        return model
    model_version = payload.get("modelVersion")
    if isinstance(model_version, str) and model_version:
        return model_version
    return None


def extract_usage_from_payload(
    payload: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    """Extract the provider-specific usage section from a payload."""
    if "usage" in payload and isinstance(payload.get("usage"), Mapping):
        return payload.get("usage")
    if "usageMetadata" in payload and isinstance(payload.get("usageMetadata"), Mapping):
        return payload.get("usageMetadata")
    return payload


def extract_input_observability(
    payload: Mapping[str, Any],
) -> tuple[str | None, str | None, list[RequestAuditMessage] | None]:
    """Build input summary, mime type, and normalized messages from a request."""
    if isinstance(payload.get("messages"), list):
        messages = _extract_messages_from_chat_messages(payload.get("messages"))
        messages = _prepend_system_message(messages, payload)
        return _summarize_messages(messages), "text/plain", messages or None

    input_payload = payload.get("input")
    if isinstance(input_payload, str):
        messages = _prepend_system_message(
            [{"role": "user", "content": input_payload}],
            payload,
        )
        return _summarize_messages(messages), "text/plain", messages
    if isinstance(input_payload, list):
        messages = _extract_messages_from_responses_input(input_payload)
        messages = _prepend_system_message(messages, payload)
        if messages:
            return _summarize_messages(messages), "text/plain", messages
        return _safe_json_dumps(input_payload), "application/json", None

    generate_request = payload.get("generateContentRequest")
    if isinstance(generate_request, Mapping):
        return extract_input_observability(generate_request)

    contents = payload.get("contents")
    if isinstance(contents, list):
        messages = _extract_messages_from_gemini_contents(contents)
        return _summarize_messages(messages), "text/plain", messages or None

    return None, None, None


def extract_output_observability(
    payload: Mapping[str, Any],
) -> tuple[str | None, str | None, list[RequestAuditMessage] | None]:
    """Build output summary, mime type, and normalized messages from a response."""
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        messages = _extract_messages_from_openai_choices(choices)
        if messages:
            return _summarize_messages(messages), "text/plain", messages

    output = payload.get("output")
    if isinstance(output, list) and output:
        messages = _extract_messages_from_responses_output(output)
        if messages:
            return _summarize_messages(messages), "text/plain", messages
        return _safe_json_dumps(output), "application/json", None

    if payload.get("role") == "assistant" and isinstance(payload.get("content"), list):
        messages = _extract_messages_from_anthropic_content(payload)
        if messages:
            return _summarize_messages(messages), "text/plain", messages

    candidates = payload.get("candidates")
    if isinstance(candidates, list) and candidates:
        messages = _extract_messages_from_gemini_candidates(candidates)
        if messages:
            return _summarize_messages(messages), "text/plain", messages

    return None, None, None


def extract_available_tools(payload: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    """Extract best-effort available tools from a request payload."""
    raw_tools = payload.get("tools")
    if not isinstance(raw_tools, list):
        return None
    tools = [dict(tool) for tool in raw_tools if isinstance(tool, Mapping)]
    return tools or None


def extract_invocation_parameters(payload: Mapping[str, Any]) -> str | None:
    """Extract a normalized subset of invocation parameters for telemetry sinks."""
    keys = (
        "model",
        "reasoning",
        "reasoning_effort",
        "temperature",
        "top_p",
        "max_tokens",
        "max_output_tokens",
        "parallel_tool_calls",
        "tool_choice",
        "response_format",
        "text",
        "truncation",
        "store",
        "stream",
        "conversation",
        "previous_response_id",
    )
    invocation_parameters = {
        key: payload.get(key) for key in keys if payload.get(key) is not None
    }
    if not invocation_parameters:
        return None
    return _safe_json_dumps(invocation_parameters)


def extract_session_id_from_request_payload(payload: Mapping[str, Any]) -> str | None:
    """Infer a stable session identifier from a request payload."""
    conversation = payload.get("conversation")
    if isinstance(conversation, Mapping):
        conversation_id = _normalize_optional_text(conversation.get("id"))
        if conversation_id:
            return conversation_id

    previous_response_id = _normalize_optional_text(payload.get("previous_response_id"))
    if previous_response_id:
        return previous_response_id

    input_payload = payload.get("input")
    if isinstance(input_payload, list):
        inferred = _infer_session_id_from_responses_input(input_payload)
        if inferred:
            return inferred

    return None


def extract_session_id_from_response_payload(
    payload: Mapping[str, Any],
) -> str | None:
    """Infer a stable session identifier from a response payload."""
    conversation = payload.get("conversation")
    if isinstance(conversation, Mapping):
        conversation_id = _normalize_optional_text(conversation.get("id"))
        if conversation_id:
            return conversation_id

    response_id = _normalize_optional_text(payload.get("id"))
    if response_id and payload.get("object") == "response":
        return response_id
    return None


def _extract_messages_from_chat_messages(messages: Any) -> list[RequestAuditMessage]:
    result: list[RequestAuditMessage] = []
    if not isinstance(messages, list):
        return result
    for message in messages:
        if not isinstance(message, Mapping):
            continue
        content = _extract_message_content_text(message.get("content"))
        tool_calls = _extract_tool_calls(
            message.get("tool_calls"),
            fallback_id=message.get("functions_state_id"),
        )
        if not tool_calls:
            tool_calls = _extract_function_call(
                message.get("function_call"),
                fallback_id=message.get("functions_state_id"),
            )
        name = _normalize_optional_text(message.get("name"))
        tool_call_id = _normalize_optional_text(message.get("tool_call_id"))
        if content is None and not tool_calls and name is None and tool_call_id is None:
            continue
        result.append(
            _build_audit_message(
                role=_normalize_optional_text(message.get("role")) or "user",
                content=content,
                name=name,
                tool_call_id=tool_call_id,
                tool_calls=tool_calls,
            )
        )
    return result


def _extract_messages_from_responses_input(
    input_payload: list[Any],
) -> list[RequestAuditMessage]:
    result: list[RequestAuditMessage] = []
    for item in input_payload:
        if isinstance(item, str):
            result.append({"role": "user", "content": item})
            continue
        if not isinstance(item, Mapping):
            continue
        item_type = item.get("type")
        if item_type == "reasoning":
            reasoning_text = _extract_reasoning_text(item)
            if reasoning_text is not None:
                result.append({"role": "assistant", "content": reasoning_text})
            continue
        if item_type == "function_call":
            name = _normalize_optional_text(item.get("name"))
            if not name:
                continue
            result.append(
                _build_audit_message(
                    role="assistant",
                    content=None,
                    tool_calls=[
                        {
                            "id": _normalize_optional_text(
                                item.get("call_id") or item.get("id")
                            ),
                            "function_name": name,
                            "function_arguments": _stringify_optional_json(
                                item.get("arguments")
                            ),
                        }
                    ],
                )
            )
            continue
        if item_type == "function_call_output":
            result.append(
                _build_audit_message(
                    role="tool",
                    content=_normalize_content_value(item.get("output")),
                    name=_normalize_optional_text(item.get("name")),
                    tool_call_id=_normalize_optional_text(
                        item.get("call_id") or item.get("id")
                    ),
                )
            )
            continue
        role = _normalize_optional_text(item.get("role"))
        if role:
            content = _extract_message_content_text(item.get("content"))
            tool_calls = _extract_tool_calls(
                item.get("tool_calls"),
                fallback_id=(
                    item.get("tools_state_id")
                    or item.get("tool_state_id")
                    or item.get("call_id")
                    or item.get("id")
                ),
            )
            if not tool_calls:
                tool_calls = _extract_function_call(
                    item.get("function_call"),
                    fallback_id=(
                        item.get("tools_state_id")
                        or item.get("tool_state_id")
                        or item.get("tool_call_id")
                        or item.get("call_id")
                        or item.get("id")
                    ),
                )
            name = _normalize_optional_text(item.get("name"))
            tool_call_id = _normalize_optional_text(
                item.get("tool_call_id")
                or item.get("tools_state_id")
                or item.get("tool_state_id")
                or item.get("call_id")
            )
            if (
                content is not None
                or tool_calls
                or name is not None
                or tool_call_id is not None
            ):
                result.append(
                    _build_audit_message(
                        role=role,
                        content=content,
                        name=name,
                        tool_call_id=tool_call_id,
                        tool_calls=tool_calls,
                    )
                )
    return result


def _extract_messages_from_gemini_contents(
    contents: list[Any],
) -> list[RequestAuditMessage]:
    result: list[RequestAuditMessage] = []
    for item in contents:
        if not isinstance(item, Mapping):
            continue
        role = _normalize_optional_text(item.get("role")) or "user"
        content = _extract_gemini_parts_text(item.get("parts"))
        if content is None:
            continue
        result.append({"role": role, "content": content})
    return result


def _extract_messages_from_openai_choices(
    choices: list[Any],
) -> list[RequestAuditMessage]:
    result: list[RequestAuditMessage] = []
    for choice in choices:
        if not isinstance(choice, Mapping):
            continue
        message = choice.get("message") or choice.get("delta")
        if not isinstance(message, Mapping):
            continue
        content = _extract_message_content_text(message.get("content"))
        if content is None and isinstance(message.get("reasoning_content"), str):
            content = _normalize_optional_text(message.get("reasoning_content"))
        tool_calls = _extract_tool_calls(
            message.get("tool_calls"),
            fallback_id=message.get("functions_state_id"),
        )
        if not tool_calls:
            tool_calls = _extract_function_call(
                message.get("function_call"),
                fallback_id=message.get("functions_state_id"),
            )
        if content is None and not tool_calls:
            continue
        result.append(
            _build_audit_message(
                role=_normalize_optional_text(message.get("role")) or "assistant",
                content=content,
                tool_calls=tool_calls,
            )
        )
    return result


def _extract_messages_from_responses_output(
    output: list[Any],
) -> list[RequestAuditMessage]:
    result: list[RequestAuditMessage] = []
    for item in output:
        if not isinstance(item, Mapping):
            continue
        item_type = item.get("type")
        if item_type == "message":
            content = _extract_responses_output_text(item.get("content"))
            if content is None:
                continue
            result.append(
                {
                    "role": _normalize_optional_text(item.get("role")) or "assistant",
                    "content": content,
                }
            )
            continue
        if item_type == "reasoning":
            reasoning_text = _extract_reasoning_text(item)
            if reasoning_text is not None:
                result.append({"role": "assistant", "content": reasoning_text})
            continue
        if item_type == "function_call":
            name = _normalize_optional_text(item.get("name"))
            if not name:
                continue
            result.append(
                _build_audit_message(
                    role="assistant",
                    content=None,
                    tool_calls=[
                        {
                            "id": _normalize_optional_text(
                                item.get("call_id") or item.get("id")
                            ),
                            "function_name": name,
                            "function_arguments": _stringify_optional_json(
                                item.get("arguments")
                            ),
                        }
                    ],
                )
            )
            continue
        if item_type == "function_call_output":
            result.append(
                _build_audit_message(
                    role="tool",
                    content=_normalize_content_value(item.get("output")),
                    name=_normalize_optional_text(item.get("name")),
                    tool_call_id=_normalize_optional_text(
                        item.get("call_id") or item.get("id")
                    ),
                )
            )
    return result


def _extract_messages_from_anthropic_content(
    payload: Mapping[str, Any],
) -> list[RequestAuditMessage]:
    content = payload.get("content")
    if not isinstance(content, list):
        return []
    text_parts: list[str] = []
    for part in content:
        if not isinstance(part, Mapping):
            continue
        if isinstance(part.get("text"), str):
            text_parts.append(part["text"])
        elif isinstance(part.get("thinking"), str):
            text_parts.append(part["thinking"])
    if not text_parts:
        return []
    return [{"role": "assistant", "content": "\n".join(text_parts)}]


def _extract_messages_from_gemini_candidates(
    candidates: list[Any],
) -> list[RequestAuditMessage]:
    result: list[RequestAuditMessage] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        content = candidate.get("content")
        if not isinstance(content, Mapping):
            continue
        text = _extract_gemini_parts_text(content.get("parts"))
        if text is None:
            continue
        result.append(
            {
                "role": _normalize_optional_text(content.get("role")) or "assistant",
                "content": text,
            }
        )
    return result


def _extract_message_content_text(content: Any) -> str | None:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, Mapping):
            continue
        for key in ("text", "thinking", "input_text", "output_text"):
            value = item.get(key)
            if isinstance(value, str):
                parts.append(value)
                break
    joined = "\n".join(part for part in parts if part)
    return joined or None


def _extract_responses_output_text(content: Any) -> str | None:
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for item in content:
        if (
            isinstance(item, Mapping)
            and item.get("type") == "output_text"
            and isinstance(item.get("text"), str)
        ):
            parts.append(item["text"])
    joined = "\n".join(part for part in parts if part)
    return joined or None


def _extract_gemini_parts_text(parts: Any) -> str | None:
    if not isinstance(parts, list):
        return None
    texts: list[str] = []
    for part in parts:
        if not isinstance(part, Mapping):
            continue
        if isinstance(part.get("text"), str):
            texts.append(part["text"])
            continue
        function_call = part.get("functionCall")
        if isinstance(function_call, Mapping):
            texts.append(_safe_json_dumps(function_call))
    joined = "\n".join(text for text in texts if text)
    return joined or None


def _summarize_messages(messages: list[RequestAuditMessage]) -> str | None:
    if not messages:
        return None
    if len(messages) == 1:
        return _format_audit_message(messages[0])
    lines: list[str] = []
    for message in messages:
        content = _format_audit_message(message)
        if not content:
            continue
        role = _normalize_optional_text(message.get("role")) or "unknown"
        lines.append(f"{role}: {content}")
    return "\n\n".join(lines) or None


def _prepend_system_message(
    messages: list[RequestAuditMessage],
    payload: Mapping[str, Any],
) -> list[RequestAuditMessage]:
    system_prompt = _normalize_optional_text(
        payload.get("instructions") or payload.get("system_prompt")
    )
    if not system_prompt:
        return messages
    return [{"role": "system", "content": system_prompt}, *messages]


def _build_audit_message(
    *,
    role: str | None,
    content: str | None,
    name: str | None = None,
    tool_call_id: str | None = None,
    tool_calls: list[dict[str, str | None]] | None = None,
) -> RequestAuditMessage:
    message: RequestAuditMessage = {
        "role": role,
        "content": content,
    }
    if name:
        message["name"] = name
    if tool_call_id:
        message["tool_call_id"] = tool_call_id
    if tool_calls:
        message["tool_calls"] = tool_calls
    return message


def _extract_tool_calls(
    tool_calls: Any,
    *,
    fallback_id: Any = None,
) -> list[dict[str, str | None]]:
    result: list[dict[str, str | None]] = []
    if not isinstance(tool_calls, list):
        return result
    for tool_call in tool_calls:
        if not isinstance(tool_call, Mapping):
            continue
        function = tool_call.get("function")
        if not isinstance(function, Mapping):
            continue
        name = _normalize_optional_text(function.get("name"))
        if not name:
            continue
        result.append(
            {
                "id": _normalize_optional_text(tool_call.get("id") or fallback_id),
                "function_name": name,
                "function_arguments": _stringify_optional_json(
                    function.get("arguments")
                ),
            }
        )
    return result


def _extract_function_call(
    function_call: Any,
    *,
    fallback_id: Any = None,
) -> list[dict[str, str | None]]:
    if not isinstance(function_call, Mapping):
        return []
    name = _normalize_optional_text(function_call.get("name"))
    if not name:
        return []
    return [
        {
            "id": _normalize_optional_text(fallback_id),
            "function_name": name,
            "function_arguments": _stringify_optional_json(
                function_call.get("arguments")
            ),
        }
    ]


def _extract_reasoning_text(item: Mapping[str, Any]) -> str | None:
    parts: list[str] = []
    summary = item.get("summary")
    if isinstance(summary, list):
        for part in summary:
            if isinstance(part, Mapping) and isinstance(part.get("text"), str):
                parts.append(part["text"])
    content = item.get("content")
    if isinstance(content, list):
        for part in content:
            if isinstance(part, Mapping) and isinstance(part.get("text"), str):
                parts.append(part["text"])
    joined = "\n".join(part for part in parts if part)
    return joined or None


def _normalize_content_value(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if value is None:
        return None
    return _safe_json_dumps(value)


def _stringify_optional_json(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return _safe_json_dumps(value)


def _format_audit_message(message: RequestAuditMessage) -> str | None:
    content = _normalize_optional_text(message.get("content"))
    if content:
        return content
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        return _safe_json_dumps(tool_calls)
    return None


def _infer_session_id_from_responses_input(input_payload: list[Any]) -> str | None:
    for item in input_payload:
        if not isinstance(item, Mapping):
            continue
        candidates = [
            item.get("id"),
            item.get("call_id"),
            item.get("tool_call_id"),
        ]
        tool_calls = item.get("tool_calls")
        if isinstance(tool_calls, list):
            for tool_call in tool_calls:
                if isinstance(tool_call, Mapping):
                    candidates.append(tool_call.get("id"))
        for candidate in candidates:
            normalized = _normalize_session_identifier(candidate)
            if normalized:
                return normalized
    return None


def _normalize_session_identifier(value: Any) -> str | None:
    normalized = _normalize_optional_text(value)
    if not normalized:
        return None
    if normalized.startswith("resp_"):
        return normalized
    if normalized.startswith("fc_call_"):
        return f"resp_{normalized.removeprefix('fc_call_')}"
    if normalized.startswith("call_"):
        return f"resp_{normalized.removeprefix('call_')}"
    if normalized.startswith("rs_"):
        return f"resp_{normalized.removeprefix('rs_')}"
    if normalized.startswith("msg_"):
        message_id = normalized.removeprefix("msg_")
        match = re.match(r"^(?P<base>.+)_\d+$", message_id)
        if match is not None:
            message_id = match.group("base")
        return f"resp_{message_id}"
    return normalized


def _safe_json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _normalize_optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
