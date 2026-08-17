import asyncio
import json
from functools import wraps

import gigachat
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from gpt2giga.common.client_params import (
    ClientCompatibilityError,
    anthropic_compatibility_response,
    openai_compatibility_error,
    openai_error_payload,
)
from gpt2giga.common.model_concurrency import (
    MODEL_CONCURRENCY_LIMIT_MESSAGE,
    ModelConcurrencyTimeoutError,
)
from gpt2giga.logger import rquid_context
from gpt2giga.providers.gigachat.model_resolution import UpstreamModelRequiredError
from gpt2giga.providers.network import ProviderNetworkAuthorizationError
from gpt2giga.providers.openai_compatible import OpenAICompatibleUpstreamError

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
        try:
            return await func(*args, **kwargs)
        except asyncio.CancelledError:
            # Allow FastAPI/Starlette to handle client disconnects and cancellations cleanly,
            # especially for streaming endpoints.
            raise
        except HTTPException:
            # Preserve FastAPI/Starlette semantics (status codes, details, headers).
            raise
        except ClientCompatibilityError as e:
            if e.provider == "anthropic":
                return anthropic_compatibility_response(
                    e.message,
                    status_code=e.status_code,
                    error_type=e.error_type,
                )
            raise openai_compatibility_error(
                e.message,
                status_code=e.status_code,
                param=e.param,
                code=e.code,
                error_type=e.error_type,
            )
        except (
            UpstreamModelRequiredError,
            gigachat.exceptions.ModelNotSpecifiedError,
        ) as e:
            provider = getattr(e, "provider", "openai")
            if provider == "anthropic":
                return anthropic_compatibility_response(
                    UpstreamModelRequiredError.message,
                    status_code=400,
                    error_type="invalid_request_error",
                    code="model_required",
                )
            return JSONResponse(
                status_code=400,
                content=openai_error_payload(
                    UpstreamModelRequiredError.message,
                    error_type="invalid_request_error",
                    param="model",
                    code="model_required",
                ),
            )
        except ModelConcurrencyTimeoutError as e:
            from loguru import logger

            logger.bind(
                event="model_concurrency_timeout",
                provider=e.provider,
                model=e.model,
                limit=e.limit,
            ).warning(str(e))
            if e.provider == "anthropic":
                return anthropic_compatibility_response(
                    MODEL_CONCURRENCY_LIMIT_MESSAGE,
                    status_code=429,
                    error_type="rate_limit_error",
                    code="model_concurrency_limit",
                )
            return JSONResponse(
                status_code=429,
                content=openai_error_payload(
                    MODEL_CONCURRENCY_LIMIT_MESSAGE,
                    error_type="rate_limit_error",
                    param="model",
                    code="model_concurrency_limit",
                ),
            )
        except gigachat.exceptions.GigaChatException as e:
            # Log the exception with context
            from loguru import logger

            rquid = rquid_context.get()
            logger.error(f"[{rquid}] GigaChatException: {type(e).__name__}: {e}")
            for exc_class, (status, error_type, code) in ERROR_MAPPING.items():
                if isinstance(e, exc_class):
                    raise HTTPException(
                        status_code=status,
                        detail={
                            "error": {
                                "message": str(e),
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
                    raise HTTPException(
                        status_code=status_code,
                        detail={
                            "url": str(url),
                            "error": error_detail,
                        },
                    )
                elif len(e.args) == 4:
                    url, status_code, message, _ = e.args
                    try:
                        error_detail = json.loads(message)
                    except Exception:
                        error_detail = message
                        if isinstance(error_detail, bytes):
                            error_detail = error_detail.decode("utf-8", errors="ignore")
                    raise HTTPException(
                        status_code=status_code,
                        detail={
                            "url": str(url),
                            "error": error_detail,
                        },
                    )
                else:
                    raise HTTPException(
                        status_code=500,
                        detail={
                            "error": "Unexpected ResponseError structure",
                            "args": e.args,
                        },
                    )

            # Fallback for unexpected GigaChatException
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "Unexpected GigaChatException",
                    "args": e.args,
                },
            )
        except OpenAICompatibleUpstreamError as e:
            request = _request_argument(args, kwargs)
            return _openai_compatible_error_response(e, request=request)
        except ProviderNetworkAuthorizationError as e:
            request = _request_argument(args, kwargs)
            return _bridge_transport_error_response(
                "The upstream destination could not be authorized.",
                code=e.code,
                request=request,
            )
        except Exception as e:
            from loguru import logger

            rquid = rquid_context.get()
            logger.exception(f"[{rquid}] Unhandled exception: {type(e).__name__}: {e}")
            return JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "message": "Internal server error",
                        "type": "server_error",
                        "param": None,
                        "code": None,
                    }
                },
            )

    return wrapper


def _request_argument(args: tuple, kwargs: dict) -> Request | None:
    for value in (*args, *kwargs.values()):
        if isinstance(value, Request):
            return value
    return None


def _openai_compatible_error_response(
    error: OpenAICompatibleUpstreamError,
    *,
    request: Request | None,
) -> JSONResponse:
    status_code = error.status_code or 502
    normalized = error.error
    protocol = _public_protocol(request)
    if protocol == "anthropic":
        error_types = {
            "authentication": "authentication_error",
            "permission": "permission_error",
            "not_found": "not_found_error",
            "rate_limit": "rate_limit_error",
            "invalid_request": "invalid_request_error",
        }
        return anthropic_compatibility_response(
            normalized.message,
            status_code=status_code,
            error_type=error_types.get(normalized.error_class, "api_error"),
            code=str(normalized.code) if normalized.code is not None else None,
        )
    if protocol == "gemini":
        return JSONResponse(
            status_code=status_code,
            content={
                "error": {
                    "code": status_code,
                    "message": normalized.message,
                    "status": _gemini_error_status(status_code),
                }
            },
        )
    return JSONResponse(
        status_code=status_code,
        content=openai_error_payload(
            normalized.message,
            error_type=normalized.type,
            param=normalized.param,
            code=str(normalized.code) if normalized.code is not None else None,
        ),
    )


def _bridge_transport_error_response(
    message: str,
    *,
    code: str,
    request: Request | None,
) -> JSONResponse:
    protocol = _public_protocol(request)
    if protocol == "anthropic":
        return anthropic_compatibility_response(
            message,
            status_code=502,
            error_type="api_error",
            code=code,
        )
    if protocol == "gemini":
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "code": 502,
                    "message": message,
                    "status": "UNAVAILABLE",
                }
            },
        )
    return JSONResponse(
        status_code=502,
        content=openai_error_payload(
            message,
            error_type="api_error",
            param=None,
            code=code,
        ),
    )


def _public_protocol(request: Request | None) -> str:
    path = request.url.path if request is not None else ""
    if "/messages" in path:
        return "anthropic"
    if "generateContent" in path or "countTokens" in path:
        return "gemini"
    return "openai"


def _gemini_error_status(status_code: int) -> str:
    return {
        400: "INVALID_ARGUMENT",
        401: "UNAUTHENTICATED",
        403: "PERMISSION_DENIED",
        404: "NOT_FOUND",
        408: "DEADLINE_EXCEEDED",
        429: "RESOURCE_EXHAUSTED",
    }.get(status_code, "UNAVAILABLE" if status_code >= 500 else "UNKNOWN")
