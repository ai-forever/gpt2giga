import secrets
from typing import Annotated

from fastapi import HTTPException, Security
from fastapi.security import (
    APIKeyHeader,
    HTTPBearer,
    HTTPAuthorizationCredentials,
    APIKeyQuery,
)
from starlette.requests import Request
from starlette.status import HTTP_401_UNAUTHORIZED

api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)
gemini_api_key_header = APIKeyHeader(name="x-goog-api-key", auto_error=False)
api_key_query = APIKeyQuery(
    name="x-api-key", scheme_name="API key query", auto_error=False
)
gemini_key_query = APIKeyQuery(
    name="key", scheme_name="Gemini key query", auto_error=False
)
bearer_scheme = HTTPBearer(auto_error=False)


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


def _verify_provided_key(request: Request, provided_key: str | None) -> str:
    """Validate a provided key against the configured proxy API key."""
    if not provided_key:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED, detail="API key required"
        )

    config = request.app.state.config
    expected_key = getattr(config.proxy_settings, "api_key", None)
    if not expected_key:
        raise HTTPException(status_code=500, detail="API key not configured")

    if not secrets.compare_digest(provided_key, expected_key):
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    return provided_key


def verify_api_key(
    request: Request,
    header_param: Annotated[str | None, Security(api_key_header)] = None,
    query_param: Annotated[str | None, Security(api_key_query)] = None,
    gemini_header_param: Annotated[str | None, Security(gemini_api_key_header)] = None,
    gemini_query_param: Annotated[str | None, Security(gemini_key_query)] = None,
    bearer: Annotated[
        HTTPAuthorizationCredentials | None, Security(bearer_scheme)
    ] = None,
) -> str:
    """Verify API key from query parameter or header."""
    provided_key = _resolve_provided_key(
        request,
        header_param=header_param,
        query_param=query_param,
        bearer=bearer,
        gemini_header_param=gemini_header_param,
        gemini_query_param=gemini_query_param,
    )
    return _verify_provided_key(request, provided_key)


def verify_api_key_gemini(
    request: Request,
    header_param: Annotated[str | None, Security(api_key_header)] = None,
    query_param: Annotated[str | None, Security(api_key_query)] = None,
    gemini_header_param: Annotated[str | None, Security(gemini_api_key_header)] = None,
    gemini_query_param: Annotated[str | None, Security(gemini_key_query)] = None,
    bearer: Annotated[
        HTTPAuthorizationCredentials | None, Security(bearer_scheme)
    ] = None,
) -> str:
    """Verify API key and raise Gemini-style API errors."""
    from gpt2giga.protocol.gemini.response import GeminiAPIError

    try:
        provided_key = _resolve_provided_key(
            request,
            header_param=header_param,
            query_param=query_param,
            bearer=bearer,
            gemini_header_param=gemini_header_param,
            gemini_query_param=gemini_query_param,
        )
        return _verify_provided_key(request, provided_key)
    except HTTPException as exc:
        message = exc.detail if isinstance(exc.detail, str) else "Authentication failed"
        status = "UNAUTHENTICATED" if exc.status_code == 401 else "INTERNAL"
        raise GeminiAPIError(
            status_code=exc.status_code,
            status=status,
            message=message,
        ) from exc
