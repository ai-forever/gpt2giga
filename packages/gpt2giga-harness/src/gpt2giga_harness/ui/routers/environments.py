"""Read-only Environment projection shared by Web and attached clients."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from gpt2giga_harness.environments import (
    EnvironmentCaptureError,
    GitEnvironmentProvider,
)
from gpt2giga_harness.sessions import SessionNotFoundError
from gpt2giga_harness.ui.async_execution import ConformantAPIRoute


router = APIRouter(route_class=ConformantAPIRoute)


@router.get("/api/environment")
def local_environment(
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
        snapshot = GitEnvironmentProvider().snapshot(workspace)
    except EnvironmentCaptureError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return {
        "environment": snapshot.to_dict(),
        "commit": {
            "ready": snapshot.staged_count > 0,
            "blocker": None if snapshot.staged_count > 0 else "no_staged_changes",
        },
        "issue_pr": {"status": "not_connected"},
        "freshness": {"status": "fresh", "captured_at": snapshot.captured_at},
    }
