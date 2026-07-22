"""Read-only Environment projection shared by Web and attached clients."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from gpt2giga_harness.environments import (
    EnvironmentCaptureError,
    GitEnvironmentProvider,
)
from gpt2giga_harness.sessions import SessionNotFoundError
from gpt2giga_harness.ui.async_execution import ConformantAPIRoute, run_in_threadpool


router = APIRouter(route_class=ConformantAPIRoute)


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
