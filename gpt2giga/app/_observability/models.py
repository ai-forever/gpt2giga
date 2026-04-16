"""Typed observability payload models."""

from __future__ import annotations

from typing import Any, TypedDict


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
