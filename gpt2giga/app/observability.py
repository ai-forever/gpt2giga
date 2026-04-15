"""Observability helpers shared by middleware and admin endpoints."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, TypedDict

from gpt2giga.app.dependencies import get_runtime_observability, get_runtime_stores
from gpt2giga.app.governance import record_governance_event
from gpt2giga.app.runtime_backends import EventFeed


class RequestAuditUsage(TypedDict):
    """Normalized token-usage payload for audit events."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class RequestAuditMessage(TypedDict, total=False):
    """Best-effort normalized chat message for observability sinks."""

    role: str | None
    content: str | None
    name: str | None
    tool_call_id: str | None
    tool_calls: list[dict[str, str | None]] | None


class RequestAuditEvent(TypedDict, total=False):
    """Structured audit event for a handled HTTP request."""

    created_at: str
    request_id: str | None
    provider: str | None
    endpoint: str
    method: str
    path: str
    status_code: int
    duration_ms: float
    stream_duration_ms: float | None
    client_ip: str | None
    model: str | None
    token_usage: RequestAuditUsage | None
    error_type: str | None
    api_key_name: str | None
    api_key_source: str | None
    input_value: str | None
    input_mime_type: str | None
    output_value: str | None
    output_mime_type: str | None
    input_messages: list[RequestAuditMessage] | None
    output_messages: list[RequestAuditMessage] | None
    session_id: str | None
    available_tools: list[dict[str, Any]] | None
    invocation_parameters: str | None


def get_recent_request_feed_from_state(state: Any) -> EventFeed:
    """Return the recent requests feed from app state."""
    feed = get_runtime_stores(state).recent_requests
    if feed is None:
        raise RuntimeError("Recent requests feed is not configured.")
    return feed


def get_recent_error_feed_from_state(state: Any) -> EventFeed:
    """Return the recent errors feed from app state."""
    feed = get_runtime_stores(state).recent_errors
    if feed is None:
        raise RuntimeError("Recent errors feed is not configured.")
    return feed


def record_request_event(state: Any, event: RequestAuditEvent) -> None:
    """Append an audit event to recent requests and errors feeds."""
    get_recent_request_feed_from_state(state).append(event)
    if int(event["status_code"]) >= 400 or event.get("error_type") is not None:
        get_recent_error_feed_from_state(state).append(event)
    _record_usage_accounting(state, event)
    record_governance_event(state, event)
    hub = get_runtime_observability(state).hub
    if hub is not None:
        hub.record_request_event(event)


def filter_request_events(
    events: list[RequestAuditEvent],
    *,
    request_id: str | None = None,
    provider: str | None = None,
    endpoint: str | None = None,
    method: str | None = None,
    status_code: int | None = None,
    model: str | None = None,
    error_type: str | None = None,
) -> list[RequestAuditEvent]:
    """Filter request events by normalized admin filter fields."""
    filtered = events
    if request_id is not None:
        filtered = [item for item in filtered if item.get("request_id") == request_id]
    if provider is not None:
        filtered = [item for item in filtered if item.get("provider") == provider]
    if endpoint is not None:
        filtered = [item for item in filtered if item.get("endpoint") == endpoint]
    if method is not None:
        filtered = [item for item in filtered if item.get("method") == method]
    if status_code is not None:
        filtered = [item for item in filtered if item.get("status_code") == status_code]
    if model is not None:
        filtered = [item for item in filtered if item.get("model") == model]
    if error_type is not None:
        filtered = [item for item in filtered if item.get("error_type") == error_type]
    return filtered


