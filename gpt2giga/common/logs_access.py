from fastapi import HTTPException
from starlette.requests import Request
from starlette.status import HTTP_403_FORBIDDEN


def _get_client_ip(request: Request) -> str:
    """Extract client IP from X-Forwarded-For or request.client."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return ""


def verify_logs_ip_allowlist(request: Request) -> None:
    """Deny access if client IP is not in the configured allowlist."""
    allowlist = getattr(
        getattr(getattr(request.app.state, "config", None), "proxy_settings", None),
        "logs_ip_allowlist",
        None,
    )
    if not allowlist:
        return
    client_ip = _get_client_ip(request)
    if client_ip not in allowlist:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Access denied: IP not in logs allowlist",
        )
