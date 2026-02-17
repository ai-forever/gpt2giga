import json

from fastapi import HTTPException
from starlette.requests import Request


async def read_request_json(request: Request) -> dict:
    """Read and parse JSON request body.

    Returns:
        Parsed JSON body as dict.

    Raises:
        HTTPException: If body is empty or invalid JSON.
    """
    body = await request.body()
    if not body or not body.strip():
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": "Request body is empty (expected JSON).",
                    "type": "invalid_request_error",
                    "param": None,
                    "code": "invalid_json",
                }
            },
        )
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": f"Invalid JSON body: {e.msg}",
                    "type": "invalid_request_error",
                    "param": None,
                    "code": "invalid_json",
                }
            },
        )
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": "Invalid JSON body: expected an object at the top level.",
                    "type": "invalid_request_error",
                    "param": None,
                    "code": "invalid_json",
                }
            },
        )
    return data
