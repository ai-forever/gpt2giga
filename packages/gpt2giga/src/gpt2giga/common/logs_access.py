import ipaddress

from fastapi import HTTPException
from starlette.requests import Request
from starlette.status import HTTP_403_FORBIDDEN


def _get_client_ip(request: Request) -> str:
    """Resolve client IP, trusting forwarding only from an explicit proxy peer."""
    peer = request.client.host if request.client else ""
    trusted_proxies = getattr(
        getattr(getattr(request.app.state, "config", None), "proxy_settings", None),
        "logs_trusted_proxies",
        (),
    )
    if peer not in trusted_proxies:
        return peer
    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return peer
    candidate = forwarded.split(",")[0].strip()
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return peer


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
