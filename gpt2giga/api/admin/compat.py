"""Protected compatibility diagnostics endpoints."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast, get_args

from fastapi import APIRouter, Depends, HTTPException, Request, status

from gpt2giga.api.admin.access import verify_admin_key
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.diagnostics import analyze_compatibility_request
from gpt2giga.diagnostics.models import CompatibilityProtocol
from gpt2giga.diagnostics.routes import ADMIN_COMPAT_ANALYZE_ROUTE
from gpt2giga.openapi_tags import OPENAPI_TAG_ADMIN_COMPATIBILITY


_SUPPORTED_PROTOCOLS = frozenset(get_args(CompatibilityProtocol))
_ADMIN_COMPAT_PREFIX = ADMIN_COMPAT_ANALYZE_ROUTE.removesuffix("/analyze")


router = APIRouter(
    prefix=_ADMIN_COMPAT_PREFIX,
    tags=[OPENAPI_TAG_ADMIN_COMPATIBILITY],
    dependencies=[Depends(verify_admin_key)],
)


@router.post("/analyze")
@exceptions_handler
async def analyze(request: Request) -> dict[str, Any]:
    """Analyze a request shape without calling the upstream provider."""
    envelope = await _read_json_object(request)
    analysis = analyze_compatibility_request(
        protocol=_read_protocol(envelope),
        route=_read_route(envelope),
        headers=_read_mapping(envelope, "headers"),
        query=_read_mapping(envelope, "query"),
        body=_read_mapping(envelope, "body"),
        config=getattr(request.app.state, "config", None),
    )
    return analysis.to_json_dict()


async def _read_json_object(request: Request) -> dict[str, Any]:
    body = await request.body()
    if not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected a JSON object",
        )
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected a JSON object",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected a JSON object",
        )
    return payload


def _read_protocol(envelope: Mapping[str, Any]) -> CompatibilityProtocol | None:
    value = envelope.get("protocol")
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected protocol to be a supported string",
        )
    normalized = value.strip().lower()
    if normalized not in _SUPPORTED_PROTOCOLS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported protocol",
        )
    return cast(CompatibilityProtocol, normalized)


def _read_route(envelope: Mapping[str, Any]) -> str:
    value = envelope.get("route")
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected route to be a non-empty string",
        )
    return value.strip()


def _read_mapping(envelope: Mapping[str, Any], field_name: str) -> dict[str, Any]:
    value = envelope.get(field_name)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Expected {field_name} to be an object",
        )
    return dict(value)
