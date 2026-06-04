import asyncio
import json
import time
import traceback
from types import SimpleNamespace
from typing import Any, AsyncGenerator, Optional

import gigachat
from aioitertools import enumerate as aio_enumerate
from gigachat import GigaChat
from gigachat.models import Chat
from starlette.requests import Request

from gpt2giga.app_state import get_gigachat_client, get_model_concurrency_limiter
from gpt2giga.common.gigachat_options import (
    GigaRequestOptions,
    gigachat_request_options,
)
from gpt2giga.common.model_concurrency import (
    ModelConcurrencyLimiter,
    ModelConcurrencyTimeoutError,
    resolve_gigachat_model,
)
from gpt2giga.common.reasoning import ReasoningContentParser
from gpt2giga.common.tools import map_tool_name_from_gigachat
from gpt2giga.logger import rquid_context
from gpt2giga.protocol.response import (
    adapt_v2_chunk_to_v1_shape,
    hydrate_v2_image_files,
)
from gpt2giga.protocol.response.processor import ResponseProcessor


async def stream_chat_completion_generator(
    request: Request,
    model: str,
    chat_messages: Chat,
    response_id: str,
    giga_client: Optional[GigaChat] = None,
    request_options: Optional[GigaRequestOptions] = None,
    *,
    model_limiter: Optional[ModelConcurrencyLimiter] = None,
    effective_model: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    logger = None
    rquid = rquid_context.get()

    try:
        if giga_client is None:
            giga_client = get_gigachat_client(request)
        if model_limiter is None:
            model_limiter = get_model_concurrency_limiter(request)
        if effective_model is None:
            effective_model = resolve_gigachat_model(
                chat_messages, getattr(request.app.state, "config", None)
            )
        logger = getattr(request.app.state, "logger", None)

        async with model_limiter.limit(effective_model, provider="openai"):
            async with gigachat_request_options(giga_client, request_options):
                async for chunk in giga_client.astream(chat_messages):
                    if await request.is_disconnected():
                        if logger:
                            logger.info(
                                f"[{rquid}] Client disconnected during streaming"
                            )
                        break
                    processed = (
                        request.app.state.response_processor.process_stream_chunk(
                            chunk, model, response_id
                        )
                    )
                    yield f"data: {json.dumps(processed)}\n\n"

            response_processor = request.app.state.response_processor
            flush_stream_reasoning = getattr(
                response_processor, "flush_stream_reasoning", None
            )
            if flush_stream_reasoning:
                flushed_reasoning = flush_stream_reasoning(response_id, family="chat")
                if flushed_reasoning.content or flushed_reasoning.reasoning_content:
                    delta = {"content": flushed_reasoning.content}
                    if flushed_reasoning.reasoning_content:
                        delta["reasoning_content"] = flushed_reasoning.reasoning_content
                    processed = {
                        "id": f"chatcmpl-{response_id}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": delta,
                                "finish_reason": None,
                                "logprobs": None,
                            }
                        ],
                        "usage": None,
                        "system_fingerprint": f"fp_{response_id}",
                    }
                    yield f"data: {json.dumps(processed)}\n\n"

            yield "data: [DONE]\n\n"

    except ModelConcurrencyTimeoutError as e:
        error_response = {
            "error": {
                "message": str(e),
                "type": "rate_limit_error",
                "param": "model",
                "code": "model_concurrency_limit",
            }
        }
        yield f"data: {json.dumps(error_response)}\n\n"
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

    except asyncio.CancelledError:
        # Preserve cooperative cancellation for graceful server shutdown.
        raise

    except Exception as e:
        error_type = type(e).__name__
        tb = traceback.format_exc()
        if logger:
            logger.error(
                f"[{rquid}] Unexpected streaming error: {error_type}: {e}\n{tb}"
            )
        error_response = {
            "error": {
                "message": "Stream interrupted",
                "type": error_type,
                "code": "internal_error",
            }
        }
        yield f"data: {json.dumps(error_response)}\n\n"
        yield "data: [DONE]\n\n"


