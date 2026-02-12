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
    request_data: Optional[dict] = None,
) -> AsyncGenerator[str, None]:
    if not giga_client:
        giga_client = request.app.state.gigachat_client
    logger = getattr(request.app.state, "logger", None)
    rquid = rquid_context.get()
    import time

    created_at = int(time.time())
    model = request_data.get("model", "unknown") if request_data else "unknown"
    msg_id = f"msg_{response_id}"
    fc_id = f"fc_{response_id}"  # ID for function call item

    # Helper to format SSE event
    def sse_event(event_type: str, data: dict) -> str:
        return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

    # Build base response object for lifecycle events
    def build_response_obj(status: str, output: list = None, usage: dict = None):
        return {
            "id": f"resp_{response_id}",
            "object": "response",
            "created_at": created_at,
            "status": status,
            "error": None,
            "incomplete_details": None,
            "instructions": request_data.get("instructions") if request_data else None,
            "max_output_tokens": (
                request_data.get("max_output_tokens") if request_data else None
            ),
            "model": model,
            "output": output or [],
            "parallel_tool_calls": True,
            "previous_response_id": None,
            "reasoning": {"effort": None, "summary": None},
            "store": True,
            "temperature": request_data.get("temperature", 1) if request_data else 1,
            "text": {"format": {"type": "text"}},
            "tool_choice": "auto",
            "tools": [],
            "top_p": request_data.get("top_p", 1) if request_data else 1,
            "truncation": "disabled",
            "usage": usage,
            "user": None,
            "metadata": {},
        }

    sequence_number = 0

    try:
        # Emit response.created
        yield sse_event(
            "response.created",
            {
                "type": "response.created",
                "response": build_response_obj("in_progress"),
                "sequence_number": sequence_number,
            },
        )
        sequence_number += 1

        # Emit response.in_progress
        yield sse_event(
            "response.in_progress",
            {
                "type": "response.in_progress",
                "response": build_response_obj("in_progress"),
                "sequence_number": sequence_number,
            },
        )
        sequence_number += 1

        # Track response type and content
        full_text = ""
        function_call_data = None  # Will hold {"name": ..., "arguments": ...}
        functions_state_id = None
        output_item_added = False
        is_function_call = False

        async for i, chunk in aio_enumerate(giga_client.astream(chat_messages)):
            if await request.is_disconnected():
                if logger:
                    logger.info(f"[{rquid}] Client disconnected during streaming")
                break

            giga_dict = chunk.model_dump()
            choice = giga_dict["choices"][0]
            delta = choice.get("delta", {})
            delta_content = delta.get("content", "")
            delta_function_call = delta.get("function_call")

            # Handle function call
            if delta_function_call:
                is_function_call = True
                if functions_state_id is None:
                    functions_state_id = delta.get("functions_state_id")

                # Initialize function_call_data on first chunk
                if function_call_data is None:
                    function_call_data = {
                        "name": delta_function_call.get("name", ""),
                        "arguments": "",
                    }
                    # Emit output_item.added for function_call
                    yield sse_event(
                        "response.output_item.added",
                        {
                            "type": "response.output_item.added",
                            "output_index": 0,
                            "item": {
                                "id": fc_id,
                                "type": "function_call",
                                "status": "in_progress",
                                "call_id": f"call_{response_id}",
                                "name": function_call_data["name"],
                                "arguments": "",
                            },
                            "sequence_number": sequence_number,
                        },
                    )
                    sequence_number += 1
                    output_item_added = True

                # Update function name if provided
                if delta_function_call.get("name"):
                    function_call_data["name"] = delta_function_call["name"]

                # Handle arguments - can be string or dict from GigaChat
                args = delta_function_call.get("arguments")
                if args is not None:
                    if isinstance(args, dict):
                        args_str = json.dumps(args, ensure_ascii=False)
                    else:
                        args_str = str(args)

                    if args_str:
                        # Emit function_call_arguments.delta
                        yield sse_event(
                            "response.function_call_arguments.delta",
                            {
                                "type": "response.function_call_arguments.delta",
                                "item_id": fc_id,
                                "output_index": 0,
                                "delta": args_str,
                                "sequence_number": sequence_number,
                            },
                        )
                        sequence_number += 1
                        function_call_data["arguments"] += args_str

            # Handle text content
            elif delta_content:
                # Emit output_item.added for message if not yet done
                if not output_item_added:
                    yield sse_event(
                        "response.output_item.added",
                        {
                            "type": "response.output_item.added",
                            "output_index": 0,
                            "item": {
                                "id": msg_id,
                                "status": "in_progress",
                                "type": "message",
                                "role": "assistant",
                                "content": [],
                            },
                            "sequence_number": sequence_number,
                        },
                    )
                    sequence_number += 1

                    # Emit content_part.added
                    yield sse_event(
                        "response.content_part.added",
                        {
                            "type": "response.content_part.added",
                            "item_id": msg_id,
                            "output_index": 0,
                            "content_index": 0,
                            "part": {
                                "type": "output_text",
                                "text": "",
                                "annotations": [],
                            },
                            "sequence_number": sequence_number,
                        },
                    )
                    sequence_number += 1
                    output_item_added = True

                full_text += delta_content
                # Emit response.output_text.delta
                yield sse_event(
                    "response.output_text.delta",
                    {
                        "type": "response.output_text.delta",
                        "item_id": msg_id,
                        "output_index": 0,
                        "content_index": 0,
                        "delta": delta_content,
                        "sequence_number": sequence_number,
                    },
                )
                sequence_number += 1

        # Finalize based on response type
        if is_function_call and function_call_data:
            # Emit function_call_arguments.done
            yield sse_event(
                "response.function_call_arguments.done",
                {
                    "type": "response.function_call_arguments.done",
                    "item_id": fc_id,
                    "output_index": 0,
                    "name": function_call_data["name"],
                    "arguments": function_call_data["arguments"],
                    "sequence_number": sequence_number,
                },
            )
            sequence_number += 1

            # Emit output_item.done for function_call
            yield sse_event(
                "response.output_item.done",
                {
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": {
                        "id": fc_id,
                        "type": "function_call",
                        "status": "completed",
                        "call_id": f"call_{response_id}",
                        "name": function_call_data["name"],
                        "arguments": function_call_data["arguments"],
                    },
                    "sequence_number": sequence_number,
                },
            )
            sequence_number += 1

            # Emit response.completed with function_call output
            final_output = [
                {
                    "id": fc_id,
                    "type": "function_call",
                    "status": "completed",
                    "call_id": f"call_{response_id}",
                    "name": function_call_data["name"],
                    "arguments": function_call_data["arguments"],
                }
            ]
            yield sse_event(
                "response.completed",
                {
                    "type": "response.completed",
                    "response": build_response_obj("completed", output=final_output),
                    "sequence_number": sequence_number,
                },
            )
        else:
            # Handle text response (including empty response)
            if not output_item_added:
                # No content received, emit minimal events
                yield sse_event(
                    "response.output_item.added",
                    {
                        "type": "response.output_item.added",
                        "output_index": 0,
                        "item": {
                            "id": msg_id,
                            "status": "in_progress",
                            "type": "message",
                            "role": "assistant",
                            "content": [],
                        },
                        "sequence_number": sequence_number,
                    },
                )
                sequence_number += 1

                yield sse_event(
                    "response.content_part.added",
                    {
                        "type": "response.content_part.added",
                        "item_id": msg_id,
                        "output_index": 0,
                        "content_index": 0,
                        "part": {
                            "type": "output_text",
                            "text": "",
                            "annotations": [],
                        },
                        "sequence_number": sequence_number,
                    },
                )
                sequence_number += 1

            # Emit response.output_text.done
            yield sse_event(
                "response.output_text.done",
                {
                    "type": "response.output_text.done",
                    "item_id": msg_id,
                    "output_index": 0,
                    "content_index": 0,
                    "text": full_text,
                    "sequence_number": sequence_number,
                },
            )
            sequence_number += 1

            # Emit response.content_part.done
            yield sse_event(
                "response.content_part.done",
                {
                    "type": "response.content_part.done",
                    "item_id": msg_id,
                    "output_index": 0,
                    "content_index": 0,
                    "part": {
                        "type": "output_text",
                        "text": full_text,
                        "annotations": [],
                    },
                    "sequence_number": sequence_number,
                },
            )
            sequence_number += 1

            # Emit response.output_item.done
            yield sse_event(
                "response.output_item.done",
                {
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": {
                        "id": msg_id,
                        "status": "completed",
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": full_text,
                                "annotations": [],
                            }
                        ],
                    },
                    "sequence_number": sequence_number,
                },
            )
            sequence_number += 1

            # Emit response.completed
            final_output = [
                {
                    "id": msg_id,
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": full_text,
                            "annotations": [],
                        }
                    ],
                }
            ]
            yield sse_event(
                "response.completed",
                {
                    "type": "response.completed",
                    "response": build_response_obj("completed", output=final_output),
                    "sequence_number": sequence_number,
                },
            )

    except gigachat.exceptions.GigaChatException as e:
        error_type = type(e).__name__
        error_message = str(e)
        if logger:
            logger.error(
                f"[{rquid}] GigaChat streaming error: {error_type}: {error_message}"
            )
        error_response = {
            "type": "error",
            "code": "stream_error",
            "message": error_message,
            "param": None,
            "sequence_number": sequence_number,
        }
        yield sse_event("error", error_response)

    except Exception as e:
        error_type = type(e).__name__
        error_message = str(e)
        tb = traceback.format_exc()
        if logger:
            logger.error(
                f"[{rquid}] Unexpected streaming error: {error_type}: {error_message}\n{tb}"
            )
        error_response = {
            "type": "error",
            "code": "internal_error",
            "message": f"Stream interrupted: {error_message}",
            "param": None,
            "sequence_number": sequence_number,
        }
        yield sse_event("error", error_response)


