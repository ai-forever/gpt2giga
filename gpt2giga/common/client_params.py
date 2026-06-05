"""Client SDK parameter compatibility policy helpers."""

from enum import Enum
from typing import Any, Iterable, Mapping, Optional

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from gpt2giga.logger import rquid_context


class ClientParamStatus(str, Enum):
    """Compatibility status for a client-visible parameter."""

    SUPPORTED = "supported"
    ACCEPTED_IGNORED = "accepted_ignored"
    REJECTED = "rejected"
    NOT_APPLICABLE = "not_applicable"


CLIENT_PARAM_STATUSES = frozenset(status.value for status in ClientParamStatus)

SAFE_DIAGNOSTIC_HEADER_NAMES = frozenset(
    {
        "traceparent",
        "x-correlation-id",
        "x-request-id",
        "x-trace-id",
    }
)

GIGACHAT_CONTEXT_HEADER_NAMES = frozenset(
    {
        "authorization",
        "x-agent-id",
        "x-client-id",
        "x-operation-id",
        "x-request-id",
        "x-service-id",
        "x-session-id",
        "x-trace-id",
    }
)

GIGACHAT_RESPONSE_METADATA_HEADER_KEYS = {
    "x-request-id": "gigachat_x_request_id",
    "x-session-id": "gigachat_x_session_id",
}

SAFE_GIGACHAT_QUERY_PARAM_NAMES = frozenset()

BLOCKED_CLIENT_HEADER_NAMES = frozenset(
    {
        "accept",
        "accept-encoding",
        "authorization",
        "connection",
        "content-length",
        "content-type",
        "cookie",
        "expect",
        "forwarded",
        "host",
        "keep-alive",
        "proxy-authorization",
        "set-cookie",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "user-agent",
        "x-api-key",
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-port",
        "x-forwarded-proto",
        "x-real-ip",
    }
)

BLOCKED_CLIENT_HEADER_PREFIXES = (
    "anthropic-",
    "openai-",
    "x-stainless-",
)


class ClientCompatibilityError(Exception):
    """Error for unsupported or unsafe client compatibility parameters."""

    def __init__(
        self,
        message: str,
        *,
        provider: str = "openai",
        status_code: int = 400,
        param: Optional[str] = None,
        code: Optional[str] = "unsupported_parameter",
        error_type: str = "invalid_request_error",
    ) -> None:
        super().__init__(message)
        if provider not in {"openai", "anthropic"}:
            raise ValueError("provider must be either 'openai' or 'anthropic'")
        self.message = message
        self.provider = provider
        self.status_code = status_code
        self.param = param
        self.code = code
        self.error_type = error_type


def normalize_header_name(name: str) -> str:
    """Normalize an HTTP header name for policy checks."""
    return name.strip().lower()


def is_blocked_client_header(name: str) -> bool:
    """Return true if a client header must never be forwarded upstream."""
    normalized = normalize_header_name(name)
    return normalized in BLOCKED_CLIENT_HEADER_NAMES or normalized.startswith(
        BLOCKED_CLIENT_HEADER_PREFIXES
    )


def is_safe_diagnostic_header(name: str) -> bool:
    """Return true if a header is allowed as diagnostic upstream metadata."""
    normalized = normalize_header_name(name)
    return normalized in SAFE_DIAGNOSTIC_HEADER_NAMES and not is_blocked_client_header(
        normalized
    )


def is_safe_extra_header(name: str) -> bool:
    """Return true if an SDK extra header may be forwarded upstream."""
    normalized = normalize_header_name(name)
    return bool(normalized) and not is_blocked_client_header(normalized)


def filter_safe_diagnostic_headers(raw: Any) -> dict[str, str]:
    """Return allowlisted diagnostic headers with scalar values stringified."""
    if not isinstance(raw, Mapping):
        return {}

    headers: dict[str, str] = {}
    for name, value in raw.items():
        if not isinstance(name, str) or value is None:
            continue
        normalized = normalize_header_name(name)
        if not is_safe_diagnostic_header(normalized):
            continue
        if isinstance(value, (str, int, float, bool)):
            headers[normalized] = str(value)
    return headers


