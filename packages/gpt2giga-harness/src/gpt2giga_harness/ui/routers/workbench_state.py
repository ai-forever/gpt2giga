"""Provider-neutral Workbench snapshot and delta API."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from gpt2giga_harness.ui.async_execution import ConformantAPIRoute
from gpt2giga_harness.workbench_protocol import workbench_state_page_to_dict


router = APIRouter(route_class=ConformantAPIRoute)


@router.get("/api/workbench/state")
async def workbench_state(
    request: Request,
    cursor: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=32, ge=1, le=32),
) -> dict[str, object]:
    """Return one bounded authoritative snapshot plus ordered reconnect deltas."""
    page = request.app.state.harness_workbench_backbone.read(cursor, limit=limit)
    return workbench_state_page_to_dict(page)
