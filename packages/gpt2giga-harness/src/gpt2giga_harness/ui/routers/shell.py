"""Public shell, packaged assets, health, and browser-session exchange."""

from __future__ import annotations

import re
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from gpt2giga_harness.ui.async_execution import ConformantAPIRoute
from gpt2giga_harness.ui.routers.schemas import (
    BrowserSessionResponse,
    UIHealthResponse,
)
from gpt2giga_harness.ui.security import HarnessUISecurity
from gpt2giga_harness.ui.static import INDEX_HTML, UIAssetNotFoundError, load_asset
from gpt2giga_harness.ui.cockpit_v2 import (
    CockpitV2AssetNotFoundError,
    CockpitV2UnavailableError,
    load_cockpit_v2_asset,
    load_cockpit_v2_shell,
)

_SPA_PATH = re.compile(
    r"(?:(?:work|runs|workflows|scheduled)(?:/[^/]+)?|arena|agents|approvals|tools|evaluate)/?"
)
_COCKPIT_V2_PATH = re.compile(
    r"(?:work(?:/[^/]+)?|runs(?:/[^/]+)?|"
    r"automation(?:/(?:agents|workflows|schedules))?|"
    r"evaluation(?:/(?:arena|evals|baselines))?|"
    r"integrations(?:/(?:add|harnesses|models|mcp|doctor))?|settings)/?"
)
_COCKPIT_V2_SHELL_HEADERS = {
    "Cache-Control": "no-cache",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'; "
        "frame-src 'self'; object-src 'none'; worker-src 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}

_LEGACY_ROUTE_REDIRECTS = {
    "": "/cockpit-v2/work",
    "agents": "/cockpit-v2/automation/agents",
    "approvals": "/cockpit-v2/runs",
    "arena": "/cockpit-v2/evaluation/arena",
    "evaluate": "/cockpit-v2/evaluation/evals",
    "tools": "/cockpit-v2/integrations/mcp",
}


def _accepted_encoding(value: str | None) -> str:
    """Select supported on-demand gzip while honoring explicit q=0."""
    qualities: dict[str, float] = {}
    for item in (value or "").split(","):
        token, *parameters = item.strip().lower().split(";")
        if not token:
            continue
        quality = 1.0
        for parameter in parameters:
            key, separator, raw_value = parameter.strip().partition("=")
            if separator and key == "q":
                try:
                    quality = min(1.0, max(0.0, float(raw_value)))
                except ValueError:
                    quality = 0.0
        qualities[token] = quality
    gzip_quality = qualities.get("gzip", qualities.get("*", 0.0))
    if gzip_quality > 0:
        return "gzip"
    return "identity"


def _cockpit_unavailable(exc: CockpitV2UnavailableError) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=(
            "Cockpit V2 packaged assets are unavailable; use /legacy while the "
            "installation is repaired"
        ),
    )


def _default_cockpit_path(spa_path: str) -> str:
    """Map the retired default shell routes onto canonical Cockpit V2 URLs."""
    normalized = spa_path.strip("/")
    static_redirect = _LEGACY_ROUTE_REDIRECTS.get(normalized)
    if static_redirect is not None:
        return static_redirect
    route, _, selected_id = normalized.partition("/")
    if route in {"work", "runs"}:
        return f"/cockpit-v2/{normalized}"
    if route == "workflows":
        target = "/cockpit-v2/automation/workflows"
    elif route == "scheduled":
        target = "/cockpit-v2/automation/schedules"
    else:  # pragma: no cover - guarded by _SPA_PATH before this helper is called
        raise ValueError(f"unsupported legacy route: {normalized}")
    if not selected_id:
        return target
    return f"{target}?selected={quote(selected_id, safe='')}"


def _validated_local_redirect(target: str) -> str:
    """Require a relative Cockpit V2 redirect with no browser authority."""
    parsed = urlparse(target)
    if (
        parsed.scheme
        or parsed.netloc
        or "\\" in target
        or not parsed.path.startswith("/cockpit-v2/")
    ):
        raise ValueError("redirect target must stay within Cockpit V2")
    return target


def create_shell_router(security: HarnessUISecurity) -> APIRouter:
    """Create the shell router; include it after every API router."""
    router = APIRouter(route_class=ConformantAPIRoute)

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
    def ui_asset(asset_name: str) -> Response:
        media_types = {
            "app.css": "text/css; charset=utf-8",
            "app.js": "text/javascript; charset=utf-8",
            "favicon.ico": "image/vnd.microsoft.icon",
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

    @router.get("/cockpit-v2/assets/{asset_name:path}", include_in_schema=False)
    def cockpit_v2_asset(asset_name: str, request: Request) -> Response:
        encoding = _accepted_encoding(request.headers.get("accept-encoding"))
        try:
            content, asset = load_cockpit_v2_asset(asset_name, encoding=encoding)
        except CockpitV2AssetNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Cockpit V2 asset not found"
            ) from exc
        except CockpitV2UnavailableError as exc:
            raise _cockpit_unavailable(exc) from exc
        headers = {
            "Cache-Control": "public, max-age=31536000, immutable",
            "Vary": "Accept-Encoding",
            "X-Content-Type-Options": "nosniff",
        }
        has_encoded_variant = (encoding == "br" and asset.brotli_name is not None) or (
            encoding == "gzip" and (asset.gzip_name is not None or asset.compressible)
        )
        if has_encoded_variant:
            headers["Content-Encoding"] = encoding
        return Response(
            content=content,
            media_type=asset.media_type,
            headers=headers,
        )

    @router.get(
        "/cockpit-v2",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    @router.get(
        "/cockpit-v2/{spa_path:path}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def cockpit_v2_shell(spa_path: str = "") -> HTMLResponse:
        normalized = spa_path.strip("/")
        if normalized and _COCKPIT_V2_PATH.fullmatch(normalized) is None:
            raise HTTPException(status_code=404, detail="Not found")
        try:
            content = load_cockpit_v2_shell()
        except CockpitV2UnavailableError as exc:
            raise _cockpit_unavailable(exc) from exc
        return HTMLResponse(content, headers=_COCKPIT_V2_SHELL_HEADERS)

    @router.get(
        "/legacy",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    @router.get(
        "/legacy/{spa_path:path}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def legacy_shell(spa_path: str = "") -> HTMLResponse:
        normalized = spa_path.strip("/")
        if normalized and _SPA_PATH.fullmatch(normalized) is None:
            raise HTTPException(status_code=404, detail="Not found")
        return HTMLResponse(INDEX_HTML, headers={"Cache-Control": "no-cache"})

    @router.get(
        "/{spa_path:path}", response_class=RedirectResponse, include_in_schema=False
    )
    def spa_shell(spa_path: str) -> RedirectResponse:
        normalized = spa_path.strip("/")
        if normalized and _SPA_PATH.fullmatch(normalized) is None:
            raise HTTPException(status_code=404, detail="Not found")
        target = _validated_local_redirect(_default_cockpit_path(normalized))
        return RedirectResponse(
            target,
            status_code=307,
            headers={"Cache-Control": "no-cache"},
        )

    return router
