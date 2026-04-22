"""Admin access helpers for bootstrap and protected console routes."""

from __future__ import annotations

import ipaddress
import secrets
from typing import Annotated

from fastapi import HTTPException, Security
from fastapi.security import (
    APIKeyHeader,
    APIKeyQuery,
    HTTPAuthorizationCredentials,
    HTTPBearer,
)
from starlette.requests import Request
from starlette.status import (
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_503_SERVICE_UNAVAILABLE,
)

from gpt2giga.api.dependencies.auth import (
    resolve_provided_api_key,
    verify_provided_api_key,
)
from gpt2giga.app.admin_ui import get_admin_setup_path
from gpt2giga.app.dependencies import get_config_from_state
from gpt2giga.core.config.control_plane import (
    load_bootstrap_token,
    requires_admin_bootstrap,
)
from gpt2giga.core.http import resolve_client_ip

_admin_api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)
_admin_api_key_query = APIKeyQuery(
    name="x-api-key", scheme_name="Admin API key query", auto_error=False
)
_admin_bearer_scheme = HTTPBearer(auto_error=False)
ADMIN_AUTH_COOKIE_NAME = "gpt2giga_admin_key"

_BOOTSTRAP_ADMIN_API_ROUTES = {
    "/admin/api/setup",
    "/admin/api/setup/claim",
    "/admin/api/runtime",
    "/admin/api/settings/application",
    "/admin/api/settings/gigachat",
    "/admin/api/settings/security",
    "/admin/api/settings/gigachat/test",
    "/admin/api/keys",
    "/admin/api/keys/global/rotate",
    "/admin/api/keys/scoped",
    "/admin/api/keys/scoped/{name}/rotate",
    "/admin/api/keys/scoped/{name}",
}


def get_client_ip(request: Request) -> str:
    """Resolve the request client IP using the configured proxy-trust policy."""
    config = get_config_from_state(request.app.state)
    return (
        resolve_client_ip(
            request,
            trusted_proxy_cidrs=config.proxy_settings.trusted_proxy_cidrs,
        )
        or ""
    )


def _route_path(request: Request) -> str:
    """Return the resolved route path format when available."""
    scope = getattr(request, "scope", {})
    route = scope.get("route") if isinstance(scope, dict) else None
    route_path = getattr(route, "path_format", None) or getattr(route, "path", None)
    if isinstance(route_path, str):
        return route_path
    return str(request.url.path)


def _is_localhost_request(request: Request) -> bool:
    """Return whether the request comes from a loopback/test client."""
    client_ip = get_client_ip(request)
    if client_ip in {"localhost", "testclient"}:
        return True
    try:
        return ipaddress.ip_address(client_ip).is_loopback
    except ValueError:
        return False


def verify_admin_ip_allowlist(request: Request) -> None:
    """Deny admin access if the client IP is not in the configured allowlist."""
    config = get_config_from_state(request.app.state)
    allowlist = getattr(config.proxy_settings, "logs_ip_allowlist", None)
    if not allowlist:
        return

    client_ip = get_client_ip(request)
    if client_ip not in allowlist:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Access denied: IP not in admin allowlist",
        )


def _is_bootstrap_route(request: Request) -> bool:
    """Return whether the route is allowed during first-run bootstrap."""
    route_path = _route_path(request)
    if route_path.startswith("/admin/api/"):
        return route_path in _BOOTSTRAP_ADMIN_API_ROUTES
    return route_path == "/admin" or route_path.startswith("/admin/")


def _bootstrap_bypass_allowed(request: Request, provided_key: str | None) -> bool:
    """Return whether localhost or the bootstrap token can access this route."""
    if not _is_bootstrap_route(request):
        return False
    if _is_localhost_request(request):
        return True
    bootstrap_token = load_bootstrap_token(create=True)
    return bool(
        bootstrap_token
        and provided_key
        and secrets.compare_digest(provided_key, bootstrap_token)
    )


def build_admin_access_verifier():
    """Create an admin-only auth dependency with first-run bootstrap bypass."""

    async def _verify(
        request: Request,
        header_param: Annotated[str | None, Security(_admin_api_key_header)] = None,
        query_param: Annotated[str | None, Security(_admin_api_key_query)] = None,
        bearer: Annotated[
            HTTPAuthorizationCredentials | None, Security(_admin_bearer_scheme)
        ] = None,
    ) -> str:
        provided_key = resolve_provided_api_key(
            request,
            header_param=header_param,
            query_param=query_param,
            bearer=bearer,
        )
        if provided_key is None:
            provided_key = request.cookies.get(ADMIN_AUTH_COOKIE_NAME)
        config = get_config_from_state(request.app.state)
        bootstrap_required = requires_admin_bootstrap(config)
        setup_path = get_admin_setup_path(config)

        if bootstrap_required and _bootstrap_bypass_allowed(request, provided_key):
            return provided_key or "__bootstrap_local__"

        if config.proxy_settings.api_key:
            return await verify_provided_api_key(
                request,
                provided_key,
                provider_name=None,
                allow_scoped_keys=False,
            )

        if bootstrap_required:
            if _is_bootstrap_route(request):
                raise HTTPException(
                    status_code=HTTP_401_UNAUTHORIZED,
                    detail=(
                        "Admin bootstrap access requires localhost or the bootstrap token "
                        f"until {setup_path} is complete."
                    ),
                )
            raise HTTPException(
                status_code=HTTP_403_FORBIDDEN,
                detail=f"This admin route is unavailable until {setup_path} is complete.",
            )

        raise HTTPException(
            status_code=HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin authentication is not configured.",
        )

    return _verify
