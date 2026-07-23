"""Provider-neutral add-integration inventory and lifecycle API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request

from gpt2giga_harness.integration_flows import (
    IntegrationFlowConflictError,
    IntegrationFlowError,
    IntegrationFlowNotFoundError,
    integration_flow_record_to_dict,
)
from gpt2giga_harness.integration_groups import (
    IntegrationGroupConflictError,
    IntegrationGroupError,
    IntegrationGroupNotFoundError,
    integration_group_record_to_dict,
)
from gpt2giga_harness.integration_lifecycle import (
    IntegrationLifecycleConflictError,
    IntegrationLifecycleError,
    IntegrationLifecycleNotFoundError,
)
from gpt2giga_harness.ui.async_execution import ConformantAPIRoute


router = APIRouter(route_class=ConformantAPIRoute)


@router.get("/api/integrations")
def integration_inventory(request: Request) -> dict[str, Any]:
    """Return source, target, catalog, and recent operation projections."""
    inventory = request.app.state.harness_integration_flow_service.inventory()
    inventory["root_skills"] = (
        request.app.state.harness_skill_library_service.root_skills()
    )
    inventory["groups"] = [
        integration_group_record_to_dict(item)
        for item in request.app.state.harness_grouped_integration_service.list()
    ]
    inventory.update(
        request.app.state.harness_integration_lifecycle_service.inventory()
    )
    return inventory


@router.get("/api/integrations/search")
async def search_integrations(
    request: Request,
    q: str = Query(min_length=2, max_length=200),
    component: list[str] = Query(default=["skill", "mcp"]),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    """Search configured read-only skills.sh and NeuralDeep boundaries."""
    try:
        return await request.app.state.harness_skill_library_service.search(
            q,
            components=component,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/integrations/skills/preview")
def preview_skill(
    request: Request,
    preview_id: str = Query(min_length=1, max_length=512),
) -> dict[str, Any]:
    """Return bounded Skill markdown after explicit item selection."""
    try:
        return request.app.state.harness_skill_library_service.preview(preview_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Skill preview not found") from exc
    except (OSError, UnicodeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/integrations/git/inspect")
async def inspect_git_repository(
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Resolve a public GitHub repository to one immutable candidate list."""
    repository_url = payload.get("repository_url")
    ref = payload.get("ref")
    if not isinstance(repository_url, str) or not repository_url.strip():
        raise HTTPException(status_code=422, detail="repository_url is required")
    if ref is not None and not isinstance(ref, str):
        raise HTTPException(status_code=422, detail="ref must be a string")
    try:
        return await request.app.state.harness_skill_library_service.inspect_git(
            repository_url,
            ref=ref,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/integrations/git/import-skill")
def import_git_skill(
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Import one immutable inspected Skill into the offline catalog."""
    candidate_id = payload.get("candidate_id")
    if not isinstance(candidate_id, str):
        raise HTTPException(status_code=422, detail="candidate_id is required")
    try:
        entry = request.app.state.harness_skill_library_service.import_git_skill(
            candidate_id
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Git candidate not found") from exc
    except (OSError, UnicodeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "catalog_id": entry.catalog_id,
        "package_id": entry.package_id,
        "version": entry.version,
        "preview_id": f"catalog:{entry.catalog_id}",
    }


@router.post("/api/integrations/groups/preview")
def preview_integration_group(
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Persist one exact all-supported group or portable pack preview set."""
    try:
        return request.app.state.harness_grouped_integration_service.preview(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrationGroupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/integrations/groups/{group_id}")
def integration_group(group_id: str, request: Request) -> dict[str, Any]:
    """Return one durable content-free group transaction."""
    try:
        record = request.app.state.harness_grouped_integration_service.get(group_id)
    except (ValueError, IntegrationGroupNotFoundError) as exc:
        raise HTTPException(
            status_code=404, detail="integration group not found"
        ) from exc
    return {"group": integration_group_record_to_dict(record)}


@router.post("/api/integrations/groups/{group_id}/apply")
def apply_integration_group(
    group_id: str,
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Apply one exact group approval through ordered child transactions."""
    plan_id = payload.get("plan_id")
    authority = payload.get("authority")
    if not isinstance(plan_id, str) or not isinstance(authority, str):
        raise HTTPException(
            status_code=422, detail="plan_id and authority are required"
        )
    try:
        return request.app.state.harness_grouped_integration_service.apply(
            group_id,
            plan_id=plan_id,
            authority=authority,
            allow_network=payload.get("allow_network") is True,
            allow_user_home=payload.get("allow_user_home") is True,
            native_consent_acknowledged=(
                payload.get("native_consent_acknowledged") is True
            ),
        )
    except IntegrationGroupNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="integration group not found"
        ) from exc
    except (ValueError, IntegrationGroupConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrationGroupError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/api/integrations/groups/{group_id}/recover")
def recover_integration_group(group_id: str, request: Request) -> dict[str, Any]:
    """Retry only exact safe group compensation actions."""
    try:
        return request.app.state.harness_grouped_integration_service.recover(group_id)
    except IntegrationGroupNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="integration group not found"
        ) from exc
    except (ValueError, IntegrationGroupConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrationGroupError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/api/integrations/groups/{group_id}/rollback")
def rollback_integration_group(group_id: str, request: Request) -> dict[str, Any]:
    """Compensate every exact current child in reverse order."""
    try:
        return request.app.state.harness_grouped_integration_service.rollback(group_id)
    except IntegrationGroupNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="integration group not found"
        ) from exc
    except (ValueError, IntegrationGroupConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrationGroupError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/api/integrations/groups/{group_id}/lifecycle/preview")
def preview_group_lifecycle(
    group_id: str,
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Preview one distinct lifecycle verb across every verified group child."""
    action = payload.get("action")
    if not isinstance(action, str):
        raise HTTPException(status_code=422, detail="action is required")
    try:
        return request.app.state.harness_integration_lifecycle_service.preview_group(
            group_id,
            action,
        )
    except IntegrationGroupNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="integration group not found"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrationLifecycleConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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


@router.post("/api/integrations/flows/{flow_id}/lifecycle/preview")
def preview_flow_lifecycle(
    flow_id: str,
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Preview one exact enable, disable, uninstall, or definition delete."""
    action = payload.get("action")
    if not isinstance(action, str):
        raise HTTPException(status_code=422, detail="action is required")
    try:
        return request.app.state.harness_integration_lifecycle_service.preview_flow(
            flow_id,
            action,
        )
    except IntegrationFlowNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="integration flow not found"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrationLifecycleConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/integrations/lifecycle/{operation_id}/apply")
def apply_integration_lifecycle(
    operation_id: str,
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Apply an exact approved lifecycle preview and return a recovery receipt."""
    plan_id = payload.get("plan_id")
    authority = payload.get("authority")
    expected_revisions = payload.get("expected_revisions")
    if (
        not isinstance(plan_id, str)
        or not isinstance(authority, str)
        or not isinstance(expected_revisions, dict)
    ):
        raise HTTPException(
            status_code=422,
            detail="plan_id, authority, and expected_revisions are required",
        )
    confirm_id = payload.get("confirm_id")
    if confirm_id is not None and not isinstance(confirm_id, str):
        raise HTTPException(status_code=422, detail="confirm_id must be a string")
    try:
        return request.app.state.harness_integration_lifecycle_service.apply(
            operation_id,
            plan_id=plan_id,
            authority=authority,
            expected_revisions=expected_revisions,
            confirm_id=confirm_id,
            allow_user_home=payload.get("allow_user_home") is True,
        )
    except IntegrationLifecycleNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="integration lifecycle operation not found"
        ) from exc
    except (ValueError, IntegrationLifecycleConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrationLifecycleError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
