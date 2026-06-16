import asyncio
import json
import time
from types import SimpleNamespace
from typing import Any, AsyncGenerator, Optional

import gigachat
from aioitertools import enumerate as aio_enumerate
from gigachat import GigaChat
from gigachat.models import Chat
from starlette.requests import Request

from gpt2giga.app_state import get_gigachat_client, get_model_concurrency_limiter
from gpt2giga.common.client_params import (
    extract_gigachat_response_metadata,
    merge_openai_response_metadata,
)
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
from gpt2giga.common.sources import (
    SourceMarkerStreamRenderer,
    extract_sources,
    has_source_marker_start,
    merge_inline_data,
)
from gpt2giga.common.tools import split_gigachat_tool_name
from gpt2giga.logger import rquid_context
from gpt2giga.protocol.response import (
    GIGACHAT_PROVIDER_METADATA_KEY,
    adapt_chat_completion_chunk_to_chat_chunk_shape,
    hydrate_chat_completion_image_files,
)
from gpt2giga.protocol.response.processor import ResponseProcessor


async def stream_chat_generator(
    request: Request,
    model: str,
    chat_messages: Chat,
    response_id: str,
    giga_client: Optional[GigaChat] = None,
    request_options: Optional[GigaRequestOptions] = None,
    *,
    request_data: Optional[dict[str, Any]] = None,
    model_limiter: Optional[ModelConcurrencyLimiter] = None,
    effective_model: Optional[str] = None,
    acquired_model_limit: Optional[Any] = None,
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

        async def emit_stream() -> AsyncGenerator[str, None]:
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
                            chunk,
                            model,
                            response_id,
                            request_data=request_data,
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
            flush_stream_sources = getattr(
                response_processor, "flush_stream_sources", None
            )
            if flush_stream_sources:
                source_text = flush_stream_sources(response_id, family="chat")
                if source_text:
                    processed = {
                        "id": f"chatcmpl-{response_id}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": source_text},
                                "finish_reason": None,
                                "logprobs": None,
                            }
                        ],
                        "usage": None,
                        "system_fingerprint": f"fp_{response_id}",
                    }
                    yield f"data: {json.dumps(processed)}\n\n"

            yield "data: [DONE]\n\n"

        if acquired_model_limit is not None:
            try:
                async for event in emit_stream():
                    yield event
            finally:
                await acquired_model_limit.__aexit__(None, None, None)
        else:
            async with model_limiter.limit(effective_model, provider="openai"):
                async for event in emit_stream():
                    yield event

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
        if logger:
            logger.error(f"[{rquid}] Unexpected streaming error: {error_type}: {e}")
        error_response = {
            "error": {
                "message": "Stream interrupted",
                "type": error_type,
                "code": "internal_error",
            }
        }
        yield f"data: {json.dumps(error_response)}\n\n"
        yield "data: [DONE]\n\n"


