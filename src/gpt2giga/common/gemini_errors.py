"""Shared Google error codes for HTTP and streaming projections."""

from typing import Any


def gemini_error_status(status_code: int) -> str:
    """Map an HTTP status to its Google canonical status name."""
    return {
        400: "INVALID_ARGUMENT",
        401: "UNAUTHENTICATED",
        403: "PERMISSION_DENIED",
        404: "NOT_FOUND",
        408: "DEADLINE_EXCEEDED",
        409: "ALREADY_EXISTS",
        413: "RESOURCE_EXHAUSTED",
        422: "INVALID_ARGUMENT",
        429: "RESOURCE_EXHAUSTED",
        500: "INTERNAL",
        501: "UNIMPLEMENTED",
        504: "DEADLINE_EXCEEDED",
    }.get(status_code, "UNAVAILABLE" if status_code >= 500 else "UNKNOWN")


def gemini_error_payload(message: str, status_code: int) -> dict[str, Any]:
    """Build the same error envelope before and after SSE dispatch."""
    return {
        "error": {
            "code": status_code,
            "message": message,
            "status": gemini_error_status(status_code),
        }
    }


def gemini_stream_error_status(error: Any) -> int:
    """Resolve normalized failures without exposing string codes as HTTP codes."""
    if error is None:
        return 502
    code = error.code
    if isinstance(code, int) and not isinstance(code, bool) and 400 <= code <= 599:
        return code
    statuses = {
        "upstream_timeout": 504,
        "timeout": 504,
        "authentication": 401,
        "authentication_error": 401,
        "permission": 403,
        "permission_error": 403,
        "not_found": 404,
        "not_found_error": 404,
        "rate_limit": 429,
        "rate_limit_error": 429,
        "invalid_request": 400,
        "invalid_request_error": 400,
        "internal_error": 500,
    }
    for value in (code, error.error_class, error.type):
        if value in statuses:
            return statuses[value]
    return 502
