from typing import Annotated

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
from starlette.requests import Request
from starlette.status import HTTP_401_UNAUTHORIZED

api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)


def verify_api_key(
    request: Request,
    api_key: Annotated[str | None, Security(api_key_header)],
    bearer: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)],
) -> str:
    """Verify API key from query parameter or header."""
    provided_key = None
    if bearer and bearer.credentials:
        provided_key = bearer.credentials.strip()
    elif api_key:
        provided_key = api_key.strip()

    if not provided_key:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED, detail="API key required"
        )

    config = request.app.state.config
    expected_key = getattr(config.proxy_settings, "api_key", None)
    if not expected_key:
        raise HTTPException(status_code=500, detail="API key not configured")

    if provided_key != expected_key:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    return provided_key
