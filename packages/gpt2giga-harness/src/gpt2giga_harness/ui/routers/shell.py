"""Public shell, packaged assets, health, and local browser-session controls."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from urllib.parse import parse_qs, quote, urlparse

import anyio
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from gpt2giga_harness.ui.async_execution import ConformantAPIRoute
from gpt2giga_harness.ui.routers.schemas import (
    BrowserAccessStatusResponse,
    BrowserSessionResponse,
    UIHealthResponse,
)
from gpt2giga_harness.ui.security import HarnessUISecurity
from gpt2giga_harness.ui.remote_identity import (
    REMOTE_TRANSACTION_COOKIE,
    RemoteIdentityError,
)
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
    r"plugins(?:/(?:all|mcp|plugins|skills))?|"
    r"integrations(?:/(?:add|harnesses|models|mcp|doctor))?|settings)/?"
)
_COCKPIT_V2_SHELL_HEADERS = {
    "Cache-Control": "no-cache",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'; "
        "frame-src 'self'; manifest-src 'self'; object-src 'none'; worker-src 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}
_LOCAL_ACCESS_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GigaLoom local access</title>
  <style>
    :root { color-scheme: light dark; font: 16px/1.5 system-ui, sans-serif; }
    body { min-height: 100vh; margin: 0; display: grid; place-items: center; background: #10131a; color: #f4f6fb; }
    main { width: min(32rem, calc(100vw - 2rem)); box-sizing: border-box; padding: 2rem; border: 1px solid #343b4b; border-radius: 1rem; background: #171c26; }
    h1 { margin-top: 0; font-size: 1.5rem; }
    p { color: #b8c0d1; }
    button { min-height: 2.75rem; padding: .65rem 1rem; border: 0; border-radius: .6rem; background: #77a7ff; color: #08111f; font: inherit; font-weight: 700; cursor: pointer; }
  </style>
</head>
<body>
  <main>
    <h1>Recover local GigaLoom access</h1>
    <p>The prior browser session is absent or expired. Continue only from this OS-local loopback UI. Recovery revokes every older local session.</p>
    <form action="/auth/local/recover" method="post">
      <button type="submit">Recover this browser</button>
    </form>
    <p>No access token is placed in a URL, browser storage, diagnostics, or project files.</p>
  </main>
</body>
</html>
"""