def filter_safe_extra_headers(raw: Any) -> dict[str, str]:
    """Return safe SDK extra headers with scalar values stringified."""
    if not isinstance(raw, Mapping):
        return {}

    headers: dict[str, str] = {}
    for name, value in raw.items():
        if not isinstance(name, str) or value is None:
            continue
        normalized = normalize_header_name(name)
        if not is_safe_extra_header(normalized):
            continue
        if isinstance(value, (str, int, float, bool)):
            headers[normalized] = str(value)
    return headers


def extract_gigachat_response_metadata(raw_headers: Any) -> dict[str, str]:
    """Return OpenAI metadata fields from allowlisted GigaChat response headers."""
    if not isinstance(raw_headers, Mapping):
        return {}

    normalized_headers = {
        normalize_header_name(name): value
        for name, value in raw_headers.items()
        if isinstance(name, str) and value is not None
    }
    metadata: dict[str, str] = {}
    for header_name, metadata_key in GIGACHAT_RESPONSE_METADATA_HEADER_KEYS.items():
        value = normalized_headers.get(header_name)
        if isinstance(value, (str, int, float, bool)):
            metadata[metadata_key] = str(value)
    return metadata


def merge_openai_response_metadata(
    request_metadata: Any,
    upstream_metadata: Optional[Mapping[str, str]] = None,
) -> Any:
    """Merge user metadata with proxy-added OpenAI response metadata."""
    metadata = (
        dict(request_metadata)
        if isinstance(request_metadata, Mapping)
        else request_metadata
    )
    if not upstream_metadata:
        return metadata

    if not isinstance(metadata, dict):
        metadata = {}
    metadata.update(upstream_metadata)
    return metadata


def filter_safe_query_items(
    items: Iterable[tuple[str, Any]],
    *,
    allowlist: frozenset[str] = SAFE_GIGACHAT_QUERY_PARAM_NAMES,
) -> tuple[tuple[str, str], ...]:
    """Return allowlisted query parameters with scalar values stringified."""
    query: list[tuple[str, str]] = []
    for key, value in items:
        if not isinstance(key, str) or value is None:
            continue
        if key.lower() not in allowlist:
            continue
        if isinstance(value, bool):
            query.append((key, "true" if value else "false"))
        elif isinstance(value, (str, int, float)):
            query.append((key, str(value)))
    return tuple(query)


def openai_error_payload(
    message: str,
    *,
    error_type: str = "invalid_request_error",
    param: Optional[str] = None,
    code: Optional[str] = "unsupported_parameter",
) -> dict[str, dict[str, Optional[str]]]:
    """Build an OpenAI-compatible error payload for HTTPException.detail."""
    return {
        "error": {
            "message": message,
            "type": error_type,
            "param": param,
            "code": code,
        }
    }


def openai_compatibility_error(
    message: str,
    *,
    status_code: int = 400,
    param: Optional[str] = None,
    code: Optional[str] = "unsupported_parameter",
    error_type: str = "invalid_request_error",
) -> HTTPException:
    """Build an OpenAI-compatible compatibility HTTPException."""
    return HTTPException(
        status_code=status_code,
        detail=openai_error_payload(
            message,
            error_type=error_type,
            param=param,
            code=code,
        ),
    )


def anthropic_error_payload(
    message: str,
    *,
    error_type: str = "invalid_request_error",
    code: Optional[str] = None,
) -> dict[str, Any]:
    """Build an Anthropic-compatible error response payload."""
    error: dict[str, str] = {
        "type": error_type,
        "message": message,
    }
    if code is not None:
        error["code"] = code

    return {
        "type": "error",
        "error": error,
        "request_id": rquid_context.get(),
    }


def anthropic_compatibility_response(
    message: str,
    *,
    status_code: int = 400,
    error_type: str = "invalid_request_error",
    code: Optional[str] = None,
) -> JSONResponse:
    """Build an Anthropic-compatible compatibility JSON response."""
    return JSONResponse(
        status_code=status_code,
        content=anthropic_error_payload(message, error_type=error_type, code=code),
    )


def client_compatibility_response(error: ClientCompatibilityError) -> JSONResponse:
    """Build a provider-compatible response for a compatibility error."""
    if error.provider == "anthropic":
        return anthropic_compatibility_response(
            error.message,
            status_code=error.status_code,
            error_type=error.error_type,
        )

    return JSONResponse(
        status_code=error.status_code,
        content=openai_error_payload(
            error.message,
            error_type=error.error_type,
            param=error.param,
            code=error.code,
        ),
    )