def query_request_events(
    feed: EventFeed,
    *,
    limit: int | None = None,
    request_id: str | None = None,
    provider: str | None = None,
    endpoint: str | None = None,
    method: str | None = None,
    status_code: int | None = None,
    model: str | None = None,
    error_type: str | None = None,
) -> list[RequestAuditEvent]:
    """Query recent request events with a graceful fallback for legacy feeds."""
    filters = {
        key: value
        for key, value in {
            "request_id": request_id,
            "provider": provider,
            "endpoint": endpoint,
            "method": method,
            "status_code": status_code,
            "model": model,
            "error_type": error_type,
        }.items()
        if value is not None
    }
    query = getattr(feed, "query", None)
    if callable(query):
        return list(query(limit=limit, filters=filters))

    return filter_request_events(
        feed.recent(limit=limit),
        request_id=request_id,
        provider=provider,
        endpoint=endpoint,
        method=method,
        status_code=status_code,
        model=model,
        error_type=error_type,
    )


def set_request_audit_model(request: Any, model: str | None) -> None:
    """Persist the requested or resolved model for the current request."""
    if isinstance(model, str) and model:
        _get_request_audit_context(request)["model"] = model


def set_request_audit_usage(
    request: Any, usage: Mapping[str, Any] | None
) -> RequestAuditUsage | None:
    """Persist normalized token usage for the current request."""
    normalized_usage = _normalize_usage_payload(usage)
    if normalized_usage is not None:
        _get_request_audit_context(request)["token_usage"] = normalized_usage
    return normalized_usage


def set_request_audit_error(request: Any, error_type: str | None) -> None:
    """Persist a best-effort error type for the current request."""
    if isinstance(error_type, str) and error_type:
        _get_request_audit_context(request)["error_type"] = error_type


def annotate_request_audit_request_payload(
    request: Any,
    payload: Mapping[str, Any] | None,
) -> None:
    """Extract request input text/messages for observability sinks."""
    if not isinstance(payload, Mapping):
        return
    input_value, input_mime_type, input_messages = _extract_input_observability(payload)
    context = _get_request_audit_context(request)
    if input_value is not None:
        context["input_value"] = input_value
        context["input_mime_type"] = input_mime_type
    if input_messages:
        context["input_messages"] = input_messages
    session_id = _extract_session_id_from_request_payload(payload)
    if session_id:
        context["session_id"] = session_id
    available_tools = _extract_available_tools(payload)
    if available_tools:
        context["available_tools"] = available_tools
    invocation_parameters = _extract_invocation_parameters(payload)
    if invocation_parameters is not None:
        context["invocation_parameters"] = invocation_parameters


def annotate_request_audit_from_payload(
    request: Any,
    payload: Mapping[str, Any] | None,
    *,
    fallback_model: str | None = None,
) -> None:
    """Extract model and token usage from a provider response payload."""
    if not isinstance(payload, Mapping):
        if fallback_model is not None:
            set_request_audit_model(request, fallback_model)
        return

    model = _extract_model_from_payload(payload) or fallback_model
    if model is not None:
        set_request_audit_model(request, model)
    set_request_audit_usage(request, _extract_usage_from_payload(payload))
    output_value, output_mime_type, output_messages = _extract_output_observability(
        payload
    )
    context = _get_request_audit_context(request)
    if output_value is not None:
        context["output_value"] = output_value
        context["output_mime_type"] = output_mime_type
    if output_messages:
        context["output_messages"] = output_messages
    if not context.get("session_id"):
        session_id = _extract_session_id_from_response_payload(payload)
        if session_id:
            context["session_id"] = session_id


def get_request_audit_metadata(request: Any) -> dict[str, Any]:
    """Return normalized request-scoped audit metadata."""
    context = _get_request_audit_context(request)
    return {
        "model": context.get("model"),
        "token_usage": context.get("token_usage"),
        "error_type": context.get("error_type"),
        "input_value": context.get("input_value"),
        "input_mime_type": context.get("input_mime_type"),
        "output_value": context.get("output_value"),
        "output_mime_type": context.get("output_mime_type"),
        "input_messages": context.get("input_messages"),
        "output_messages": context.get("output_messages"),
        "session_id": context.get("session_id"),
        "available_tools": context.get("available_tools"),
        "invocation_parameters": context.get("invocation_parameters"),
    }


