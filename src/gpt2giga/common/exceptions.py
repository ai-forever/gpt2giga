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
from gpt2giga.common.gemini_errors import gemini_error_payload, gemini_error_status
from gpt2giga.core.context import _infer_protocol, get_request_context
from gpt2giga.logger import rquid_context
from gpt2giga.providers.gigachat.model_resolution import UpstreamModelRequiredError
from gpt2giga.providers.gigachat.streaming import sdk_request_id, sdk_transport_error
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
        except HTTPException as e:
            if _public_protocol(_request_argument(args, kwargs)) == "gemini":
                detail = e.detail
                if isinstance(detail, dict):
                    detail = detail.get("error", detail)
                message = (
                    detail.get("message", "Request failed")
                    if isinstance(detail, dict)
                    else str(detail)
                )
                payload = gemini_error_payload(message, e.status_code)
                if isinstance(detail, dict) and detail.get("param") is not None:
                    payload["error"]["param"] = detail["param"]
                return JSONResponse(
                    status_code=e.status_code, content=payload, headers=e.headers
                )
            if isinstance(e.detail, str) and _resource_error_route(
                _request_argument(args, kwargs)
            ):
                error_type = {
                    401: "authentication_error",
                    403: "permission_error",
                    404: "not_found_error",
                    429: "rate_limit_error",
                }.get(
                    e.status_code,
                    "api_error" if e.status_code >= 500 else "invalid_request_error",
                )
                if _public_protocol(_request_argument(args, kwargs)) == "anthropic":
                    response = anthropic_compatibility_response(
                        e.detail, status_code=e.status_code, error_type=error_type
                    )
                    response.headers.update(e.headers or {})
                    return response
                return JSONResponse(
                    status_code=e.status_code,
                    content=openai_error_payload(e.detail, error_type=error_type),
                    headers=e.headers,
                )
            # Preserve FastAPI/Starlette semantics (status codes, details, headers).
            raise
        except ClientCompatibilityError as e:
            if _public_protocol(_request_argument(args, kwargs)) == "gemini":
                return JSONResponse(
                    status_code=e.status_code,
                    content=gemini_error_payload(e.message, e.status_code),
                )
            if e.provider == "anthropic":
                return anthropic_compatibility_response(
                    e.message,
                    status_code=e.status_code,
                    error_type=e.error_type,
                )
            if _resource_error_route(_request_argument(args, kwargs)):
                return JSONResponse(
                    status_code=e.status_code,
                    content=openai_error_payload(
                        e.message, error_type=e.error_type, param=e.param, code=e.code
                    ),
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
            if _public_protocol(_request_argument(args, kwargs)) == "gemini":
                return JSONResponse(
                    status_code=400,
                    content=gemini_error_payload(
                        UpstreamModelRequiredError.message, 400
                    ),
                )
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
            if _public_protocol(_request_argument(args, kwargs)) == "gemini":
                return JSONResponse(
                    status_code=429,
                    content=gemini_error_payload(MODEL_CONCURRENCY_LIMIT_MESSAGE, 429),
                )
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
            transport_error = sdk_transport_error(e)
            if transport_error is not None:
                status, code, message = transport_error
                response = _bridge_transport_error_response(
                    message,
                    code=code,
                    request=_request_argument(args, kwargs),
                    status_code=status,
                )
                request_id = sdk_request_id(e)
                if request_id:
                    response.headers["X-GigaChat-Request-ID"] = request_id
                return response
            request = _request_argument(args, kwargs)
            if request is not None and isinstance(e, gigachat.exceptions.ResponseError):
                status = getattr(e, "status_code", 502)
                response = _bridge_transport_error_response(
                    "The upstream request failed.",
                    code="upstream_error",
                    request=request,
                    status_code=status if isinstance(status, int) else 502,
                )
                request_id = sdk_request_id(e)
                if request_id:
                    response.headers["X-GigaChat-Request-ID"] = request_id
                return response
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
            if _public_protocol(_request_argument(args, kwargs)) == "gemini":
                return JSONResponse(
                    status_code=500,
                    content=gemini_error_payload("Internal server error", 500),
                )
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


def _resource_error_route(request: Request | None) -> bool:
    """Keep legacy admin/system errors while projecting public resource failures."""
    if request is None:
        return False
    path = request.url.path
    segments = path.strip("/").split("/")
    while segments and segments[0] in {"v1", "v2", "v1beta"}:
        segments.pop(0)
    return bool(
        segments
        and segments[0] in {"files", "batches", "responses", "conversations", "images"}
        or segments[:2] == ["messages", "batches"]
        or segments[:2] == ["bridge", "gigachat"]
    )


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
    status_code: int = 502,
) -> JSONResponse:
    protocol = _public_protocol(request)
    if protocol == "anthropic":
        return anthropic_compatibility_response(
            message,
            status_code=status_code,
            error_type="api_error",
            code=code,
        )
    if protocol == "gemini":
        return JSONResponse(
            status_code=status_code,
            content={
                "error": {
                    "code": status_code,
                    "message": message,
                    "status": _gemini_error_status(status_code),
                }
            },
        )
    return JSONResponse(
        status_code=status_code,
        content=openai_error_payload(
            message,
            error_type="api_error",
            param=None,
            code=code,
        ),
    )


def _public_protocol(request: Request | None) -> str:
    context = get_request_context()
    if context is not None:
        protocol = context.metadata.get("protocol") or context.protocol
        if protocol in {"anthropic", "gemini"}:
            return protocol
    path = request.url.path if request is not None else ""
    protocol = _infer_protocol(path)
    if protocol in {"anthropic", "gemini"}:
        return protocol
    if request is not None:
        shared_route = any(part in path.split("/") for part in ("models", "files"))
        if shared_route and (
            request.headers.get("anthropic-version")
            or request.headers.get("anthropic-beta")
        ):
            return "anthropic"
        if request.headers.get("x-goog-api-key") and "/models" in path:
            return "gemini"
    return protocol


def _gemini_error_status(status_code: int) -> str:
    return gemini_error_status(status_code)
