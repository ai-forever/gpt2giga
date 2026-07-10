"""Public shell, packaged assets, health, and browser-session exchange."""

from __future__ import annotations

import re

from fastapi import APIRouter, Header, HTTPException, Response
from fastapi.responses import HTMLResponse

from gpt2giga.harness.ui.routers.schemas import (
    BrowserSessionResponse,
    UIHealthResponse,
)
from gpt2giga.harness.ui.security import HarnessUISecurity
from gpt2giga.harness.ui.static import INDEX_HTML, UIAssetNotFoundError, load_asset

_SPA_PATH = re.compile(r"(?:work|runs)(?:/[^/]+)?/?")


def create_shell_router(security: HarnessUISecurity) -> APIRouter:
    """Create the shell router; include it after every API router."""
    router = APIRouter()

    @router.get("/healthz", response_model=UIHealthResponse)
    async def health() -> UIHealthResponse:
        return UIHealthResponse()

    @router.post("/auth/session", response_model=BrowserSessionResponse)
    async def browser_session(
        response: Response,
        authorization: str | None = Header(default=None),
    ) -> BrowserSessionResponse:
        if not security.bootstrap_configured:
            raise HTTPException(
                status_code=403,
                detail="Remote browser authentication is not configured",
            )
        if not security.bootstrap_matches(authorization):
            raise HTTPException(status_code=401, detail="Invalid bootstrap token")
        security.set_session_cookie(response)
        return BrowserSessionResponse()

    @router.get("/assets/{asset_name:path}", include_in_schema=False)
    async def ui_asset(asset_name: str) -> Response:
        media_types = {
            "app.css": "text/css; charset=utf-8",
            "app.js": "text/javascript; charset=utf-8",
        }
        media_type = media_types.get(asset_name)
        if media_type is None:
            raise HTTPException(status_code=404, detail="UI asset not found")
        try:
            content = load_asset(asset_name)
        except UIAssetNotFoundError as exc:
            raise HTTPException(status_code=404, detail="UI asset not found") from exc
        return Response(
            content=content,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @router.get(
        "/{spa_path:path}", response_class=HTMLResponse, include_in_schema=False
    )
    async def spa_shell(spa_path: str) -> HTMLResponse:
        normalized = spa_path.strip("/")
        if normalized and _SPA_PATH.fullmatch(normalized) is None:
            raise HTTPException(status_code=404, detail="Not found")
        return HTMLResponse(INDEX_HTML, headers={"Cache-Control": "no-cache"})

    return router
