from typing import Any, Optional


def adapt_v2_completion_to_v1_shape(response: Any, *, default_model: str) -> dict:
    """Adapt a primary v2 completion response to the legacy internal shape."""
    response_data = _dump_model(response)
    message = _select_message(response_data)
    function_call = extract_v2_function_call(message)
    text = extract_v2_assistant_text(message)
    reasoning_text = extract_v2_reasoning_text(response_data)
    metadata = extract_v2_message_metadata(response_data)

    message_payload: dict[str, Any] = {
        "role": _adapt_role(message.get("role")),
        "content": None if function_call and not text else text,
    }
    message_payload.update(metadata)
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
    metadata = extract_v2_message_metadata(chunk_data)

    delta: dict[str, Any] = {"content": text}
    delta.update(metadata)
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


def extract_v2_message_metadata(message_or_response: Any) -> dict[str, Any]:
    """Extract v2 built-in tool metadata from a message, response, or chunk."""
    data = _dump_model(message_or_response)
    message = _select_message(data)

    tool_executions: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    inline_data: dict[str, Any] = {}

    _append_tool_execution(tool_executions, data.get("tool_execution"))
    _append_tool_execution(tool_executions, message.get("tool_execution"))
    _merge_inline_data(inline_data, message.get("inline_data"))

    content = message.get("content")
    if isinstance(content, list):
        for part in content:
            part_data = _dump_model(part)
            _append_tool_execution(tool_executions, part_data.get("tool_execution"))
            _merge_inline_data(inline_data, part_data.get("inline_data"))

            part_files = part_data.get("files")
            if isinstance(part_files, list):
                for file_data in part_files:
                    normalized_file = _dump_model(file_data)
                    if normalized_file:
                        files.append(normalized_file)

    metadata: dict[str, Any] = {}
    if tool_executions:
        metadata["tool_executions"] = tool_executions
    if files:
        metadata["files"] = files
    if inline_data:
        metadata["inline_data"] = inline_data
    return metadata


def extract_v2_thread_id(response_or_chunk: Any) -> Optional[str]:
    """Extract a v2 storage thread identifier."""
    data = _dump_model(response_or_chunk)
    thread_id = data.get("thread_id")
    if isinstance(thread_id, str) and thread_id:
        return thread_id
    return None


async def hydrate_v2_image_files(
    adapted_response: dict, giga_client: Any, logger: Any = None
) -> None:
    """Fetch base64 image payloads for v2 image file references in-place."""
    if not hasattr(giga_client, "aget_image"):
        return

    choices = adapted_response.get("choices")
    if not isinstance(choices, list):
        return

    for choice in choices:
        choice_data = _dump_model(choice)
        for message_key in ("message", "delta"):
            message = choice_data.get(message_key)
            if not isinstance(message, dict):
                continue
            files = message.get("files")
            if not isinstance(files, list):
                continue
            for file_data in files:
                if not isinstance(file_data, dict) or file_data.get("content"):
                    continue
                file_id = file_data.get("id")
                if not isinstance(file_id, str) or not file_id:
                    continue
                if not _is_image_file(file_data):
                    continue
                try:
                    image = await giga_client.aget_image(file_id)
                    image_data = _dump_model(image)
                    content = image_data.get("content")
                    if isinstance(content, str) and content:
                        file_data["content"] = content
                except Exception as exc:
                    if logger:
                        logger.warning(
                            f"Failed to fetch GigaChat image file {file_id}: {exc}"
                        )


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


def _append_tool_execution(items: list[dict[str, Any]], value: Any) -> None:
    execution = _dump_model(value)
    if execution:
        items.append(execution)


def _merge_inline_data(target: dict[str, Any], value: Any) -> None:
    inline_data = _dump_model(value)
    if not inline_data:
        return

    for key, item in inline_data.items():
        if key == "sources" and isinstance(item, dict):
            existing = target.setdefault("sources", {})
            if isinstance(existing, dict):
                existing.update(item)
            else:
                target["sources"] = item
        elif isinstance(item, list):
            existing_list = target.setdefault(key, [])
            if isinstance(existing_list, list):
                existing_list.extend(item)
            else:
                target[key] = item
        elif item is not None:
            target[key] = item


def _is_image_file(file_data: dict[str, Any]) -> bool:
    target = file_data.get("target")
    mime = file_data.get("mime")
    return target == "image" or (isinstance(mime, str) and mime.startswith("image/"))


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
    for container in (message, response_or_chunk):
        for field_name in (
            "tools_state_id",
            "tool_state_id",
            "functions_state_id",
            "function_state_id",
        ):
            state_id = _normalize_state_id(container.get(field_name))
            if state_id:
                return state_id

    return str(message.get("message_id") or response_or_chunk.get("message_id") or "v2")


def _normalize_state_id(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    state_id = value.strip()
    if not state_id:
        return None
    for prefix in ("fc_", "call_"):
        if state_id.startswith(prefix) and len(state_id) > len(prefix):
            return state_id.removeprefix(prefix)
    return state_id