async def stream_chat_completion_generator(
    request: Request,
    model: str,
    chat_request: Any,
    response_id: str,
    giga_client: Optional[GigaChat] = None,
    request_options: Optional[GigaRequestOptions] = None,
    *,
    request_data: Optional[dict[str, Any]] = None,
    model_limiter: Optional[ModelConcurrencyLimiter] = None,
    effective_model: Optional[str] = None,
    acquired_model_limit: Optional[Any] = None,
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

        async def emit_stream() -> AsyncGenerator[str, None]:
            async with gigachat_request_options(giga_client, request_options):
                async for chunk in giga_client.achat.stream(chat_request):
                    if await request.is_disconnected():
                        if logger:
                            logger.info(
                                f"[{rquid}] Client disconnected during streaming"
                            )
                        break
                    adapted = adapt_chat_completion_chunk_to_chat_chunk_shape(
                        chunk,
                        default_model=model,
                    )
                    processed = (
                        request.app.state.response_processor.process_stream_chunk(
                            SimpleNamespace(model_dump=lambda: adapted),
                            model,
                            response_id,
                            request_data=request_data,
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
            flush_stream_sources = getattr(
                response_processor, "flush_stream_sources", None
            )
            if flush_stream_sources:
                source_text = flush_stream_sources(response_id, family="chat")
                if source_text:
                    processed = {
                        "id": f"chatcmpl-{response_id}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": source_text},
                                "finish_reason": None,
                                "logprobs": None,
                            }
                        ],
                        "usage": None,
                        "system_fingerprint": f"fp_{response_id}",
                    }
                    yield f"data: {json.dumps(processed)}\n\n"

            yield "data: [DONE]\n\n"

        if acquired_model_limit is not None:
            try:
                async for event in emit_stream():
                    yield event
            finally:
                await acquired_model_limit.__aexit__(None, None, None)
        else:
            async with model_limiter.limit(effective_model, provider="openai"):
                async for event in emit_stream():
                    yield event

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
        if logger:
            logger.error(f"[{rquid}] Unexpected streaming error: {error_type}: {e}")
        error_response = {
            "error": {
                "message": "Stream interrupted",
                "type": error_type,
                "code": "internal_error",
            }
        }
        yield f"data: {json.dumps(error_response)}\n\n"
        yield "data: [DONE]\n\n"


class _ChatCompletionResponsesStreamClient:
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
                    adapted = adapt_chat_completion_chunk_to_chat_chunk_shape(
                        chunk,
                        default_model=self._model,
                    )
                    await hydrate_chat_completion_image_files(
                        adapted,
                        self._giga_client,
                    )
                    yield SimpleNamespace(model_dump=lambda adapted=adapted: adapted)

        return gen()

    async def aget_image(self, file_id: str):
        async with gigachat_request_options(self._giga_client, self._request_options):
            return await self._giga_client.aget_image(file_id)


