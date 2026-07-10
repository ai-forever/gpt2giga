"""MCP connection inventory, compatibility, discovery, and health APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from gpt2giga.harness.mcp import (
    MCPProbeHistoryStore,
    MCPTransport,
    build_mcp_inventory,
    mcp_descriptor_to_dict,
    mcp_probe_to_dict,
    probe_mcp_server,
)
from gpt2giga.harness.managed_mcp import (
    ManagedConfigConflictError,
    ManagedConfigOwnershipError,
    ManagedMCPConfigService,
    managed_config_plan_to_dict,
    managed_config_result_to_dict,
)
from gpt2giga.harness.project import (
    load_project_config,
    project_to_dict,
    resolve_project,
)
from gpt2giga.harness.runtime.policy import (
    EnforcementLevel,
    PermissionAction,
    PolicyContext,
    PolicyDecision,
    REVIEW_EVERY_ACTION_PROFILE,
    approval_request_to_dict,
)
from gpt2giga.harness.runtime.store import RuntimeCoordinationStore
from gpt2giga.tools import CompositeSecretResolver, EnvironmentSecretResolver


router = APIRouter()


@router.get("/api/tool-servers")
async def tool_inventory(
    request: Request,
    workspace: str | None = Query(default=None),
) -> dict[str, Any]:
    """Return redacted MCP descriptors, latest health, and compatibility."""
    project, descriptors, errors = _inventory(request, workspace)
    history = _history_store(request)
    registry = request.app.state.harness_registry
    rows = []
    for descriptor in descriptors:
        latest = history.list(descriptor.id, limit=1)
        targets = descriptor.harnesses or ("codex-cli", "claude-code", "gemini-cli")
        compatibility = []
        for harness_id in targets:
            try:
                harness = registry.get(harness_id)
            except Exception:
                compatibility.append({"harness_id": harness_id, "status": "missing"})
                continue
            availability = harness.availability()
            compatibility.append(
                {
                    "harness_id": harness_id,
                    "status": availability.status.value,
                    "reason": availability.reason,
                }
            )
        rows.append(
            {
                "descriptor": mcp_descriptor_to_dict(descriptor),
                "latest_probe": latest[0] if latest else None,
                "compatibility": compatibility,
            }
        )
    return {
        "project": project_to_dict(project),
        "servers": rows,
        "errors": list(errors),
        "execution_enabled": False,
        "config_writes_enabled": True,
    }


@router.get("/api/tool-servers/{server_id}")
async def tool_server_detail(
    server_id: str,
    request: Request,
    workspace: str | None = Query(default=None),
) -> dict[str, Any]:
    """Return one descriptor and its bounded probe history."""
    project, descriptors, _ = _inventory(request, workspace)
    descriptor = next((item for item in descriptors if item.id == server_id), None)
    if descriptor is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return {
        "project": project_to_dict(project),
        "descriptor": mcp_descriptor_to_dict(descriptor),
        "history": _history_store(request).list(server_id, limit=20),
    }


@router.post("/api/tool-servers/{server_id}/probe", response_model=None)
async def probe_tool_server(
    server_id: str,
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> Any:
    """Policy-gate, initialize, and discover without invoking a tool."""
    workspace = str(payload.get("workspace") or "").strip() or None
    project, descriptors, _ = _inventory(request, workspace)
    descriptor = next((item for item in descriptors if item.id == server_id), None)
    if descriptor is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    if not descriptor.enabled:
        raise HTTPException(status_code=409, detail="MCP server is disabled")

    if not descriptor.trusted:
        action = (
            PermissionAction.MCP_SERVER_START
            if descriptor.transport is MCPTransport.STDIO
            else PermissionAction.NETWORK_CONNECT
        )
        runtime_store = _runtime_store(request)
        context = PolicyContext(
            project_id=project.id,
            reason=(
                "Start an untrusted MCP server for metadata discovery."
                if descriptor.transport is MCPTransport.STDIO
                else "Connect to a new MCP network origin for metadata discovery."
            ),
            preview={
                "server_id": descriptor.id,
                "transport": descriptor.transport.value,
                "command": descriptor.command,
                "url": descriptor.url,
                "operation": "initialize and list capabilities only",
            },
        )
        resolution = request.app.state.harness_policy_engine.resolve(
            action,
            profile=REVIEW_EVERY_ACTION_PROFILE,
            context=context,
            enforcement=EnforcementLevel.ENFORCED_BY_HARNESS,
        )
        if resolution.decision is PolicyDecision.DENY:
            raise HTTPException(status_code=403, detail="MCP probe denied by policy")
        if resolution.decision is PolicyDecision.ASK:
            approval = runtime_store.create_approval_request(resolution, context)
            return JSONResponse(
                status_code=202,
                content={
                    "approval_required": True,
                    "approval": approval_request_to_dict(approval),
                },
            )

    resolver = getattr(request.app.state, "harness_secret_resolver", None)
    if resolver is None:
        resolver = CompositeSecretResolver((EnvironmentSecretResolver(),))
    result = await run_in_threadpool(probe_mcp_server, descriptor, resolver)
    _history_store(request).append(result)
    return {"probe": mcp_probe_to_dict(result)}


@router.post("/api/tool-config/preview")
async def preview_tool_config(
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Return the exact redacted managed-home config diff before apply."""
    workspace = str(payload.get("workspace") or "").strip() or None
    harness_id = str(payload.get("harness_id") or "").strip()
    project, descriptors, errors = _inventory(request, workspace)
    selected = _select_descriptors(descriptors, payload.get("server_ids"))
    if errors:
        raise HTTPException(status_code=400, detail="MCP inventory contains errors")
    try:
        plan = _config_service(request).preview(harness_id, project.id, selected)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "project": project_to_dict(project),
        "plan": managed_config_plan_to_dict(plan),
        "enforcement": "delegated_to_cli_sandbox",
        "tool_calls_observable": False,
    }


