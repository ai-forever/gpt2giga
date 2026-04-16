"""High-level request-event recording and payload annotation helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from gpt2giga.app.dependencies import get_runtime_observability
from gpt2giga.app.governance import record_governance_event

from .context import (
    get_request_audit_context,
    set_request_audit_model,
    set_request_audit_usage,
)
from .feeds import get_recent_error_feed_from_state, get_recent_request_feed_from_state
from .messages import (
    extract_available_tools,
    extract_input_observability,
    extract_invocation_parameters,
    extract_model_from_payload,
    extract_output_observability,
    extract_session_id_from_request_payload,
    extract_session_id_from_response_payload,
    extract_usage_from_payload,
)
from .models import RequestAuditEvent
from .usage import record_usage_accounting


def record_request_event(state: Any, event: RequestAuditEvent) -> None:
    """Append an audit event to recent requests and errors feeds."""
    get_recent_request_feed_from_state(state).append(event)
    if int(event["status_code"]) >= 400 or event.get("error_type") is not None:
        get_recent_error_feed_from_state(state).append(event)
    record_usage_accounting(state, event)
    record_governance_event(state, event)
    hub = get_runtime_observability(state).hub
    if hub is not None:
        hub.record_request_event(event)


def annotate_request_audit_request_payload(
    request: Any,
    payload: Mapping[str, Any] | None,
) -> None:
    """Extract request input text/messages for observability sinks."""
    if not isinstance(payload, Mapping):
        return
    input_value, input_mime_type, input_messages = extract_input_observability(payload)
    context = get_request_audit_context(request)
    if input_value is not None:
        context["input_value"] = input_value
        context["input_mime_type"] = input_mime_type
    if input_messages:
        context["input_messages"] = input_messages
    session_id = extract_session_id_from_request_payload(payload)
    if session_id:
        context["session_id"] = session_id
    available_tools = extract_available_tools(payload)
    if available_tools:
        context["available_tools"] = available_tools
    invocation_parameters = extract_invocation_parameters(payload)
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

    model = extract_model_from_payload(payload) or fallback_model
    if model is not None:
        set_request_audit_model(request, model)
    set_request_audit_usage(request, extract_usage_from_payload(payload))
    output_value, output_mime_type, output_messages = extract_output_observability(
        payload
    )
    context = get_request_audit_context(request)
    if output_value is not None:
        context["output_value"] = output_value
        context["output_mime_type"] = output_mime_type
    if output_messages:
        context["output_messages"] = output_messages
    if not context.get("session_id"):
        session_id = extract_session_id_from_response_payload(payload)
        if session_id:
            context["session_id"] = session_id