async def stream_responses_chat_completion_generator(
    request: Request,
    chat_request: Any,
    response_id: str,
    giga_client: Optional[GigaChat] = None,
    request_data: Optional[dict] = None,
    request_options: Optional[GigaRequestOptions] = None,
    *,
    model_limiter: Optional[ModelConcurrencyLimiter] = None,
    effective_model: Optional[str] = None,
    acquired_model_limit: Optional[Any] = None,
) -> AsyncGenerator[str, None]:
    if giga_client is None:
        giga_client = get_gigachat_client(request)
    model = request_data.get("model", "unknown") if request_data else "unknown"
    adapter_client = _ChatCompletionResponsesStreamClient(
        giga_client,
        model,
        request_options,
    )

    async for event in stream_responses_generator(
        request,
        chat_request,
        response_id,
        giga_client=adapter_client,
        request_data=request_data,
        request_options=None,
        model_limiter=model_limiter,
        effective_model=effective_model,
        acquired_model_limit=acquired_model_limit,
        response_id_from_stream_metadata=True,
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
    merge_inline_data(target, inline_data)


def _builtin_tool_stream_name(name: Any) -> str:
    tool_name = ResponseProcessor._normalize_builtin_tool_name(name)
    if tool_name in {"image_generate", "web_search"}:
        return tool_name
    return ""


def _builtin_tool_stream_status(tool_name: str, status: Any) -> str:
    if status in {"success", "completed"}:
        return "completed"
    if status == "failed":
        return "failed"
    if tool_name == "image_generate" and status == "generating":
        return "generating"
    if tool_name == "web_search" and status == "searching":
        return "searching"
    return "in_progress"


def _builtin_tool_stream_event_type(tool_name: str, status: str) -> str:
    if tool_name == "image_generate":
        if status == "completed":
            return "response.image_generation_call.completed"
        if status == "generating":
            return "response.image_generation_call.generating"
        return "response.image_generation_call.in_progress"

    if status == "completed":
        return "response.web_search_call.completed"
    if status == "searching":
        return "response.web_search_call.searching"
    return "response.web_search_call.in_progress"


def _builtin_tool_stream_item_id(tool_name: str, response_id: str) -> str:
    if tool_name == "image_generate":
        return f"ig_{response_id}_0"
    return f"ws_{response_id}"


def _image_generation_stream_item(
    response_id: str,
    status: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    image_files = [
        file_data
        for file_data in ResponseProcessor._extract_files(metadata)
        if ResponseProcessor._is_image_file(file_data)
    ]
    file_data = image_files[0] if image_files else {}
    item = {
        "id": _builtin_tool_stream_item_id("image_generate", response_id),
        "type": "image_generation_call",
        "status": status,
        "result": file_data.get("content"),
    }
    if file_data:
        ResponseProcessor._copy_file_metadata(item, file_data)
    return item


def _web_search_stream_item(
    response_id: str,
    status: str,
    request_data: Optional[dict],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    inline_data = ResponseProcessor._normalize_inline_data(metadata.get("inline_data"))
    sources = ResponseProcessor._extract_sources(inline_data)
    return {
        "id": _builtin_tool_stream_item_id("web_search", response_id),
        "type": "web_search_call",
        "status": status,
        "action": {
            "type": "search",
            "query": ResponseProcessor._request_input_text(request_data),
            "sources": [
                {"type": "url", "url": source["url"]}
                for source in sources.values()
                if source.get("url")
            ],
        },
    }


def _builtin_tool_stream_item(
    tool_name: str,
    response_id: str,
    status: str,
    request_data: Optional[dict],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    if tool_name == "image_generate":
        return _image_generation_stream_item(response_id, status, metadata)
    return _web_search_stream_item(response_id, status, request_data, metadata)


def _builtin_tool_has_stream_result(
    tool_name: str,
    metadata: dict[str, Any],
) -> bool:
    if tool_name == "image_generate":
        return any(
            ResponseProcessor._is_image_file(file_data)
            for file_data in ResponseProcessor._extract_files(metadata)
        )

    inline_data = ResponseProcessor._normalize_inline_data(metadata.get("inline_data"))
    return bool(ResponseProcessor._extract_sources(inline_data))


def _annotation_key(annotation: dict[str, Any]) -> str:
    return json.dumps(annotation, ensure_ascii=False, sort_keys=True, default=str)


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
    acquired_model_limit: Optional[Any] = None,
    response_id_from_stream_metadata: bool = False,
) -> AsyncGenerator[str, None]:
    import time

    logger = None
    rquid = rquid_context.get()
    created_at = int(time.time())
    model = request_data.get("model", "unknown") if request_data else "unknown"
    msg_id = f"msg_{response_id}"
    fc_id = f"fc_{response_id}"  # ID for function call item
    response_metadata: dict[str, str] = {}

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

    def update_response_identity() -> None:
        nonlocal fc_id, msg_id, response_id
        if not response_id_from_stream_metadata:
            return
        thread_id = response_metadata.get("gigachat_thread_id")
        if not thread_id or thread_id == response_id:
            return
        response_id = thread_id
        msg_id = f"msg_{response_id}"
        fc_id = f"fc_{response_id}"

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
            "previous_response_id": (
                request_data.get("previous_response_id") if request_data else None
            ),
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
            "metadata": merge_openai_response_metadata(
                request_data.get("metadata", {}) if request_data else {},
                response_metadata,
            ),
        }

    def response_start_events() -> list[str]:
        nonlocal sequence_number
        events = [
            sse_event(
                "response.created",
                {
                    "type": "response.created",
                    "response": build_response_obj("in_progress"),
                    "sequence_number": sequence_number,
                },
            )
        ]
        sequence_number += 1
        events.append(
            sse_event(
                "response.in_progress",
                {
                    "type": "response.in_progress",
                    "response": build_response_obj("in_progress"),
                    "sequence_number": sequence_number,
                },
            )
        )
        sequence_number += 1
        return events

    sequence_number = 0
    release_acquired_model_limit = acquired_model_limit is not None

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

        full_text = ""
        raw_full_text = ""
        reasoning_text = ""
        reasoning_parser = ReasoningContentParser()
        source_renderer = SourceMarkerStreamRenderer()
        source_rendering_enabled = False
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
        builtin_tool_streams: dict[str, dict[str, Any]] = {}
        builtin_tool_stream_order: list[str] = []
        emitted_annotation_keys: set[str] = set()
        emitted_annotation_count = 0
        text_output_index = 0

        def emit_sequenced_event(event_type: str, data: dict[str, Any]) -> str:
            nonlocal sequence_number
            data["type"] = event_type
            data["sequence_number"] = sequence_number
            sequence_number += 1
            return sse_event(event_type, data)

        def ensure_builtin_tool_stream(tool_name: str) -> list[str]:
            if tool_name in builtin_tool_streams:
                return []

            output_index = len(builtin_tool_stream_order)
            builtin_tool_stream_order.append(tool_name)
            item = _builtin_tool_stream_item(
                tool_name,
                response_id,
                "in_progress",
                request_data,
                builtin_message_metadata,
            )
            builtin_tool_streams[tool_name] = {
                "item_id": item["id"],
                "output_index": output_index,
                "last_status": "in_progress",
                "completed_event_emitted": False,
                "item_done": False,
            }
            return [
                emit_sequenced_event(
                    "response.output_item.added",
                    {
                        "output_index": output_index,
                        "item": item,
                    },
                )
            ]

        def emit_builtin_tool_execution_events(
            executions: Any,
        ) -> list[str]:
            if not isinstance(executions, list):
                return []

            events = []
            for execution in executions:
                if not isinstance(execution, dict):
                    continue
                tool_name = _builtin_tool_stream_name(execution.get("name"))
                if not tool_name:
                    continue

                events.extend(ensure_builtin_tool_stream(tool_name))
                state = builtin_tool_streams[tool_name]
                status = _builtin_tool_stream_status(
                    tool_name,
                    execution.get("status"),
                )
                state["last_status"] = status

                if status == "failed":
                    continue
                if status == "completed" and state["completed_event_emitted"]:
                    continue

                event_data = {
                    "item_id": state["item_id"],
                    "output_index": state["output_index"],
                    "tool_execution": execution,
                }
                if "seconds_left" in execution:
                    event_data["seconds_left"] = execution["seconds_left"]
                events.append(
                    emit_sequenced_event(
                        _builtin_tool_stream_event_type(tool_name, status),
                        event_data,
                    )
                )
                if status == "completed":
                    state["completed_event_emitted"] = True
            return events

        def emit_builtin_tool_result_events() -> list[str]:
            events = []
            for tool_name in builtin_tool_stream_order:
                state = builtin_tool_streams[tool_name]
                if state["item_done"] or not _builtin_tool_has_stream_result(
                    tool_name,
                    builtin_message_metadata,
                ):
                    continue

                if not state["completed_event_emitted"]:
                    events.append(
                        emit_sequenced_event(
                            _builtin_tool_stream_event_type(
                                tool_name,
                                "completed",
                            ),
                            {
                                "item_id": state["item_id"],
                                "output_index": state["output_index"],
                            },
                        )
                    )
                    state["completed_event_emitted"] = True

                item = _builtin_tool_stream_item(
                    tool_name,
                    response_id,
                    "completed",
                    request_data,
                    builtin_message_metadata,
                )
                events.append(
                    emit_sequenced_event(
                        "response.output_item.done",
                        {
                            "output_index": state["output_index"],
                            "item": item,
                        },
                    )
                )
                state["item_done"] = True
            return events

        def emit_pending_builtin_tool_done_events(
            final_items: list[dict[str, Any]],
        ) -> list[str]:
            events = []
            final_items_by_tool = {
                "image_generate": next(
                    (
                        item
                        for item in final_items
                        if item.get("type") == "image_generation_call"
                    ),
                    None,
                ),
                "web_search": next(
                    (
                        item
                        for item in final_items
                        if item.get("type") == "web_search_call"
                    ),
                    None,
                ),
            }
            for tool_name in builtin_tool_stream_order:
                state = builtin_tool_streams[tool_name]
                if state["item_done"]:
                    continue
                final_item = final_items_by_tool[tool_name]
                if final_item:
                    item = dict(final_item)
                    item["id"] = state["item_id"]
                    status = item.get("status", state["last_status"])
                else:
                    status = state["last_status"]
                    item = _builtin_tool_stream_item(
                        tool_name,
                        response_id,
                        status,
                        request_data,
                        builtin_message_metadata,
                    )

                if status == "completed" and not state["completed_event_emitted"]:
                    events.append(
                        emit_sequenced_event(
                            _builtin_tool_stream_event_type(
                                tool_name,
                                "completed",
                            ),
                            {
                                "item_id": state["item_id"],
                                "output_index": state["output_index"],
                            },
                        )
                    )
                    state["completed_event_emitted"] = True

                events.append(
                    emit_sequenced_event(
                        "response.output_item.done",
                        {
                            "output_index": state["output_index"],
                            "item": item,
                        },
                    )
                )
                state["item_done"] = True
            return events

        def emit_url_annotation_events(
            *,
            include_unreferenced: bool,
        ) -> list[str]:
            nonlocal emitted_annotation_count
            if not output_item_added or not raw_full_text:
                return []

            annotations = ResponseProcessor._create_url_annotations(
                raw_full_text,
                builtin_message_metadata["inline_data"],
                include_unreferenced=include_unreferenced,
            )
            events = []
            for annotation in annotations:
                annotation_key = _annotation_key(annotation)
                if annotation_key in emitted_annotation_keys:
                    continue
                emitted_annotation_keys.add(annotation_key)
                events.append(
                    emit_sequenced_event(
                        "response.output_text.annotation.added",
                        {
                            "item_id": msg_id,
                            "output_index": text_output_index,
                            "content_index": 0,
                            "annotation_index": emitted_annotation_count,
                            "annotation": annotation,
                        },
                    )
                )
                emitted_annotation_count += 1
            return events

        def emit_text_output_start_events() -> list[str]:
            nonlocal output_item_added, sequence_number, text_output_index
            if output_item_added:
                return []

            text_output_index = len(builtin_tool_stream_order)
            events = [
                sse_event(
                    "response.output_item.added",
                    {
                        "type": "response.output_item.added",
                        "output_index": text_output_index,
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
            ]
            sequence_number += 1
            events.append(
                sse_event(
                    "response.content_part.added",
                    {
                        "type": "response.content_part.added",
                        "item_id": msg_id,
                        "output_index": text_output_index,
                        "content_index": 0,
                        "part": {
                            "type": "output_text",
                            "text": "",
                            "annotations": [],
                        },
                        "sequence_number": sequence_number,
                    },
                )
            )
            sequence_number += 1
            output_item_added = True
            return events

        async def iterate_chunks_with_optional_prefetch():
            stream = aio_enumerate(giga_client.astream(chat_messages))
            if not response_id_from_stream_metadata:
                for event in response_start_events():
                    yield event, None
                async for item in stream:
                    yield None, item
                return

            first_item = None
            try:
                first_item = await anext(stream)
            except StopAsyncIteration:
                # Empty upstream streams still need response start events below.
                pass
            except Exception:
                for event in response_start_events():
                    yield event, None
                raise
            if first_item is not None:
                first_giga_dict = first_item[1].model_dump()
                response_metadata.update(
                    extract_gigachat_response_metadata(first_giga_dict.get("x_headers"))
                )
                response_metadata.update(
                    _extract_provider_response_metadata(first_giga_dict)
                )
                update_response_identity()
            for event in response_start_events():
                yield event, None
            if first_item is not None:
                yield None, first_item
            async for item in stream:
                yield None, item

        async def emit_upstream_events() -> AsyncGenerator[str, None]:
            nonlocal final_usage, full_text, function_call_data, functions_state_id
            nonlocal is_function_call, output_item_added, raw_full_text, reasoning_text
            nonlocal sequence_number, source_rendering_enabled, text_output_index
            async with gigachat_request_options(giga_client, request_options):
                async for (
                    prebuilt_event,
                    chunk_item,
                ) in iterate_chunks_with_optional_prefetch():
                    if prebuilt_event is not None:
                        yield prebuilt_event
                        continue
                    _i, chunk = chunk_item
                    if await request.is_disconnected():
                        if logger:
                            logger.info(
                                f"[{rquid}] Client disconnected during streaming"
                            )
                        break

                    giga_dict = chunk.model_dump()
                    response_metadata.update(
                        extract_gigachat_response_metadata(giga_dict.get("x_headers"))
                    )
                    response_metadata.update(
                        _extract_provider_response_metadata(giga_dict)
                    )
                    update_response_identity()
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
                    raw_delta_content = parsed_content.content
                    inline_data = delta.get("inline_data")
                    had_source_rendering = source_rendering_enabled
                    source_rendering_enabled = (
                        source_rendering_enabled
                        or bool(extract_sources(inline_data or {}))
                        or has_source_marker_start(raw_delta_content)
                    )
                    if (
                        source_rendering_enabled
                        and not had_source_rendering
                        and full_text
                    ):
                        source_renderer.mark_emitted_text()
                    delta_content = (
                        source_renderer.feed(raw_delta_content)
                        if source_rendering_enabled
                        else raw_delta_content
                    )
                    if source_rendering_enabled:
                        source_renderer.merge_inline_data(inline_data)
                    if raw_delta_content:
                        raw_full_text += raw_delta_content
                    if parsed_content.reasoning_content:
                        reasoning_text += parsed_content.reasoning_content
                    if delta_reasoning:
                        reasoning_text += delta_reasoning
                    _accumulate_builtin_metadata(builtin_message_metadata, delta)
                    for event in emit_builtin_tool_execution_events(
                        delta.get("tool_executions")
                    ):
                        yield event
                    for event in emit_builtin_tool_result_events():
                        yield event
                    for event in emit_url_annotation_events(include_unreferenced=False):
                        yield event

                    if delta_function_call:
                        is_function_call = True
                        if functions_state_id is None:
                            functions_state_id = delta.get("functions_state_id")

                        if function_call_data is None:
                            tool_name, namespace = split_gigachat_tool_name(
                                delta_function_call.get("name", ""),
                                request_tools=(
                                    request_data.get("tools") if request_data else None
                                ),
                            )
                            function_call_data = {
                                "name": tool_name,
                                "arguments": "",
                            }
                            if namespace:
                                function_call_data["namespace"] = namespace
                            item = {
                                "id": fc_id,
                                "type": "function_call",
                                "status": "in_progress",
                                "call_id": f"call_{response_id}",
                                "name": function_call_data["name"],
                                "arguments": "",
                            }
                            if namespace:
                                item["namespace"] = namespace
                            yield sse_event(
                                "response.output_item.added",
                                {
                                    "type": "response.output_item.added",
                                    "output_index": 0,
                                    "item": item,
                                    "sequence_number": sequence_number,
                                },
                            )
                            sequence_number += 1
                            output_item_added = True

                        if delta_function_call.get("name"):
                            tool_name, namespace = split_gigachat_tool_name(
                                delta_function_call["name"],
                                request_tools=(
                                    request_data.get("tools") if request_data else None
                                ),
                            )
                            function_call_data["name"] = tool_name
                            if namespace:
                                function_call_data["namespace"] = namespace

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
                        for event in emit_text_output_start_events():
                            yield event

                        full_text += delta_content
                        yield sse_event(
                            "response.output_text.delta",
                            {
                                "type": "response.output_text.delta",
                                "item_id": msg_id,
                                "output_index": text_output_index,
                                "content_index": 0,
                                "delta": delta_content,
                                "sequence_number": sequence_number,
                            },
                        )
                        sequence_number += 1
                        for event in emit_url_annotation_events(
                            include_unreferenced=False
                        ):
                            yield event

        if acquired_model_limit is not None:
            async for event in emit_upstream_events():
                yield event
        else:
            async with model_limiter.limit(effective_model, provider="openai"):
                async for event in emit_upstream_events():
                    yield event

        flushed_reasoning = reasoning_parser.flush()
        if flushed_reasoning.content:
            raw_full_text += flushed_reasoning.content
        if source_rendering_enabled:
            source_text = source_renderer.feed(flushed_reasoning.content)
            source_text += source_renderer.finish()
        else:
            source_text = flushed_reasoning.content
        if source_text:
            for event in emit_text_output_start_events():
                yield event
            full_text += source_text
            yield sse_event(
                "response.output_text.delta",
                {
                    "type": "response.output_text.delta",
                    "item_id": msg_id,
                    "output_index": text_output_index,
                    "content_index": 0,
                    "delta": source_text,
                    "sequence_number": sequence_number,
                },
            )
            sequence_number += 1
            for event in emit_url_annotation_events(include_unreferenced=False):
                yield event
        if flushed_reasoning.reasoning_content:
            reasoning_text += flushed_reasoning.reasoning_content

        if is_function_call and function_call_data:
            response_metadata["gigachat_called_tools"] = json.dumps(
                [
                    _stream_called_tool_item(
                        function_call_data,
                        tools_state_id=functions_state_id,
                    )
                ],
                ensure_ascii=False,
                separators=(",", ":"),
            )
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

            done_item = {
                "id": fc_id,
                "type": "function_call",
                "status": "completed",
                "call_id": f"call_{response_id}",
                "name": function_call_data["name"],
                "arguments": function_call_data["arguments"],
            }
            if function_call_data.get("namespace"):
                done_item["namespace"] = function_call_data["namespace"]
            yield sse_event(
                "response.output_item.done",
                {
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": done_item,
                    "sequence_number": sequence_number,
                },
            )
            sequence_number += 1

            final_output = [done_item]
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
                raw_full_text,
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
                    for event in emit_text_output_start_events():
                        yield event

                for event in emit_url_annotation_events(include_unreferenced=True):
                    yield event

                yield sse_event(
                    "response.output_text.done",
                    {
                        "type": "response.output_text.done",
                        "item_id": msg_id,
                        "output_index": text_output_index,
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
                        "output_index": text_output_index,
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
                        "output_index": text_output_index,
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
            for event in emit_pending_builtin_tool_done_events(builtin_items):
                yield event
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
        if logger:
            logger.error(f"[{rquid}] Unexpected streaming error: {error_type}: {e}")
        error_response = {
            "type": "error",
            "code": "internal_error",
            "message": "Stream interrupted",
            "param": None,
            "sequence_number": sequence_number,
        }
        yield sse_event("error", error_response)
    finally:
        if release_acquired_model_limit:
            await acquired_model_limit.__aexit__(None, None, None)


def _extract_provider_response_metadata(data: dict[str, Any]) -> dict[str, str]:
    raw_metadata = data.get(GIGACHAT_PROVIDER_METADATA_KEY)
    if not isinstance(raw_metadata, dict):
        return {}

    metadata: dict[str, str] = {}
    for key, value in raw_metadata.items():
        if isinstance(key, str) and isinstance(value, str):
            metadata[key] = value
    return metadata


def _stream_called_tool_item(
    function_call_data: dict[str, Any],
    *,
    tools_state_id: Optional[str],
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "index": 0,
        "name": function_call_data.get("name", ""),
        "arguments": _decode_stream_tool_arguments(
            function_call_data.get("arguments", "")
        ),
    }
    if tools_state_id:
        item["tools_state_id"] = tools_state_id
    if function_call_data.get("namespace"):
        item["namespace"] = function_call_data["namespace"]
    return item


def _decode_stream_tool_arguments(arguments: Any) -> Any:
    if not isinstance(arguments, str):
        return arguments
    try:
        return json.loads(arguments)
    except json.JSONDecodeError:
        return arguments