@router.post("/api/tool-config/apply")
async def apply_tool_config(
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Apply trusted MCP servers to one Harness-owned managed home."""
    workspace = str(payload.get("workspace") or "").strip() or None
    harness_id = str(payload.get("harness_id") or "").strip()
    expected_hash = str(payload.get("expected_hash") or "").strip()
    if not expected_hash:
        raise HTTPException(status_code=400, detail="expected_hash is required")
    project, descriptors, errors = _inventory(request, workspace)
    selected = _select_descriptors(descriptors, payload.get("server_ids"))
    if errors:
        raise HTTPException(status_code=400, detail="MCP inventory contains errors")
    untrusted = [item.id for item in selected if item.enabled and not item.trusted]
    if untrusted:
        raise HTTPException(
            status_code=409,
            detail=f"Only trusted MCP servers can be applied: {', '.join(untrusted)}",
        )
    try:
        result = _config_service(request).apply(
            harness_id,
            project.id,
            selected,
            expected_hash=expected_hash,
        )
    except (ManagedConfigConflictError, ManagedConfigOwnershipError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "project": project_to_dict(project),
        "provenance": managed_config_result_to_dict(result),
        "enforcement": "delegated_to_cli_sandbox",
        "tool_calls_observable": False,
    }


@router.post("/api/tool-config/rollback")
async def rollback_tool_config(
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Restore the last config backup for one managed home."""
    workspace = str(payload.get("workspace") or "").strip() or None
    harness_id = str(payload.get("harness_id") or "").strip()
    project, _descriptors, _errors = _inventory(request, workspace)
    try:
        result = _config_service(request).rollback(harness_id, project.id)
    except (ManagedConfigConflictError, ManagedConfigOwnershipError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "project": project_to_dict(project),
        "provenance": managed_config_result_to_dict(result),
    }


def _inventory(request: Request, workspace: str | None):
    config = request.app.state.harness_config
    try:
        project = resolve_project(workspace, data_dir=config.data_dir)
        loaded = load_project_config(project.root)
        descriptors, errors = build_mcp_inventory(loaded.tool_profiles)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return project, descriptors, errors


def _history_store(request: Request) -> MCPProbeHistoryStore:
    return MCPProbeHistoryStore(request.app.state.harness_config.data_dir)


def _runtime_store(request: Request) -> RuntimeCoordinationStore:
    store = getattr(request.app.state, "harness_runtime_store", None)
    if not isinstance(store, RuntimeCoordinationStore):
        raise HTTPException(
            status_code=409,
            detail="Durable runtime is required for MCP approvals",
        )
    return store


def _config_service(request: Request) -> ManagedMCPConfigService:
    manager = request.app.state.harness_native_process_manager
    return ManagedMCPConfigService(
        request.app.state.harness_config.data_dir,
        home_active=manager.is_home_active,
    )


def _select_descriptors(descriptors, raw_ids):
    if raw_ids is None:
        return descriptors
    if not isinstance(raw_ids, list) or not all(
        isinstance(item, str) and item.strip() for item in raw_ids
    ):
        raise HTTPException(status_code=400, detail="server_ids must be a string list")
    requested = set(raw_ids)
    known = {item.id for item in descriptors}
    missing = sorted(requested - known)
    if missing:
        raise HTTPException(
            status_code=404,
            detail=f"MCP servers not found: {', '.join(missing)}",
        )
    return tuple(item for item in descriptors if item.id in requested)
