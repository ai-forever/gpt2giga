"""Request-scoped context for internal routing and future observability."""

import hashlib
import secrets
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from starlette.requests import Request

from gpt2giga.core.caller import infer_request_caller

_FINGERPRINT_KEY = secrets.token_bytes(32)
_FINGERPRINT_ITERATIONS = 100_000


@dataclass
class RequestContext:
    """Store internal request metadata without changing public responses."""

    request_id: str
    trace_id: str
    span_id: Optional[str]
    protocol: str
    route: str
    method: str
    started_at: datetime
    client_ip_hash: Optional[str] = None
    api_key_hash: Optional[str] = None
    caller_name: Optional[str] = None
    caller_category: Optional[str] = None
    caller_client_family: Optional[str] = None
    caller_sdk: Optional[str] = None
    caller_agent: Optional[str] = None
    caller_ui: Optional[str] = None
    caller_user_agent: Optional[str] = None
    caller_agent_id: Optional[str] = None
    model_requested: Optional[str] = None
    model_effective: Optional[str] = None
    llm_observability_emitted: bool = False
    request_headers_redacted: Any | None = None
    request_body_redacted: Any | None = None
    response_body_redacted: Any | None = None
    annotations: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


request_context_var: ContextVar[Optional[RequestContext]] = ContextVar(
    "gpt2giga_request_context",
    default=None,
)


def build_request_context(request: Request, *, request_id: str) -> RequestContext:
    """Build a safe request context from HTTP request metadata."""
    caller = infer_request_caller(request.headers)
    return RequestContext(
        request_id=request_id,
        trace_id=_header_or_new_id(request, "x-trace-id"),
        span_id=_optional_header(request, "x-span-id"),
        protocol=_infer_protocol(request.url.path),
        route=request.url.path,
        method=request.method,
        started_at=datetime.now(timezone.utc),
        client_ip_hash=fingerprint_sensitive_value(_client_ip(request)),
        api_key_hash=fingerprint_sensitive_value(_api_key_value(request)),
        caller_name=caller.name,
        caller_category=caller.category,
        caller_client_family=caller.client_family,
        caller_sdk=caller.sdk,
        caller_agent=caller.agent,
        caller_ui=caller.ui,
        caller_user_agent=caller.user_agent,
        caller_agent_id=caller.agent_id,
        annotations=caller.to_annotations(),
    )


def get_request_context() -> Optional[RequestContext]:
    """Return the current request context if one is active."""
    return request_context_var.get()


def update_request_context(
    *,
    model_requested: Any = None,
    model_effective: Any = None,
    metadata: Optional[dict[str, Any]] = None,
) -> Optional[RequestContext]:
    """Update optional request context fields when request details become known."""
    context = get_request_context()
    if context is None:
        return None
    if model_requested is not None:
        context.model_requested = str(model_requested)
    if model_effective is not None:
        context.model_effective = str(model_effective)
    if metadata:
        context.metadata.update(metadata)
    return context


def _header_or_new_id(request: Request, header_name: str) -> str:
    value = _optional_header(request, header_name)
    return value or str(uuid.uuid4())


def _optional_header(request: Request, header_name: str) -> Optional[str]:
    value = request.headers.get(header_name)
    if not value:
        return None
    value = value.strip()
    return value or None


def _infer_protocol(path: str) -> str:
    normalized = path.rstrip("/") or "/"
    if normalized == "/" or normalized in {"/health", "/ping"}:
        return "system"
    if normalized.startswith("/logs"):
        return "system"
    if (
        normalized.startswith("/v1/messages")
        or normalized.startswith("/v2/messages")
        or normalized.startswith("/messages")
    ):
        return "anthropic"
    if normalized.startswith("/v1beta/"):
        return "gemini"
    if normalized in {"/v1/model/info", "/v2/model/info", "/model/info"}:
        return "litellm"
    return "openai"


def _client_ip(request: Request) -> Optional[str]:
    if request.client is None:
        return None
    return request.client.host


def _api_key_value(request: Request) -> Optional[str]:
    authorization = request.headers.get("authorization")
    if authorization:
        authorization = authorization.strip()
        if authorization[:7].lower() == "bearer ":
            return authorization[7:].strip() or None
        return authorization

    api_key = request.headers.get("x-api-key") or request.query_params.get("x-api-key")
    if api_key:
        return api_key.strip() or None
    return None


def fingerprint_sensitive_value(value: Optional[str]) -> Optional[str]:
    """Return a request-correlation fingerprint without storing raw secrets."""
    if not value:
        return None
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        value.encode("utf-8"),
        _FINGERPRINT_KEY,
        _FINGERPRINT_ITERATIONS,
        dklen=8,
    ).hex()
    return f"pbkdf2-sha256:{digest}"