def _record_usage_accounting(state: Any, event: RequestAuditEvent) -> None:
    """Update aggregated usage counters for provider and API-key views."""
    provider = event.get("provider")
    if provider in (None, "admin", "system"):
        return

    stores = get_runtime_stores(state)
    _update_usage_mapping(
        stores.usage_by_provider,
        str(provider),
        event,
        kind="provider",
        display_name=str(provider),
    )

    api_key_name = event.get("api_key_name")
    if api_key_name:
        _update_usage_mapping(
            stores.usage_by_api_key,
            str(api_key_name),
            event,
            kind="api_key",
            display_name=str(api_key_name),
        )


def _update_usage_mapping(
    store: Any,
    key: str,
    event: RequestAuditEvent,
    *,
    kind: str,
    display_name: str,
) -> None:
    """Apply a normalized request event to an aggregated usage mapping."""
    current = store.get(key) if hasattr(store, "get") else None
    record = dict(current) if isinstance(current, Mapping) else {}
    usage = event.get("token_usage") or {}
    prompt_tokens = _safe_int(usage.get("prompt_tokens"))
    completion_tokens = _safe_int(usage.get("completion_tokens"))
    total_tokens = _safe_int(usage.get("total_tokens"))
    status_code = _safe_int(event.get("status_code"))
    is_error = status_code >= 400 or event.get("error_type") is not None
    provider = event.get("provider")
    endpoint = event.get("endpoint")
    model = event.get("model")
    created_at = event.get("created_at")
    api_key_name = event.get("api_key_name")
    api_key_source = event.get("api_key_source")

    record.setdefault("kind", kind)
    if kind == "api_key":
        record.setdefault("name", display_name)
        record.setdefault("source", api_key_source or "unknown")
    else:
        record.setdefault("provider", display_name)
    record.setdefault("request_count", 0)
    record.setdefault("success_count", 0)
    record.setdefault("error_count", 0)
    record.setdefault("prompt_tokens", 0)
    record.setdefault("completion_tokens", 0)
    record.setdefault("total_tokens", 0)
    record.setdefault("models", {})
    record.setdefault("endpoints", {})
    if kind == "api_key":
        record.setdefault("providers", {})
    else:
        record.setdefault("api_keys", {})
    record.setdefault("first_seen_at", created_at)
    record["last_seen_at"] = created_at

    record["request_count"] += 1
    if is_error:
        record["error_count"] += 1
    else:
        record["success_count"] += 1
    record["prompt_tokens"] += prompt_tokens
    record["completion_tokens"] += completion_tokens
    record["total_tokens"] += total_tokens

    if isinstance(model, str) and model:
        _update_usage_breakdown(
            record["models"],
            model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            is_error=is_error,
            created_at=created_at,
        )
    if isinstance(endpoint, str) and endpoint:
        _update_usage_breakdown(
            record["endpoints"],
            endpoint,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            is_error=is_error,
            created_at=created_at,
        )
    if kind == "api_key" and isinstance(provider, str) and provider:
        _update_usage_breakdown(
            record["providers"],
            provider,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            is_error=is_error,
            created_at=created_at,
        )
    if kind == "provider" and isinstance(api_key_name, str) and api_key_name:
        _update_usage_breakdown(
            record["api_keys"],
            api_key_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            is_error=is_error,
            created_at=created_at,
            extra={"source": api_key_source or "unknown"},
        )

    store[key] = record


