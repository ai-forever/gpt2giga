import json
import traceback
from functools import wraps
from typing import AsyncGenerator, Optional

import gigachat
from aioitertools import enumerate as aio_enumerate
from fastapi import HTTPException
from gigachat import GigaChat
from gigachat.models import Chat, Function, FunctionParameters
from gigachat.settings import SCOPE
from starlette.requests import Request

from gpt2giga.logger import rquid_context


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

    return wrapper


async def stream_chat_completion_generator(
    request: Request,
    model: str,
    chat_messages: Chat,
    response_id: str,
    giga_client: Optional[GigaChat] = None,
) -> AsyncGenerator[str, None]:
    if not giga_client:
        giga_client = request.app.state.gigachat_client
    logger = getattr(request.app.state, "logger", None)
    rquid = rquid_context.get()

    try:
        async for chunk in giga_client.astream(chat_messages):
            if await request.is_disconnected():
                if logger:
                    logger.info(f"[{rquid}] Client disconnected during streaming")
                break
            processed = request.app.state.response_processor.process_stream_chunk(
                chunk, model, response_id
            )
            yield f"data: {json.dumps(processed)}\n\n"

        yield "data: [DONE]\n\n"

    except gigachat.exceptions.GigaChatException as e:
        error_type = type(e).__name__
        error_message = str(e)
        if logger:
            logger.error(
                f"[{rquid}] GigaChat streaming error: {error_type}: {error_message}"
            )
        error_response = {
            "error": {
                "message": error_message,
                "type": error_type,
                "code": "stream_error",
            }
        }
        yield f"data: {json.dumps(error_response)}\n\n"
        yield "data: [DONE]\n\n"

    except Exception as e:
        error_type = type(e).__name__
        error_message = str(e)
        tb = traceback.format_exc()
        if logger:
            logger.error(
                f"[{rquid}] Unexpected streaming error: {error_type}: {error_message}\n{tb}"
            )
        error_response = {
            "error": {
                "message": f"Stream interrupted: {error_message}",
                "type": error_type,
                "code": "internal_error",
            }
        }
        yield f"data: {json.dumps(error_response)}\n\n"
        yield "data: [DONE]\n\n"


async def stream_responses_generator(
    request: Request,
    chat_messages: Chat,
    response_id: str,
    giga_client: Optional[GigaChat] = None,
) -> AsyncGenerator[str, None]:
    if not giga_client:
        giga_client = request.app.state.gigachat_client
    logger = getattr(request.app.state, "logger", None)
    rquid = rquid_context.get()

    try:
        async for i, chunk in aio_enumerate(giga_client.astream(chat_messages)):
            if await request.is_disconnected():
                if logger:
                    logger.info(f"[{rquid}] Client disconnected during streaming")
                break
            processed = (
                request.app.state.response_processor.process_stream_chunk_response(
                    chunk, sequence_number=i, response_id=response_id
                )
            )
            yield f"data: {json.dumps(processed)}\n\n"

        yield "data: [DONE]\n\n"

    except gigachat.exceptions.GigaChatException as e:
        error_type = type(e).__name__
        error_message = str(e)
        if logger:
            logger.error(
                f"[{rquid}] GigaChat streaming error: {error_type}: {error_message}"
            )
        error_response = {
            "error": {
                "message": error_message,
                "type": error_type,
                "code": "stream_error",
            }
        }
        yield f"data: {json.dumps(error_response)}\n\n"
        yield "data: [DONE]\n\n"

    except Exception as e:
        error_type = type(e).__name__
        error_message = str(e)
        tb = traceback.format_exc()
        if logger:
            logger.error(
                f"[{rquid}] Unexpected streaming error: {error_type}: {error_message}\n{tb}"
            )
        error_response = {
            "error": {
                "message": f"Stream interrupted: {error_message}",
                "type": error_type,
                "code": "internal_error",
            }
        }
        yield f"data: {json.dumps(error_response)}\n\n"
        yield "data: [DONE]\n\n"