def resolve_schema_refs(schema: dict) -> dict:
    """
    Resolves $ref references and anyOf/oneOf in JSON schema.

    GigaChat doesn't support $ref/$defs and anyOf/oneOf, so we need to
    expand the schema and simplify Optional types.

    Args:
        schema: JSON schema that may contain $ref, $defs, anyOf, oneOf

    Returns:
        Resolved schema without $ref/$defs references
    """
    from typing import Any, Dict

    def resolve(obj: Any, defs: Dict[str, Any]) -> Any:
        if isinstance(obj, dict):
            # Handle $ref
            if "$ref" in obj:
                ref_path = obj["$ref"]
                # Parse reference like '#/$defs/Step'
                if ref_path.startswith("#/$defs/"):
                    ref_name = ref_path.split("/")[-1]
                    if ref_name in defs:
                        # Return resolved definition (recursively resolve)
                        resolved = defs[ref_name].copy()
                        return resolve(resolved, defs)
                return obj

            # Handle anyOf/oneOf (typically from Optional types)
            # Pydantic generates: anyOf: [{actual_type}, {type: "null"}]
            for union_key in ("anyOf", "oneOf"):
                if union_key in obj:
                    variants = obj[union_key]
                    # Find non-null variant
                    non_null_variants = [v for v in variants if v.get("type") != "null"]
                    if non_null_variants:
                        # Take the first non-null variant and merge with other props
                        result = resolve(non_null_variants[0], defs)
                        # Preserve other properties like 'default', 'title', 'description'
                        for key, value in obj.items():
                            if key not in (union_key, "$defs") and key not in result:
                                result[key] = resolve(value, defs)
                        return result
                    # If all are null, just return null type
                    return {"type": "null"}

            # Recursively process dict, skipping $defs
            return {
                key: resolve(value, defs)
                for key, value in obj.items()
                if key != "$defs"
            }

        elif isinstance(obj, list):
            return [resolve(item, defs) for item in obj]

        return obj

    defs = schema.get("$defs", {})
    return resolve(schema, defs)


