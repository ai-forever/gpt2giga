"""API-key authentication helpers and scoped access checks."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import HTTPException, Security
from fastapi.security import (
    APIKeyHeader,
    APIKeyQuery,
    HTTPAuthorizationCredentials,
    HTTPBearer,
)
from starlette.requests import Request
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN

from gpt2giga.api.gemini.request import normalize_model_name
from gpt2giga.app.dependencies import get_config_from_state
from gpt2giga.core.config.settings import ScopedAPIKeySettings

api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)
gemini_api_key_header = APIKeyHeader(name="x-goog-api-key", auto_error=False)
api_key_query = APIKeyQuery(
    name="x-api-key", scheme_name="API key query", auto_error=False
)
gemini_key_query = APIKeyQuery(
    name="key", scheme_name="Gemini key query", auto_error=False
)
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class APIKeyContext:
    """Safe request-scoped metadata about the authenticated API key."""

    name: str
    source: Literal["global", "scoped"]
    provider: str | None
    endpoint: str | None
    model: str | None


def _resolve_provided_key(
    request: Request,
    header_param: str | None = None,
    query_param: str | None = None,
    bearer: HTTPAuthorizationCredentials | None = None,
    gemini_header_param: str | None = None,
    gemini_query_param: str | None = None,
) -> str | None:
    """Extract an API key from supported auth locations."""
    provided_key = None
    if bearer and bearer.credentials:
        provided_key = bearer.credentials.strip()
    elif query_param or header_param or gemini_query_param or gemini_header_param:
        provided_key = (
            query_param or header_param or gemini_query_param or gemini_header_param
        )
    else:
        auth_header = request.headers.get("authorization")
        x_api_key = request.headers.get("x-api-key")
        x_goog_api_key = request.headers.get("x-goog-api-key")
        query_key = request.query_params.get("key")
        if (
            auth_header
            and len(auth_header) > 7
            and auth_header[:7].lower() == "bearer "
        ):
            provided_key = auth_header[7:].strip()
        elif x_api_key:
            provided_key = x_api_key.strip()
        elif x_goog_api_key:
            provided_key = x_goog_api_key.strip()
        elif query_key:
            provided_key = query_key.strip()
    return provided_key


def _set_request_api_key_context(request: Request, context: APIKeyContext) -> None:
    """Persist safe auth metadata on request state for later middleware/use."""
    state = getattr(request, "state", None)
    if state is None:
        return
    setattr(state, "api_key_context", context)


def normalize_endpoint_id(path: str | None) -> str | None:
    """Normalize a route path into a stable endpoint identifier."""
    if not path:
        return None
    normalized = path.strip().strip("/")
    for prefix in ("v1/", "v1beta/"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    return normalized or None


def resolve_endpoint_id(request: Request) -> str | None:
    """Resolve the normalized endpoint identifier for the matched route."""
    scope = getattr(request, "scope", {})
    route = scope.get("route") if isinstance(scope, dict) else None
    route_path = getattr(route, "path_format", None) or getattr(route, "path", None)
    if isinstance(route_path, str):
        return normalize_endpoint_id(route_path)
    url = getattr(request, "url", None)
    raw_path = getattr(url, "path", None)
    if isinstance(raw_path, str):
        return normalize_endpoint_id(raw_path)
    return None


async def resolve_requested_model(
    request: Request,
    *,
    provider_name: str | None,
) -> str | None:
    """Extract a request model id from path params or JSON body when available."""
    path_params = getattr(request, "path_params", {}) or {}
    path_model = path_params.get("model")
    if isinstance(path_model, str) and path_model.strip():
        if provider_name == "gemini":
            return normalize_model_name(path_model)
        return path_model.strip()

    method = str(getattr(request, "method", "GET")).upper()
    if method not in {"POST", "PUT", "PATCH"}:
        return None

    body_reader = getattr(request, "body", None)
    if not callable(body_reader):
        return None

    body = await body_reader()
    if not body or not body.strip():
        return None

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    model = payload.get("model")
    if not isinstance(model, str) or not model.strip():
        return None

    normalized_model = model.strip()
    if provider_name == "gemini":
        return normalize_model_name(normalized_model)
    return normalized_model


def _raise_scope_denied(message: str) -> None:
    """Raise a consistent forbidden error for a scoped key violation."""
    raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail=message)


async def _authorize_scoped_key(
    request: Request,
    scoped_key: ScopedAPIKeySettings,
    *,
    provider_name: str | None,
    allow_scoped_keys: bool,
) -> APIKeyContext:
    """Validate scoped-key access against provider, endpoint, and model filters."""
    if not allow_scoped_keys:
        _raise_scope_denied("Scoped API key is not allowed for this route")

    endpoint_id = resolve_endpoint_id(request)
    model = None

    if scoped_key.providers is not None:
        if provider_name is None or provider_name not in scoped_key.providers:
            _raise_scope_denied("API key is not allowed for this provider")

    if scoped_key.endpoints is not None:
        if endpoint_id is None or endpoint_id not in scoped_key.endpoints:
            _raise_scope_denied("API key is not allowed for this endpoint")

    if scoped_key.models is not None:
        model = await resolve_requested_model(request, provider_name=provider_name)
        if model is None or model not in scoped_key.models:
            _raise_scope_denied("API key is not allowed for this model")

    return APIKeyContext(
        name=scoped_key.name or "scoped",
        source="scoped",
        provider=provider_name,
        endpoint=endpoint_id,
        model=model,
    )


async def _verify_provided_key(
    request: Request,
    provided_key: str | None,
    *,
    provider_name: str | None = None,
    allow_scoped_keys: bool = True,
) -> str:
    """Validate a provided key against the configured global/scoped keys."""
    if not provided_key:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED, detail="API key required"
        )

    config = get_config_from_state(request.app.state)
    proxy = config.proxy_settings
    expected_key = getattr(proxy, "api_key", None)
    if not expected_key:
        raise HTTPException(status_code=500, detail="API key not configured")

    if secrets.compare_digest(provided_key, expected_key):
        _set_request_api_key_context(
            request,
            APIKeyContext(
                name="global",
                source="global",
                provider=provider_name,
                endpoint=resolve_endpoint_id(request),
                model=None,
            ),
        )
        return provided_key

    for scoped_key_data in getattr(proxy, "scoped_api_keys", []):
        scoped_key = (
            scoped_key_data
            if isinstance(scoped_key_data, ScopedAPIKeySettings)
            else ScopedAPIKeySettings.model_validate(scoped_key_data)
        )
        if secrets.compare_digest(provided_key, scoped_key.key):
            context = await _authorize_scoped_key(
                request,
                scoped_key,
                provider_name=provider_name,
                allow_scoped_keys=allow_scoped_keys,
            )
            _set_request_api_key_context(request, context)
            return provided_key

    raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Invalid API key")


def build_api_key_verifier(
    *,
    provider_name: str | None = None,
    gemini_style: bool = False,
    allow_scoped_keys: bool = True,
):
    """Create an auth dependency with optional provider and error-style hints."""

    async def _verify(
        request: Request,
        header_param: Annotated[str | None, Security(api_key_header)] = None,
        query_param: Annotated[str | None, Security(api_key_query)] = None,
        gemini_header_param: Annotated[
            str | None, Security(gemini_api_key_header)
        ] = None,
        gemini_query_param: Annotated[str | None, Security(gemini_key_query)] = None,
        bearer: Annotated[
            HTTPAuthorizationCredentials | None, Security(bearer_scheme)
        ] = None,
    ) -> str:
        provided_key = _resolve_provided_key(
            request,
            header_param=header_param,
            query_param=query_param,
            bearer=bearer,
            gemini_header_param=gemini_header_param,
            gemini_query_param=gemini_query_param,
        )
        try:
            return await _verify_provided_key(
                request,
                provided_key,
                provider_name=provider_name,
                allow_scoped_keys=allow_scoped_keys,
            )
        except HTTPException as exc:
            if not gemini_style:
                raise

            from gpt2giga.api.gemini.request import GeminiAPIError

            message = (
                exc.detail if isinstance(exc.detail, str) else "Authentication failed"
            )
            status_map = {
                HTTP_401_UNAUTHORIZED: "UNAUTHENTICATED",
                HTTP_403_FORBIDDEN: "PERMISSION_DENIED",
            }
            raise GeminiAPIError(
                status_code=exc.status_code,
                status=status_map.get(exc.status_code, "INTERNAL"),
                message=message,
            ) from exc

    return _verify


verify_api_key = build_api_key_verifier()
verify_api_key_gemini = build_api_key_verifier(gemini_style=True)