def normalize_json_schema(schema: dict) -> dict:
    """
    Нормализует JSON Schema для совместимости с GigaChat.

    GigaChat требует, чтобы у каждого объекта (type: "object") были properties.
    Если properties отсутствуют, добавляем пустой объект.

    GigaChat не поддерживает anyOf/oneOf с type: null (Optional типы).
    Удаляем null варианты и упрощаем схему.

    Рекурсивно обрабатывает вложенные схемы.
    """

    # TODO: please help
    if not isinstance(schema, dict):
        return schema

    result = dict(schema)

    # Обрабатываем anyOf, oneOf - GigaChat SDK не поддерживает эти конструкции
    # Удаляем null типы и выбираем первый оставшийся вариант
    for key in ("anyOf", "oneOf"):
        if key in result and isinstance(result[key], list):
            # Фильтруем null типы
            filtered = [
                item
                for item in result[key]
                if not (isinstance(item, dict) and item.get("type") == "null")
            ]

            # Удаляем anyOf/oneOf - GigaChat SDK его не поддерживает
            del result[key]

            if len(filtered) >= 1:
                # Берём первый не-null вариант и разворачиваем на верхний уровень
                # GigaChat SDK всё равно теряет anyOf, лучше явно выбрать первый тип
                single = normalize_json_schema(filtered[0])
                for k, v in single.items():
                    if (
                        k not in result
                    ):  # Не перезаписываем существующие поля (description, default)
                        result[k] = v

    # Обрабатываем allOf (без удаления null)
    if "allOf" in result and isinstance(result["allOf"], list):
        result["allOf"] = [normalize_json_schema(item) for item in result["allOf"]]

    # Если это объект без properties, добавляем пустые properties
    schema_type = result.get("type")
    if schema_type == "object" and "properties" not in result:
        result["properties"] = {}

    # Рекурсивно обрабатываем properties
    if "properties" in result and isinstance(result["properties"], dict):
        result["properties"] = {
            key: normalize_json_schema(value)
            for key, value in result["properties"].items()
        }

    # Обрабатываем items для массивов
    if "items" in result:
        if isinstance(result["items"], dict):
            result["items"] = normalize_json_schema(result["items"])
        elif isinstance(result["items"], list):
            result["items"] = [normalize_json_schema(item) for item in result["items"]]

    # Обрабатываем additionalProperties если это схема
    if "additionalProperties" in result and isinstance(
        result["additionalProperties"], dict
    ):
        result["additionalProperties"] = normalize_json_schema(
            result["additionalProperties"]
        )

    # Обрабатываем $defs / definitions
    for key in ("$defs", "definitions"):
        if key in result and isinstance(result[key], dict):
            result[key] = {
                def_key: normalize_json_schema(def_value)
                for def_key, def_value in result[key].items()
            }

    return result


def convert_tool_to_giga_functions(data: dict):
    functions = []
    tools = data.get("tools", []) or data.get("functions", [])
    for tool in tools:
        if tool.get("function"):
            function = tool["function"]
            normalized_params = normalize_json_schema(function["parameters"])
            giga_function = Function(
                name=function["name"],
                description=function["description"],
                parameters=FunctionParameters(**normalized_params),
            )
        else:
            normalized_params = normalize_json_schema(tool["parameters"])
            giga_function = Function(
                name=tool["name"],
                description=tool["description"],
                parameters=FunctionParameters(**normalized_params),
            )
        functions.append(giga_function)
    return functions


def pass_token_to_gigachat(giga: GigaChat, token: str) -> GigaChat:
    giga._settings.credentials = None
    giga._settings.user = None
    giga._settings.password = None
    if token.startswith("giga-user-"):
        user, password = token.replace("giga-user-", "", 1).split(":")
        giga._settings.user = user
        giga._settings.password = password
    elif token.startswith("giga-cred-"):
        parts = token.replace("giga-cred-", "", 1).split(":")
        giga._settings.credentials = parts[0]
        giga._settings.scope = parts[1] if len(parts) > 1 else SCOPE
    elif token.startswith("giga-auth-"):
        giga._settings.access_token = token.replace("giga-auth-", "", 1)

    return giga
