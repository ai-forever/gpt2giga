"""Read-only Environment projection shared by Web and attached clients."""

from __future__ import annotations

import asyncio
from pathlib import Path
import threading
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from gpt2giga_harness.environment_actions import (
    EnvironmentCommitError,
)
from gpt2giga_harness.environments import (
    EnvironmentCaptureError,
    GitEnvironmentProvider,
)
from gpt2giga_harness.runtime.policy import PermissionAction, approval_binding_digest
from gpt2giga_harness.runtime.policy import approval_request_to_dict
from gpt2giga_harness.sessions import SessionNotFoundError
from gpt2giga_harness.ui.async_execution import ConformantAPIRoute, run_in_threadpool


router = APIRouter(route_class=ConformantAPIRoute)


@router.post("/api/environment/commit/preview")
async def preview_environment_commit(
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Persist one immutable HEAD/diff-bound local commit preview."""
    workspace, session = _commit_workspace(request, payload)
    service = request.app.state.harness_environment_commit_service
    if service is None:
        raise _git_unavailable()
    try:
        preview = await run_in_threadpool(
            service.preview,
            workspace,
            message=payload.get("message", ""),
            author_name=payload.get("author_name", ""),
            author_email=payload.get("author_email", ""),
        )
    except EnvironmentCommitError as exc:
        raise _commit_http_error(exc) from exc
    return {
        "preview": preview.to_dict(),
        "approval": {
            "required": True,
            "action": PermissionAction.GIT_COMMIT.value,
            "binding_sha256": approval_binding_digest(preview.approval_binding),
            "session_id": session.id if session is not None else None,
        },
    }


@router.post("/api/environment/commit/apply", response_model=None)
async def apply_environment_commit(
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any] | JSONResponse:
    """Apply one approved commit preview exactly once."""
    preview_id = payload.get("preview_id")
    if not isinstance(preview_id, str):
        raise HTTPException(status_code=422, detail="preview_id is required")
    service = request.app.state.harness_environment_commit_service
    coordinator = request.app.state.harness_governed_environment_commit_service
    if service is None:
        raise _git_unavailable()
    if coordinator is None:
        raise HTTPException(status_code=409, detail="Durable runtime is unavailable")
    try:
        preview = service.get_preview(preview_id)
        _, session = _commit_workspace(
            request,
            payload,
            expected_worktree=preview.worktree_root,
            workspace_optional=True,
        )
    except EnvironmentCommitError as exc:
        raise _commit_http_error(exc) from exc
    project_id = preview.scope_id
    if session is not None:
        project_id = str(session.metadata.get("project_id") or "") or preview.scope_id
    try:
        outcome = await run_in_threadpool(
            coordinator.apply_or_request,
            preview.id,
            project_id=project_id,
            session_id=session.id if session is not None else None,
        )
    except EnvironmentCommitError as exc:
        raise _commit_http_error(exc) from exc
    if outcome.approval is not None:
        return JSONResponse(
            status_code=202,
            content={
                "approval_required": True,
                "approval": approval_request_to_dict(outcome.approval),
                "preview": outcome.preview.to_dict(),
            },
        )
    if outcome.result is None:
        raise HTTPException(status_code=409, detail="Commit result is unavailable")
    return {
        "preview": outcome.preview.to_dict(),
        "result": outcome.result.to_dict(),
        "idempotent_replay": outcome.idempotent_replay,
    }


@router.get("/api/environment")
async def local_environment(
    request: Request,
    session_id: str | None = Query(default=None, min_length=1, max_length=512),
    workspace: str | None = Query(default=None, min_length=1, max_length=4096),
) -> dict[str, Any]:
    """Capture one bounded canonical local Git Environment snapshot."""
    if session_id is not None and workspace is not None:
        raise HTTPException(
            status_code=422,
            detail="Choose either session_id or workspace for Environment capture.",
        )
    if session_id is not None:
        try:
            session = request.app.state.harness_session_store.get_session(session_id)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        workspace = session.workspace
    if workspace is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "workspace_unavailable",
                "message": "Environment requires a workspace-bound session.",
            },
        )
    try:
        provider = GitEnvironmentProvider()

        def capture_local():
            snapshot = provider.snapshot(workspace)
            return snapshot, provider.hosted_repository(snapshot)

        snapshot, repository_hint = await run_in_threadpool(capture_local)
    except EnvironmentCaptureError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    cancel_event = threading.Event()
    try:
        github = await run_in_threadpool(
            request.app.state.harness_github_environment_service.inspect,
            snapshot,
            repository_hint,
            cancel_event=cancel_event,
        )
    except asyncio.CancelledError:
        cancel_event.set()
        raise
    issue_pr: dict[str, Any]
    if github.pull_request is None:
        issue_pr = {"status": "none" if github.status == "ready" else "not_connected"}
    else:
        issue_pr = {
            "status": github.pull_request.state,
            "kind": "pull_request",
            "number": github.pull_request.number,
            "url": github.pull_request.url,
            "checks": github.pull_request.checks.to_dict(),
            "issues": [item.to_dict() for item in github.pull_request.issues],
        }
    return {
        "environment": snapshot.to_dict(),
        "commit": {
            "ready": snapshot.staged_count > 0,
            "blocker": None if snapshot.staged_count > 0 else "no_staged_changes",
        },
        "github": github.to_dict(),
        "issue_pr": issue_pr,
        "freshness": {"status": "fresh", "captured_at": snapshot.captured_at},
    }


def _commit_workspace(
    request: Request,
    payload: dict[str, Any],
    *,
    expected_worktree: str | None = None,
    workspace_optional: bool = False,
):
    session_id = payload.get("session_id")
    workspace = payload.get("workspace")
    if session_id is not None and not isinstance(session_id, str):
        raise HTTPException(status_code=422, detail="session_id is invalid")
    if workspace is not None and not isinstance(workspace, str):
        raise HTTPException(status_code=422, detail="workspace is invalid")
    if session_id and workspace:
        raise HTTPException(status_code=422, detail="Choose session_id or workspace")
    session = None
    if session_id:
        try:
            session = request.app.state.harness_session_store.get_session(session_id)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        workspace = session.workspace
    if not workspace:
        if not workspace_optional:
            raise HTTPException(
                status_code=422, detail="workspace or session_id is required"
            )
        workspace = expected_worktree
    if expected_worktree is not None:
        try:
            resolved = Path(str(workspace)).expanduser().resolve()
            root = Path(expected_worktree).resolve()
        except OSError as exc:
            raise HTTPException(
                status_code=409, detail="Workspace is unavailable"
            ) from exc
        if resolved != root and not resolved.is_relative_to(root):
            raise HTTPException(
                status_code=409,
                detail={"code": "workspace_mismatch", "message": "Workspace changed."},
            )
    return str(workspace), session


def _commit_http_error(exc: EnvironmentCommitError) -> HTTPException:
    invalid = {"author_invalid", "message_invalid", "preview_invalid"}
    not_found = {"preview_not_found"}
    status = (
        422
        if exc.code in invalid
        else 404
        if exc.code in not_found
        else 403
        if exc.code == "policy_denied"
        else 409
    )
    return HTTPException(
        status_code=status, detail={"code": exc.code, "message": str(exc)}
    )


def _git_unavailable() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"code": "git_unavailable", "message": "Git is unavailable."},
    )