_LEGACY_ROUTE_REDIRECTS = {
    "": "/cockpit-v2/work",
    "agents": "/cockpit-v2/automation/agents",
    "approvals": "/cockpit-v2/runs",
    "arena": "/cockpit-v2/evaluation/arena",
    "evaluate": "/cockpit-v2/evaluation/evals",
    "tools": "/cockpit-v2/plugins/mcp",
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


def _utc_timestamp(value: float | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def create_shell_router(security: HarnessUISecurity) -> APIRouter:
    """Create the shell router; include it after every API router."""
    router = APIRouter(route_class=ConformantAPIRoute)

    @router.get("/healthz", response_model=UIHealthResponse)
    async def health() -> UIHealthResponse:
        return UIHealthResponse()

    @router.get("/auth/status", response_model=BrowserAccessStatusResponse)
    async def browser_access_status(request: Request) -> BrowserAccessStatusResponse:
        if not security.local_mode:
            session = security.remote_session(request)
            return BrowserAccessStatusResponse(
                local=False,
                authenticated=session is not None,
                expires_at=(
                    _utc_timestamp(session.expires_at) if session is not None else None
                ),
                idle_expires_at=(
                    _utc_timestamp(session.idle_expires_at)
                    if session is not None
                    else None
                ),
                actor_id=session.actor.actor_id if session is not None else None,
                role=session.actor.role if session is not None else None,
                session_id=session.session_id if session is not None else None,
                authentication_time=(
                    _utc_timestamp(session.actor.authentication_time)
                    if session is not None
                    else None
                ),
                recovery=(
                    "Log out this remote GigaLoom session."
                    if session is not None
                    else "Sign in through the configured OpenID Connect issuer."
                ),
            )
        status = security.local_status(request)
        return BrowserAccessStatusResponse(
            local=True,
            authenticated=status.authenticated,
            claimable=status.claimable,
            expires_at=_utc_timestamp(status.expires_at),
            recovery=status.recovery,
        )

    @router.post("/auth/logout", response_model=BrowserSessionResponse)
    async def browser_logout(
        request: Request,
        response: Response,
    ) -> BrowserSessionResponse:
        if security.local_mode:
            security.logout_local(request)
        else:
            security.revoke_remote_session(request)
        security.clear_session_cookie(response)
        return BrowserSessionResponse(authenticated=False)

    @router.get("/auth/oidc/login", include_in_schema=False)
    async def begin_remote_login(request: Request, next: str = "/cockpit-v2/work"):
        if security.local_mode:
            raise HTTPException(status_code=404, detail="Page not found")
        try:
            transaction, authorization_url = await anyio.to_thread.run_sync(
                security.begin_remote_login,
                next,
            )
        except RemoteIdentityError as exc:
            raise HTTPException(
                status_code=503,
                detail="Remote identity provider is unavailable",
            ) from exc
        response = RedirectResponse(authorization_url, status_code=303)
        security.set_transaction_cookie(response, transaction)
        return response

    @router.get("/auth/oidc/callback", include_in_schema=False)
    async def complete_remote_login(
        request: Request,
        code: str = "",
        state: str = "",
    ):
        if security.local_mode:
            raise HTTPException(status_code=404, detail="Page not found")

        def complete():
            return security.complete_remote_login(
                code=code,
                state=state,
                binding=request.cookies.get(REMOTE_TRANSACTION_COOKIE),
            )

        try:
            session, redirect_path = await anyio.to_thread.run_sync(complete)
        except RemoteIdentityError as exc:
            raise HTTPException(
                status_code=401,
                detail="Remote identity callback was rejected",
            ) from exc
        response = RedirectResponse(redirect_path, status_code=303)
        security.clear_transaction_cookie(response)
        security.set_remote_session_cookie(response, session)
        return response

    @router.post("/auth/oidc/backchannel-logout", include_in_schema=False)
    async def backchannel_logout(request: Request) -> Response:
        if security.local_mode:
            raise HTTPException(status_code=404, detail="Page not found")
        body = await request.body()
        if len(body) > 64 * 1024:
            raise HTTPException(status_code=413, detail="Logout request is too large")
        values = parse_qs(body.decode("utf-8", errors="strict"), strict_parsing=True)
        tokens = values.get("logout_token", [])
        if len(tokens) != 1:
            raise HTTPException(status_code=400, detail="Logout token is required")
        try:
            await anyio.to_thread.run_sync(
                security.apply_backchannel_logout,
                tokens[0],
            )
        except (RemoteIdentityError, ValueError) as exc:
            raise HTTPException(
                status_code=400,
                detail="Back-channel logout was rejected",
            ) from exc
        return Response(status_code=204)

    @router.post("/auth/remote/revoke-actor", include_in_schema=False)
    async def revoke_remote_actor(request: Request) -> dict[str, int]:
        if security.local_mode or security.remote_store is None:
            raise HTTPException(status_code=404, detail="Page not found")
        payload = await request.json()
        actor_id = payload.get("actor_id") if isinstance(payload, dict) else None
        if not isinstance(actor_id, str) or not re.fullmatch(
            r"oidc_[0-9a-f]{64}", actor_id
        ):
            raise HTTPException(status_code=422, detail="actor_id is invalid")
        revoked = await anyio.to_thread.run_sync(
            security.remote_store.revoke_actor,
            actor_id,
        )
        return {"revoked": revoked}

    @router.post("/auth/remote/revoke-all", include_in_schema=False)
    async def revoke_all_remote_sessions() -> dict[str, int]:
        if security.local_mode or security.remote_store is None:
            raise HTTPException(status_code=404, detail="Page not found")
        revoked = await anyio.to_thread.run_sync(security.remote_store.revoke_all)
        return {"revoked": revoked}

    @router.post("/auth/local/rotate", response_model=BrowserSessionResponse)
    async def rotate_local_browser_session(
        request: Request,
        response: Response,
    ) -> BrowserSessionResponse:
        if not security.local_mode:
            raise HTTPException(
                status_code=403,
                detail="Local access rotation requires a loopback listener",
            )
        session = security.rotate_local(request)
        if session is None:
            raise HTTPException(status_code=401, detail="Browser session required")
        security.set_session_cookie(response, session)
        return BrowserSessionResponse()

    @router.post("/auth/local/recover", include_in_schema=False)
    async def recover_local_browser_session(request: Request) -> Response:
        session = security.recover_local(request)
        if session is None:
            raise HTTPException(
                status_code=403,
                detail="Local recovery requires an explicit same-origin loopback request",
            )
        response = RedirectResponse("/cockpit-v2/settings", status_code=303)
        security.set_session_cookie(response, session)
        return response

    @router.get("/local-access", include_in_schema=False)
    async def local_access_page(request: Request) -> Response:
        if not security.local_mode:
            raise HTTPException(status_code=404, detail="Page not found")
        if security.has_session(request):
            return RedirectResponse("/cockpit-v2/settings", status_code=303)
        return HTMLResponse(
            _LOCAL_ACCESS_HTML,
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": (
                    "default-src 'none'; style-src 'unsafe-inline'; "
                    "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
                ),
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.get("/assets/{asset_name:path}", include_in_schema=False)
    def ui_asset(asset_name: str) -> Response:
        media_types = {
            "app.css": "text/css; charset=utf-8",
            "app.js": "text/javascript; charset=utf-8",
            "brand/gigaloom-mark.svg": "image/svg+xml",
            "brand/gigaloom-mark-dark.svg": "image/svg+xml",
            "brand/gigaloom-mask.svg": "image/svg+xml",
            "brand/gigaloom.webmanifest": "application/manifest+json",
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