def normalize_json_schema(schema: dict) -> dict:
    """
    Нормализует JSON Schema для совместимости с GigaChat.

    GigaChat требует, чтобы у каждого объекта (type: "object") были properties.
    Если properties отсутствуют, добавляем пустой объект.

    GigaChat не поддерживает anyOf/oneOf с type: null (Optional типы).
    Удаляем null варианты и упрощаем схему.

    JSON Schema также поддерживает type: ['string', 'null'] для nullable типов.
    Преобразуем в одиночный тип (первый не-null).

    Рекурсивно обрабатывает вложенные схемы.
    """

    if not isinstance(schema, dict):
        return schema

    result = dict(schema)

    # Handle array-style type field: type: ['string', 'null'] -> type: 'string'
    # This is valid JSON Schema syntax for nullable types
    if "type" in result and isinstance(result["type"], list):
        non_null_types = [t for t in result["type"] if t != "null"]
        if non_null_types:
            # Take the first non-null type
            result["type"] = non_null_types[0]
        elif result["type"]:
            # If all types are null (unlikely), keep the first one
            result["type"] = result["type"][0]

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
            if "parameters" not in function:
                # Skip tools without parameters (e.g., custom/freeform tools)
                continue
            # Resolve $ref/$defs references as GigaChat doesn't support them
            resolved_params = resolve_schema_refs(function["parameters"])
            normalized_params = normalize_json_schema(resolved_params)
            giga_function = Function(
                name=function["name"],
                description=function.get("description", ""),
                parameters=FunctionParameters(**normalized_params),
            )
        elif "parameters" in tool:
            # Resolve $ref/$defs references as GigaChat doesn't support them
            resolved_params = resolve_schema_refs(tool["parameters"])
            normalized_params = normalize_json_schema(resolved_params)
            giga_function = Function(
                name=tool["name"],
                description=tool.get("description", ""),
                parameters=FunctionParameters(**normalized_params),
            )
        else:
            # Skip tools without parameters (e.g., custom/freeform tools like apply_patch)
            continue
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
