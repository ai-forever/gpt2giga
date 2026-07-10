"""Stable run deep-link API for the Harness cockpit."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from gpt2giga.harness.sessions.models import bundle_to_dict
from gpt2giga.harness.sessions.store import RunNotFoundError
from gpt2giga.harness.ui.routers.schemas import RunBundleResponse


router = APIRouter()


@router.get("/api/runs/{run_id}", response_model=RunBundleResponse)
async def run_bundle(run_id: str, request: Request) -> dict:
    """Resolve one run id to its complete persisted session bundle."""
    store = request.app.state.harness_session_store
    try:
        run = store.get_run(run_id)
        payload = bundle_to_dict(store.get_session_bundle(run.session_id))
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    payload["selected_run_id"] = run.id
    return payload
