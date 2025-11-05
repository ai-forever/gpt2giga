from fastapi import HTTPException
from starlette.requests import Request


def verify_api_key(request: Request) -> str:
    """Verify API key from query parameter or header."""
    auth_header = request.headers.get("authorization")
    x_api_key = request.headers.get("x-api-key")
    provided_key = None
    if auth_header and auth_header.lower().startswith("bearer "):
        provided_key = auth_header.split(" ", 1)[1].strip()
    elif x_api_key:
        provided_key = x_api_key.strip()
    if not provided_key:
        raise HTTPException(status_code=401, detail="API key required")

    try:
        config = request.app.state.config
        expected_key = getattr(config.proxy_settings, "api_key", None)
        if not expected_key:
            raise HTTPException(status_code=500, detail="API key not configured")

        if provided_key != expected_key:
            raise HTTPException(status_code=401, detail="Invalid API key")
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return provided_key