def _update_usage_breakdown(
    breakdown: dict[str, Any],
    bucket_key: str,
    *,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    is_error: bool,
    created_at: str | None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """Update a nested usage bucket grouped by model/provider/endpoint/key."""
    item = dict(breakdown.get(bucket_key) or {})
    item.setdefault("request_count", 0)
    item.setdefault("success_count", 0)
    item.setdefault("error_count", 0)
    item.setdefault("prompt_tokens", 0)
    item.setdefault("completion_tokens", 0)
    item.setdefault("total_tokens", 0)
    item.setdefault("first_seen_at", created_at)
    item["last_seen_at"] = created_at
    item["request_count"] += 1
    if is_error:
        item["error_count"] += 1
    else:
        item["success_count"] += 1
    item["prompt_tokens"] += prompt_tokens
    item["completion_tokens"] += completion_tokens
    item["total_tokens"] += total_tokens
    if extra:
        for extra_key, extra_value in extra.items():
            item.setdefault(extra_key, extra_value)
    breakdown[bucket_key] = item


def _get_request_audit_context(request: Any) -> dict[str, Any]:
    state = getattr(request, "state", None)
    context = getattr(state, "_request_audit_context", None)
    if not isinstance(context, dict):
        context = {}
        if state is not None:
            state._request_audit_context = context
    return context


def _extract_model_from_payload(payload: Mapping[str, Any]) -> str | None:
    model = payload.get("model")
    if isinstance(model, str) and model:
        return model
    model_version = payload.get("modelVersion")
    if isinstance(model_version, str) and model_version:
        return model_version
    return None


def _extract_usage_from_payload(
    payload: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    if "usage" in payload and isinstance(payload.get("usage"), Mapping):
        return payload.get("usage")
    if "usageMetadata" in payload and isinstance(payload.get("usageMetadata"), Mapping):
        return payload.get("usageMetadata")
    return payload


def _normalize_usage_payload(
    usage: Mapping[str, Any] | None,
) -> RequestAuditUsage | None:
    if not isinstance(usage, Mapping):
        return None

    if "prompt_tokens" in usage or "completion_tokens" in usage:
        return {
            "prompt_tokens": _safe_int(usage.get("prompt_tokens")),
            "completion_tokens": _safe_int(usage.get("completion_tokens")),
            "total_tokens": _safe_int(usage.get("total_tokens")),
        }

    if "input_tokens" in usage or "output_tokens" in usage:
        return {
            "prompt_tokens": _safe_int(usage.get("input_tokens")),
            "completion_tokens": _safe_int(usage.get("output_tokens")),
            "total_tokens": _safe_int(usage.get("total_tokens")),
        }

    if "promptTokenCount" in usage or "candidatesTokenCount" in usage:
        return {
            "prompt_tokens": _safe_int(usage.get("promptTokenCount")),
            "completion_tokens": _safe_int(usage.get("candidatesTokenCount")),
            "total_tokens": _safe_int(usage.get("totalTokenCount")),
        }

    return None


def _extract_input_observability(
    payload: Mapping[str, Any],
) -> tuple[str | None, str | None, list[RequestAuditMessage] | None]:
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
        return _extract_input_observability(generate_request)

    contents = payload.get("contents")
    if isinstance(contents, list):
        messages = _extract_messages_from_gemini_contents(contents)
        return _summarize_messages(messages), "text/plain", messages or None

    return None, None, None


def _extract_output_observability(
    payload: Mapping[str, Any],
) -> tuple[str | None, str | None, list[RequestAuditMessage] | None]:
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


def _extract_available_tools(payload: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    raw_tools = payload.get("tools")
    if not isinstance(raw_tools, list):
        return None
    tools = [dict(tool) for tool in raw_tools if isinstance(tool, Mapping)]
    return tools or None


def _extract_invocation_parameters(payload: Mapping[str, Any]) -> str | None:
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


def _extract_session_id_from_request_payload(payload: Mapping[str, Any]) -> str | None:
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


def _extract_session_id_from_response_payload(
    payload: Mapping[str, Any],
) -> str | None:
    conversation = payload.get("conversation")
    if isinstance(conversation, Mapping):
        conversation_id = _normalize_optional_text(conversation.get("id"))
        if conversation_id:
            return conversation_id

    response_id = _normalize_optional_text(payload.get("id"))
    if response_id and payload.get("object") == "response":
        return response_id
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


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
