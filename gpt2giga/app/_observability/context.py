"""Request-local audit metadata helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .models import RequestAuditUsage
from .usage import normalize_usage_payload


def set_request_audit_model(request: Any, model: str | None) -> None:
    """Persist the requested or resolved model for the current request."""
    if isinstance(model, str) and model:
        get_request_audit_context(request)["model"] = model


def set_request_audit_usage(
    request: Any, usage: Mapping[str, Any] | None
) -> RequestAuditUsage | None:
    """Persist normalized token usage for the current request."""
    normalized_usage = normalize_usage_payload(usage)
    if normalized_usage is not None:
        get_request_audit_context(request)["token_usage"] = normalized_usage
    return normalized_usage


def set_request_audit_error(request: Any, error_type: str | None) -> None:
    """Persist a best-effort error type for the current request."""
    if isinstance(error_type, str) and error_type:
        get_request_audit_context(request)["error_type"] = error_type


def get_request_audit_metadata(request: Any) -> dict[str, Any]:
    """Return normalized request-scoped audit metadata."""
    context = get_request_audit_context(request)
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


def get_request_audit_context(request: Any) -> dict[str, Any]:
    """Return the mutable per-request audit context, creating it on demand."""
    state = getattr(request, "state", None)
    context = getattr(state, "_request_audit_context", None)
    if not isinstance(context, dict):
        context = {}
        if state is not None:
            state._request_audit_context = context
    return context