async def stream_chat_completion_v2_generator(
    request: Request,
    model: str,
    chat_request: Any,
    response_id: str,
    giga_client: Optional[GigaChat] = None,
    request_options: Optional[GigaRequestOptions] = None,
    *,
    model_limiter: Optional[ModelConcurrencyLimiter] = None,
    effective_model: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    logger = None
    rquid = rquid_context.get()

    try:
        if giga_client is None:
            giga_client = get_gigachat_client(request)
        if model_limiter is None:
            model_limiter = get_model_concurrency_limiter(request)
        if effective_model is None:
            effective_model = resolve_gigachat_model(
                chat_request, getattr(request.app.state, "config", None)
            )
        logger = getattr(request.app.state, "logger", None)

        async with model_limiter.limit(effective_model, provider="openai"):
            async with gigachat_request_options(giga_client, request_options):
                async for chunk in giga_client.achat.stream(chat_request):
                    if await request.is_disconnected():
                        if logger:
                            logger.info(
                                f"[{rquid}] Client disconnected during streaming"
                            )
                        break
                    adapted = adapt_v2_chunk_to_v1_shape(chunk, default_model=model)
                    processed = (
                        request.app.state.response_processor.process_stream_chunk(
                            SimpleNamespace(model_dump=lambda: adapted),
                            model,
                            response_id,
                        )
                    )
                    yield f"data: {json.dumps(processed)}\n\n"

            response_processor = request.app.state.response_processor
            flush_stream_reasoning = getattr(
                response_processor, "flush_stream_reasoning", None
            )
            if flush_stream_reasoning:
                flushed_reasoning = flush_stream_reasoning(response_id, family="chat")
                if flushed_reasoning.content or flushed_reasoning.reasoning_content:
                    delta = {"content": flushed_reasoning.content}
                    if flushed_reasoning.reasoning_content:
                        delta["reasoning_content"] = flushed_reasoning.reasoning_content
                    processed = {
                        "id": f"chatcmpl-{response_id}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": delta,
                                "finish_reason": None,
                                "logprobs": None,
                            }
                        ],
                        "usage": None,
                        "system_fingerprint": f"fp_{response_id}",
                    }
                    yield f"data: {json.dumps(processed)}\n\n"

            yield "data: [DONE]\n\n"

    except ModelConcurrencyTimeoutError as e:
        error_response = {
            "error": {
                "message": str(e),
                "type": "rate_limit_error",
                "param": "model",
                "code": "model_concurrency_limit",
            }
        }
        yield f"data: {json.dumps(error_response)}\n\n"
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

    except asyncio.CancelledError:
        raise

    except Exception as e:
        error_type = type(e).__name__
        tb = traceback.format_exc()
        if logger:
            logger.error(
                f"[{rquid}] Unexpected streaming error: {error_type}: {e}\n{tb}"
            )
        error_response = {
            "error": {
                "message": "Stream interrupted",
                "type": error_type,
                "code": "internal_error",
            }
        }
        yield f"data: {json.dumps(error_response)}\n\n"
        yield "data: [DONE]\n\n"


class _V2ResponsesStreamClient:
    def __init__(
        self,
        giga_client: GigaChat,
        model: str,
        request_options: Optional[GigaRequestOptions],
    ):
        self._giga_client = giga_client
        self._model = model
        self._request_options = request_options

    def astream(self, chat_request: Any):
        async def gen():
            async with gigachat_request_options(
                self._giga_client, self._request_options
            ):
                async for chunk in self._giga_client.achat.stream(chat_request):
                    adapted = adapt_v2_chunk_to_v1_shape(
                        chunk,
                        default_model=self._model,
                    )
                    await hydrate_v2_image_files(adapted, self._giga_client)
                    yield SimpleNamespace(model_dump=lambda adapted=adapted: adapted)

        return gen()

    async def aget_image(self, file_id: str):
        async with gigachat_request_options(self._giga_client, self._request_options):
            return await self._giga_client.aget_image(file_id)


