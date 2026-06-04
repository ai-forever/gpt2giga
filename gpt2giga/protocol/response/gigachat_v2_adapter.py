from typing import Any, Optional


def adapt_v2_completion_to_v1_shape(response: Any, *, default_model: str) -> dict:
    """Adapt a primary v2 completion response to the legacy internal shape."""
    response_data = _dump_model(response)
    message = _select_message(response_data)
    function_call = extract_v2_function_call(message)
    text = extract_v2_assistant_text(message)
    reasoning_text = extract_v2_reasoning_text(response_data)

    message_payload: dict[str, Any] = {
        "role": _adapt_role(message.get("role")),
        "content": None if function_call and not text else text,
    }
    if reasoning_text:
        message_payload["reasoning_content"] = reasoning_text
    if function_call:
        message_payload["function_call"] = function_call
        message_payload["functions_state_id"] = _functions_state_id(
            response_data, message
        )

    return {
        "model": response_data.get("model") or default_model,
        "thread_id": extract_v2_thread_id(response_data),
        "choices": [
            {
                "message": message_payload,
                "finish_reason": _finish_reason(
                    response_data,
                    message,
                    has_function_call=bool(function_call),
                    default_stop=True,
                ),
            }
        ],
        "usage": adapt_v2_usage(response_data.get("usage")),
    }


def adapt_v2_chunk_to_v1_shape(chunk: Any, *, default_model: str) -> dict:
    """Adapt a primary v2 stream chunk to the legacy internal chunk shape."""
    chunk_data = _dump_model(chunk)
    message = _select_message(chunk_data)
    function_call = extract_v2_function_call(message)
    text = extract_v2_assistant_text(message)
    reasoning_text = extract_v2_reasoning_text(chunk_data)

    delta: dict[str, Any] = {"content": text}
    if message.get("role"):
        delta["role"] = _adapt_role(message["role"])
    if reasoning_text:
        delta["reasoning_content"] = reasoning_text
    if function_call:
        delta["function_call"] = function_call
        delta["functions_state_id"] = _functions_state_id(chunk_data, message)

    return {
        "model": chunk_data.get("model") or default_model,
        "thread_id": extract_v2_thread_id(chunk_data),
        "choices": [
            {
                "delta": delta,
                "finish_reason": _finish_reason(
                    chunk_data,
                    message,
                    has_function_call=bool(function_call),
                    default_stop=False,
                ),
            }
        ],
        "usage": adapt_v2_usage(chunk_data.get("usage")),
    }


def extract_v2_assistant_text(message_or_response: Any) -> str:
    """Extract assistant text content from a v2 message, response, or chunk."""
    data = _dump_model(message_or_response)
    message = _select_message(data)
    role = message.get("role")
    if role and role != "assistant":
        return ""

    return _extract_text_content(message)


def extract_v2_reasoning_text(message_or_response: Any) -> str:
    """Extract reasoning text content from v2 reasoning messages."""
    data = _dump_model(message_or_response)
    messages = data.get("messages")
    if not isinstance(messages, list):
        message = _select_message(data)
        if message.get("role") == "reasoning":
            return _extract_text_content(message)
        return ""

    text_parts = []
    for message in messages:
        message_data = _dump_model(message)
        if message_data.get("role") != "reasoning":
            continue
        text = _extract_text_content(message_data)
        if text:
            text_parts.append(text)
    return "".join(text_parts)


def extract_v2_function_call(message_or_response: Any) -> Optional[dict]:
    """Extract the first function call from a v2 message, response, or chunk."""
    data = _dump_model(message_or_response)
    message = _select_message(data)

    function_call = _normalize_function_call(message.get("function_call"))
    if function_call:
        return function_call

    content = message.get("content")
    if not isinstance(content, list):
        return None

    for part in content:
        part_data = _dump_model(part)
        function_call = _normalize_function_call(part_data.get("function_call"))
        if function_call:
            return function_call
    return None


def extract_v2_thread_id(response_or_chunk: Any) -> Optional[str]:
    """Extract a v2 storage thread identifier."""
    data = _dump_model(response_or_chunk)
    thread_id = data.get("thread_id")
    if isinstance(thread_id, str) and thread_id:
        return thread_id
    return None


def adapt_v2_usage(usage: Any) -> Optional[dict]:
    """Map primary v2 token usage to the legacy internal usage shape."""
    usage_data = _dump_model(usage)
    if not usage_data:
        return None

    prompt_tokens = usage_data.get("input_tokens") or 0
    completion_tokens = usage_data.get("output_tokens") or 0
    total_tokens = usage_data.get("total_tokens")
    if total_tokens is None:
        total_tokens = prompt_tokens + completion_tokens

    input_details = _dump_model(usage_data.get("input_tokens_details"))
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "precached_prompt_tokens": input_details.get("cached_tokens", 0) or 0,
    }


def _dump_model(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_none=True, by_alias=True)
    if hasattr(value, "dict"):
        return value.dict(exclude_none=True, by_alias=True)
    return {}


def _select_message(data: dict) -> dict:
    if "messages" not in data:
        if {"role", "content", "function_call"} & data.keys():
            return data
        return {}

    messages = data.get("messages")
    if not isinstance(messages, list) or not messages:
        return {}

    for message in messages:
        message_data = _dump_model(message)
        if message_data.get("role") == "assistant":
            return message_data

    return _dump_model(messages[0])


def _extract_text_content(message: dict) -> str:
    content = message.get("content")

    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    text_parts = []
    for part in content:
        part_data = _dump_model(part)
        text = part_data.get("text")
        if isinstance(text, str):
            text_parts.append(text)
    return "".join(text_parts)


def _adapt_role(role: Any) -> str:
    if role == "reasoning" or not isinstance(role, str) or not role:
        return "assistant"
    return role


def _normalize_function_call(function_call: Any) -> Optional[dict]:
    function_call_data = _dump_model(function_call)
    name = function_call_data.get("name")
    if not isinstance(name, str) or not name:
        return None

    return {
        "name": name,
        "arguments": function_call_data.get("arguments", {}),
    }


def _finish_reason(
    response_or_chunk: dict,
    message: dict,
    *,
    has_function_call: bool,
    default_stop: bool,
) -> Optional[str]:
    finish_reason = response_or_chunk.get("finish_reason") or message.get(
        "finish_reason"
    )
    if finish_reason:
        return finish_reason
    if has_function_call:
        return "function_call" if default_stop else None
    if default_stop and (message or "messages" in response_or_chunk):
        return "stop"
    return None


def _functions_state_id(response_or_chunk: dict, message: dict) -> str:
    return str(
        message.get("tools_state_id")
        or response_or_chunk.get("tools_state_id")
        or message.get("message_id")
        or response_or_chunk.get("message_id")
        or "v2"
    )
