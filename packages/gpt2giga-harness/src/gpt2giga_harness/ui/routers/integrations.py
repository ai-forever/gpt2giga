"""Provider-neutral add-integration inventory and lifecycle API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request

from gpt2giga_harness.integration_flows import (
    IntegrationFlowConflictError,
    IntegrationFlowError,
    IntegrationFlowNotFoundError,
    integration_flow_record_to_dict,
)
from gpt2giga_harness.ui.async_execution import ConformantAPIRoute


router = APIRouter(route_class=ConformantAPIRoute)


@router.get("/api/integrations")
def integration_inventory(request: Request) -> dict[str, Any]:
    """Return source, target, catalog, and recent operation projections."""
    return request.app.state.harness_integration_flow_service.inventory()


@router.post("/api/integrations/preview")
def preview_integration(
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Persist one exact risk, permission, and configuration preview."""
    try:
        return request.app.state.harness_integration_flow_service.preview(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrationFlowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/integrations/flows/{flow_id}")
def integration_flow(flow_id: str, request: Request) -> dict[str, Any]:
    """Return one content-free durable operation with progress events."""
    try:
        record = request.app.state.harness_integration_flow_service.get(flow_id)
    except (ValueError, IntegrationFlowNotFoundError) as exc:
        raise HTTPException(
            status_code=404, detail="integration flow not found"
        ) from exc
    return {"flow": integration_flow_record_to_dict(record)}


@router.post("/api/integrations/flows/{flow_id}/apply")
def apply_integration(
    flow_id: str,
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Apply an exact approved preview or return a target-owned handoff."""
    plan_id = payload.get("plan_id")
    authority = payload.get("authority")
    if not isinstance(plan_id, str) or not isinstance(authority, str):
        raise HTTPException(
            status_code=422, detail="plan_id and authority are required"
        )
    try:
        return request.app.state.harness_integration_flow_service.apply(
            flow_id,
            plan_id=plan_id,
            authority=authority,
            allow_network=payload.get("allow_network") is True,
            allow_user_home=payload.get("allow_user_home") is True,
            native_consent_acknowledged=(
                payload.get("native_consent_acknowledged") is True
            ),
        )
    except IntegrationFlowNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="integration flow not found"
        ) from exc
    except (ValueError, IntegrationFlowConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrationFlowError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/api/integrations/flows/{flow_id}/rollback")
def rollback_integration(flow_id: str, request: Request) -> dict[str, Any]:
    """Roll back one exact application-owned transaction."""
    try:
        return request.app.state.harness_integration_flow_service.rollback(flow_id)
    except IntegrationFlowNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="integration flow not found"
        ) from exc
    except (ValueError, IntegrationFlowConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrationFlowError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