async def stream_responses_v2_generator(
    request: Request,
    chat_request: Any,
    response_id: str,
    giga_client: Optional[GigaChat] = None,
    request_data: Optional[dict] = None,
    request_options: Optional[GigaRequestOptions] = None,
    *,
    model_limiter: Optional[ModelConcurrencyLimiter] = None,
    effective_model: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    if giga_client is None:
        giga_client = get_gigachat_client(request)
    model = request_data.get("model", "unknown") if request_data else "unknown"
    adapter_client = _V2ResponsesStreamClient(giga_client, model, request_options)

    async for event in stream_responses_generator(
        request,
        chat_request,
        response_id,
        giga_client=adapter_client,
        request_data=request_data,
        request_options=None,
        model_limiter=model_limiter,
        effective_model=effective_model,
    ):
        yield event


def _accumulate_builtin_metadata(target: dict[str, Any], delta: dict[str, Any]) -> None:
    tool_executions = delta.get("tool_executions")
    if isinstance(tool_executions, list):
        target["tool_executions"].extend(
            item for item in tool_executions if isinstance(item, dict)
        )

    files = delta.get("files")
    if isinstance(files, list):
        target["files"].extend(item for item in files if isinstance(item, dict))

    inline_data = delta.get("inline_data")
    if isinstance(inline_data, dict):
        _merge_inline_data(target["inline_data"], inline_data)


def _merge_inline_data(target: dict[str, Any], inline_data: dict[str, Any]) -> None:
    for key, value in inline_data.items():
        if key == "sources" and isinstance(value, dict):
            sources = target.setdefault("sources", {})
            if isinstance(sources, dict):
                sources.update(value)
            else:
                target["sources"] = value
        elif isinstance(value, list):
            items = target.setdefault(key, [])
            if isinstance(items, list):
                items.extend(value)
            else:
                target[key] = value
        elif value is not None:
            target[key] = value


async def stream_responses_generator(
    request: Request,
    chat_messages: Chat,
    response_id: str,
    giga_client: Optional[GigaChat] = None,
    request_data: Optional[dict] = None,
    request_options: Optional[GigaRequestOptions] = None,
    *,
    model_limiter: Optional[ModelConcurrencyLimiter] = None,
    effective_model: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    import time

    logger = None
    rquid = rquid_context.get()
    created_at = int(time.time())
    model = request_data.get("model", "unknown") if request_data else "unknown"
    msg_id = f"msg_{response_id}"
    fc_id = f"fc_{response_id}"  # ID for function call item

    def build_reasoning_config() -> dict:
        reasoning_data = request_data.get("reasoning") if request_data else None
        if isinstance(reasoning_data, dict):
            return {
                "effort": reasoning_data.get("effort"),
                "summary": reasoning_data.get("summary"),
            }
        effort = request_data.get("reasoning_effort") if request_data else None
        return {"effort": effort, "summary": None}

    def sse_event(event_type: str, data: dict) -> str:
        return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

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
            "reasoning": build_reasoning_config(),
            "store": request_data.get("store", True) if request_data else True,
            "temperature": request_data.get("temperature", 1) if request_data else 1,
            "text": {"format": {"type": "text"}},
            "tool_choice": request_data.get("tool_choice", "auto")
            if request_data
            else "auto",
            "tools": request_data.get("tools", []) if request_data else [],
            "top_p": request_data.get("top_p", 1) if request_data else 1,
            "truncation": "disabled",
            "usage": usage,
            "user": None,
            "metadata": {},
        }

    sequence_number = 0

    try:
        if giga_client is None:
            giga_client = get_gigachat_client(request)
        if model_limiter is None:
            model_limiter = get_model_concurrency_limiter(request)
        if effective_model is None:
            effective_model = resolve_gigachat_model(
                chat_messages, getattr(request.app.state, "config", None)
            )
        logger = getattr(request.app.state, "logger", None)

        yield sse_event(
            "response.created",
            {
                "type": "response.created",
                "response": build_response_obj("in_progress"),
                "sequence_number": sequence_number,
            },
        )
        sequence_number += 1

        yield sse_event(
            "response.in_progress",
            {
                "type": "response.in_progress",
                "response": build_response_obj("in_progress"),
                "sequence_number": sequence_number,
            },
        )
        sequence_number += 1

        full_text = ""
        reasoning_text = ""
        reasoning_parser = ReasoningContentParser()
        function_call_data = None  # {"name": ..., "arguments": ...}
        functions_state_id = None
        output_item_added = False
        is_function_call = False
        final_usage = None
        builtin_message_metadata = {
            "tool_executions": [],
            "files": [],
            "inline_data": {},
        }

        async with model_limiter.limit(effective_model, provider="openai"):
            async with gigachat_request_options(giga_client, request_options):
                async for _i, chunk in aio_enumerate(
                    giga_client.astream(chat_messages)
                ):
                    if await request.is_disconnected():
                        if logger:
                            logger.info(
                                f"[{rquid}] Client disconnected during streaming"
                            )
                        break

                    giga_dict = chunk.model_dump()
                    if giga_dict.get("usage"):
                        usage_builder = getattr(
                            request.app.state.response_processor,
                            "_build_response_usage",
                            None,
                        )
                        final_usage = (
                            usage_builder(giga_dict["usage"])
                            if callable(usage_builder)
                            else None
                        )
                    choice = giga_dict["choices"][0]
                    delta = choice.get("delta", {})
                    delta_content = delta.get("content", "")
                    delta_function_call = delta.get("function_call")
                    delta_reasoning = delta.get("reasoning_content", "")
                    parsed_content = reasoning_parser.feed(delta_content)
                    delta_content = parsed_content.content
                    if parsed_content.reasoning_content:
                        reasoning_text += parsed_content.reasoning_content
                    if delta_reasoning:
                        reasoning_text += delta_reasoning
                    _accumulate_builtin_metadata(builtin_message_metadata, delta)

                    if delta_function_call:
                        is_function_call = True
                        if functions_state_id is None:
                            functions_state_id = delta.get("functions_state_id")

                        if function_call_data is None:
                            tool_name = map_tool_name_from_gigachat(
                                delta_function_call.get("name", "")
                            )
                            function_call_data = {
                                "name": tool_name,
                                "arguments": "",
                            }
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

                        if delta_function_call.get("name"):
                            function_call_data["name"] = map_tool_name_from_gigachat(
                                delta_function_call["name"]
                            )

                        args = delta_function_call.get("arguments")
                        if args is not None:
                            if isinstance(args, dict):
                                args_str = json.dumps(args, ensure_ascii=False)
                            else:
                                args_str = str(args)

                            if args_str:
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

                    elif delta_content:
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

        flushed_reasoning = reasoning_parser.flush()
        if flushed_reasoning.content:
            full_text += flushed_reasoning.content
        if flushed_reasoning.reasoning_content:
            reasoning_text += flushed_reasoning.reasoning_content

        if is_function_call and function_call_data:
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
                    "response": build_response_obj(
                        "completed", output=final_output, usage=final_usage
                    ),
                    "sequence_number": sequence_number,
                },
            )
        else:
            metadata_message = {
                "content": full_text,
                "tool_executions": builtin_message_metadata["tool_executions"],
                "files": builtin_message_metadata["files"],
                "inline_data": builtin_message_metadata["inline_data"],
            }
            builtin_items = ResponseProcessor._create_builtin_tool_items(
                metadata_message,
                response_id,
                request_data=request_data,
            )
            annotations = ResponseProcessor._create_url_annotations(
                full_text,
                builtin_message_metadata["inline_data"],
            )
            output_text_part = {
                "type": "output_text",
                "text": full_text,
                "annotations": annotations,
            }
            if builtin_message_metadata["inline_data"]:
                output_text_part["inline_data"] = builtin_message_metadata[
                    "inline_data"
                ]
            message_needed = bool(full_text or not builtin_items)

            if message_needed:
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

                yield sse_event(
                    "response.content_part.done",
                    {
                        "type": "response.content_part.done",
                        "item_id": msg_id,
                        "output_index": 0,
                        "content_index": 0,
                        "part": output_text_part,
                        "sequence_number": sequence_number,
                    },
                )
                sequence_number += 1

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
                            "content": [output_text_part],
                        },
                        "sequence_number": sequence_number,
                    },
                )
                sequence_number += 1

            final_output = []
            if reasoning_text:
                final_output.append(
                    {
                        "id": f"rs_{response_id}",
                        "type": "reasoning",
                        "summary": [
                            {
                                "type": "summary_text",
                                "text": reasoning_text,
                            }
                        ],
                    }
                )
            final_output.extend(builtin_items)
            if message_needed:
                final_output.append(
                    {
                        "id": msg_id,
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [output_text_part],
                    }
                )
            yield sse_event(
                "response.completed",
                {
                    "type": "response.completed",
                    "response": build_response_obj(
                        "completed", output=final_output, usage=final_usage
                    ),
                    "sequence_number": sequence_number,
                },
            )

    except ModelConcurrencyTimeoutError as e:
        error_response = {
            "type": "error",
            "code": "model_concurrency_limit",
            "message": str(e),
            "param": "model",
            "sequence_number": sequence_number,
        }
        yield sse_event("error", error_response)

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

    except asyncio.CancelledError:
        raise

    except Exception as e:
        error_type = type(e).__name__
        tb = traceback.format_exc()
        if logger:
            logger.error(
                f"[{rquid}] Unexpected streaming error: {error_type}: {e}\n{tb}"
            )
        error_response = {
            "type": "error",
            "code": "internal_error",
            "message": "Stream interrupted",
            "param": None,
            "sequence_number": sequence_number,
        }
        yield sse_event("error", error_response)
