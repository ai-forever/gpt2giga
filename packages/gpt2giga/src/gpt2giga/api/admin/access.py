"""Shared admin API access guards."""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, status


def verify_admin_key(request: Request) -> None:
    """Require the configured admin key for protected admin routes."""
    settings = getattr(
        getattr(request.app.state, "config", None), "proxy_settings", None
    )
    expected = getattr(settings, "admin_api_key", None)
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin API key is required",
        )

    supplied = extract_admin_key(request)
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin API key",
        )


def extract_admin_key(request: Request) -> str | None:
    """Read the admin key from supported headers."""
    header_key = request.headers.get("x-admin-api-key")
    if header_key:
        return header_key.strip() or None

    authorization = request.headers.get("authorization")
    if not authorization:
        return None
    authorization = authorization.strip()
    if authorization[:7].lower() == "bearer ":
        return authorization[7:].strip() or None
    return None
