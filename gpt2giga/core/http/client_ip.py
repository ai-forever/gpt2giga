"""Shared client-IP resolution helpers with explicit proxy trust."""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable

from starlette.requests import Request


def resolve_client_ip(
    request: Request,
    *,
    trusted_proxy_cidrs: Iterable[str] | None = None,
) -> str | None:
    """Resolve the effective client IP for a request.

    ``X-Forwarded-For`` is honored only when the direct peer IP matches one of
    the configured trusted proxy CIDRs. Otherwise the direct peer address is
    returned.
    """

    peer_ip = get_peer_ip(request)
    if peer_ip is None:
        return None

    if is_trusted_proxy(peer_ip, trusted_proxy_cidrs):
        forwarded_ip = get_forwarded_client_ip(request)
        if forwarded_ip is not None:
            return forwarded_ip

    return peer_ip


def get_peer_ip(request: Request) -> str | None:
    """Return the direct peer IP/host reported by the ASGI server."""
    client = request.client
    return None if client is None else client.host


def get_forwarded_client_ip(request: Request) -> str | None:
    """Return the first client IP from ``X-Forwarded-For`` when present."""
    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return None
    first_hop = forwarded.split(",", 1)[0].strip()
    return first_hop or None


def is_trusted_proxy(
    peer_ip: str | None,
    trusted_proxy_cidrs: Iterable[str] | None = None,
) -> bool:
    """Return whether the direct peer is an explicitly trusted proxy."""
    if peer_ip is None:
        return False

    try:
        peer = ipaddress.ip_address(peer_ip)
    except ValueError:
        return False

    for entry in trusted_proxy_cidrs or ():
        if peer in ipaddress.ip_network(entry, strict=False):
            return True
    return False
