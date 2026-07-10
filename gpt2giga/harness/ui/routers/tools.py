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
        "config_writes_enabled": False,
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
