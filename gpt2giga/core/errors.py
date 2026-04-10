import asyncio
import json
from functools import wraps

import gigachat
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import JSONResponse

from gpt2giga.app.observability import set_request_audit_error
from gpt2giga.core.logging.setup import rquid_context, sanitize_for_utf8

ERROR_MAPPING = {
    gigachat.exceptions.BadRequestError: (400, "invalid_request_error", None),
    gigachat.exceptions.AuthenticationError: (
        401,
        "authentication_error",
        "invalid_api_key",
    ),
    gigachat.exceptions.ForbiddenError: (403, "permission_denied_error", None),
    gigachat.exceptions.NotFoundError: (404, "not_found_error", None),
    gigachat.exceptions.RequestEntityTooLargeError: (
        413,
        "invalid_request_error",
        None,
    ),
    gigachat.exceptions.RateLimitError: (429, "rate_limit_error", None),
    gigachat.exceptions.UnprocessableEntityError: (422, "invalid_request_error", None),
    gigachat.exceptions.ServerError: (500, "server_error", None),
}


def exceptions_handler(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        request = _find_request_arg(args, kwargs)
        try:
            return await func(*args, **kwargs)
        except asyncio.CancelledError:
            # Allow FastAPI/Starlette to handle client disconnects and cancellations cleanly,
            # especially for streaming endpoints.
            raise
        except HTTPException:
            _annotate_request_error(request, "HTTPException")
            # Preserve FastAPI/Starlette semantics (status codes, details, headers).
            raise
        except gigachat.exceptions.GigaChatException as e:
            _annotate_request_error(request, type(e).__name__)
            from loguru import logger

            rquid = rquid_context.get()
            safe_message = sanitize_for_utf8(str(e))
            logger.error(
                f"[{rquid}] GigaChatException: {type(e).__name__}: {safe_message}"
            )
            for exc_class, (status, error_type, code) in ERROR_MAPPING.items():
                if isinstance(e, exc_class):
                    raise HTTPException(
                        status_code=status,
                        detail={
                            "error": {
                                "message": safe_message,
                                "type": error_type,
                                "param": None,
                                "code": code,
                            }
                        },
                    )

            if isinstance(e, gigachat.exceptions.ResponseError):
                if hasattr(e, "status_code") and hasattr(e, "content"):
                    url = getattr(e, "url", "unknown")
                    status_code = e.status_code
                    message = e.content
                    try:
                        error_detail = json.loads(message)
                    except Exception:
                        error_detail = message
                        if isinstance(error_detail, bytes):
                            error_detail = error_detail.decode("utf-8", errors="ignore")
                    error_detail = sanitize_for_utf8(error_detail)
                    raise HTTPException(
                        status_code=status_code,
                        detail={
                            "url": str(url),
                            "error": error_detail,
                        },
                    )
                if len(e.args) == 4:
                    url, status_code, message, _ = e.args
                    try:
                        error_detail = json.loads(message)
                    except Exception:
                        error_detail = message
                        if isinstance(error_detail, bytes):
                            error_detail = error_detail.decode("utf-8", errors="ignore")
                    error_detail = sanitize_for_utf8(error_detail)
                    raise HTTPException(
                        status_code=status_code,
                        detail={
                            "url": str(url),
                            "error": error_detail,
                        },
                    )
                raise HTTPException(
                    status_code=500,
                    detail={
                        "error": "Unexpected ResponseError structure",
                        "args": e.args,
                    },
                )

            raise HTTPException(
                status_code=500,
                detail={
                    "error": "Unexpected GigaChatException",
                    "args": e.args,
                },
            )
        except Exception as e:
            _annotate_request_error(request, type(e).__name__)
            from loguru import logger

            rquid = rquid_context.get()
            safe_message = sanitize_for_utf8(str(e))
            logger.exception(
                f"[{rquid}] Unhandled exception: {type(e).__name__}: {safe_message}"
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "message": safe_message,
                        "type": "server_error",
                        "param": None,
                        "code": None,
                    }
                },
            )

    return wrapper


def _find_request_arg(args, kwargs) -> Request | None:
    for value in kwargs.values():
        if isinstance(value, Request):
            return value
    for value in args:
        if isinstance(value, Request):
            return value
    return None


def _annotate_request_error(request: Request | None, error_type: str) -> None:
    if request is not None:
        set_request_audit_error(request, error_type)
