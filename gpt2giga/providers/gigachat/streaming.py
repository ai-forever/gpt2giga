"""GigaChat provider streaming helpers."""

from __future__ import annotations

import traceback
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from typing import Any, Optional, Protocol, TypeAlias, TypeVar

import gigachat

from gpt2giga.app.observability import set_request_audit_error
from gpt2giga.features.chat.contracts import ChatProviderMapper, PreparedChatRequest
from gpt2giga.features.responses.contracts import PreparedResponsesRequest
from gpt2giga.providers.gigachat.tool_mapping import map_tool_name_from_gigachat

StreamChunkT = TypeVar("StreamChunkT")


class GigaChatStreamError(Exception):
    """Wrap provider streaming errors in a provider-owned exception."""

    def __init__(
        self,
        *,
        error_type: str,
        message: str,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message
        self.status_code = status_code

    @classmethod
    def from_exception(
        cls, exc: gigachat.exceptions.GigaChatException
    ) -> "GigaChatStreamError":
        """Build a provider stream error from a GigaChat SDK exception."""
        return cls(
            error_type=type(exc).__name__,
            message=str(exc),
            status_code=getattr(exc, "status_code", None),
        )


@dataclass(slots=True)
class StreamFailure:
    """Normalized stream-failure state shared by transport presenters."""

    error_type: str
    message: str
    code: str
    status_code: int | None = None


class GigaChatResponsesStreamProcessor(Protocol):
    """Private response-processor helpers needed for Responses streaming."""

    def _safe_model_dump(self, giga_resp: Any) -> dict[str, Any]:
        """Dump a GigaChat model into a dictionary."""

    def _build_response_usage_v2(
        self, usage: Optional[dict[str, Any]]
    ) -> Optional[dict[str, Any]]:
        """Normalize Responses API usage payload."""

    def _stringify_json(self, value: Any) -> str:
        """Convert JSON-like content into a streamed string delta."""

    def _build_builtin_tool_output_item(
        self,
        *,
        tool_name: str,
        item_id: str,
        tools_state_id: Optional[str],
        response_status: str,
        raw_status: Optional[str],
        related_files: Optional[list[dict[str, Any]]] = None,
        additional_data: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        """Build a Responses API builtin tool output item."""


@dataclass(slots=True)
class ResponsesTextUpdate:
    """Normalized text delta from a GigaChat Responses stream chunk."""

    message_key: str
    item_id: str
    text: str


@dataclass(slots=True)
class ResponsesFunctionCallUpdate:
    """Normalized function-call delta from a GigaChat Responses chunk."""

    call_key: str
    item_id: str
    call_id: str
    name: str | None
    arguments: str


@dataclass(slots=True)
class ResponsesToolUpdate:
    """Normalized builtin-tool update from a GigaChat Responses chunk."""

    tool_key: str
    item_id: str
    tool_name: str
    tools_state_id: str | None
    output_item: dict[str, Any]
    raw_status: str | None


ResponsesStreamUpdate: TypeAlias = (
    ResponsesTextUpdate | ResponsesFunctionCallUpdate | ResponsesToolUpdate
)


@dataclass(slots=True)
class ResponsesStreamChunk:
    """Provider-normalized view of a single Responses stream chunk."""

    model: str | None = None
    created_at: int | None = None
    thread_id: str | None = None
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None
    updates: list[ResponsesStreamUpdate] = field(default_factory=list)


async def iter_stream_with_disconnect(
    request: Any,
    stream_iter: AsyncIterator[StreamChunkT],
    *,
    logger: Any = None,
    rquid: str | None = None,
) -> AsyncIterator[StreamChunkT]:
    """Yield stream chunks until the client disconnects."""
    async for chunk in stream_iter:
        if await request.is_disconnected():
            if logger:
                logger.info(f"{_log_prefix(rquid)}Client disconnected during streaming")
            break
        yield chunk


def report_stream_failure(
    request: Any,
    exc: Exception,
    *,
    logger: Any = None,
    rquid: str | None = None,
    unexpected_log_label: str = "Unexpected streaming error",
) -> StreamFailure:
    """Normalize, audit, and log a stream failure."""
    if isinstance(exc, gigachat.exceptions.GigaChatException):
        exc = GigaChatStreamError.from_exception(exc)

    if isinstance(exc, GigaChatStreamError):
        set_request_audit_error(request, exc.error_type)
        if logger:
            logger.error(
                f"{_log_prefix(rquid)}GigaChat streaming error: "
                f"{exc.error_type}: {exc.message}"
            )
        return StreamFailure(
            error_type=exc.error_type,
            message=exc.message,
            code="stream_error",
            status_code=exc.status_code,
        )

    error_type = type(exc).__name__
    set_request_audit_error(request, error_type)
    if logger:
        logger.error(
            f"{_log_prefix(rquid)}{unexpected_log_label}: "
            f"{error_type}: {exc}\n{traceback.format_exc()}"
        )
    return StreamFailure(
        error_type=error_type,
        message="Stream interrupted",
        code="internal_error",
    )


async def iter_chat_stream_chunks(
    giga_client: Any,
    chat_messages: PreparedChatRequest,
) -> AsyncIterator[Any]:
    """Yield raw GigaChat chat stream chunks."""
    try:
        async for chunk in giga_client.astream(chat_messages):
            yield chunk
    except gigachat.exceptions.GigaChatException as exc:
        raise GigaChatStreamError.from_exception(exc) from exc


async def iter_chat_v2_stream_chunks(
    giga_client: Any,
    chat_messages: PreparedChatRequest,
) -> AsyncIterator[Any]:
    """Yield raw GigaChat v2 chat stream chunks."""
    try:
        async for chunk in giga_client.astream_v2(chat_messages):
            yield chunk
    except gigachat.exceptions.GigaChatException as exc:
        raise GigaChatStreamError.from_exception(exc) from exc


def map_chat_stream_chunk(
    chunk: Any,
    *,
    mapper: ChatProviderMapper,
    model: str,
    response_id: str,
    request_data: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Map a raw GigaChat chat chunk into the external chat stream shape."""
    return mapper.process_stream_chunk(
        chunk,
        model,
        response_id,
        request_data=request_data,
    )


def _looks_like_generated_image_files(files: list[Any]) -> bool:
    """Return True when file parts look like model-generated image outputs."""
    for file_desc in files:
        if not isinstance(file_desc, dict):
            continue
        if file_desc.get("target") == "image":
            return True
        mime = file_desc.get("mime")
        if isinstance(mime, str) and mime.startswith("image/"):
            return True
    return False


async def iter_responses_stream_chunks(
    giga_client: Any,
    chat_messages: PreparedResponsesRequest,
    *,
    response_processor: GigaChatResponsesStreamProcessor,
    response_id: str,
) -> AsyncIterator[ResponsesStreamChunk]:
    """Yield provider-normalized Responses API stream chunks."""
    last_tool_state: dict[str, ResponsesToolUpdate] = {}
    try:
        async for chunk in giga_client.astream_v2(chat_messages):
            chunk_dict = response_processor._safe_model_dump(chunk)
            yield ResponsesStreamChunk(
                model=chunk_dict.get("model"),
                created_at=chunk_dict.get("created_at"),
                thread_id=chunk_dict.get("thread_id"),
                finish_reason=chunk_dict.get("finish_reason"),
                usage=response_processor._build_response_usage_v2(
                    chunk_dict.get("usage")
                ),
                updates=_collect_responses_updates(
                    chunk_dict,
                    response_processor=response_processor,
                    response_id=response_id,
                    last_tool_state=last_tool_state,
                ),
            )
    except gigachat.exceptions.GigaChatException as exc:
        raise GigaChatStreamError.from_exception(exc) from exc


def _collect_responses_updates(
    chunk_dict: dict[str, Any],
    *,
    response_processor: GigaChatResponsesStreamProcessor,
    response_id: str,
    last_tool_state: dict[str, ResponsesToolUpdate],
) -> list[ResponsesStreamUpdate]:
    updates: list[ResponsesStreamUpdate] = []
    raw_additional_data = chunk_dict.get("additional_data")
    additional_data = (
        raw_additional_data if isinstance(raw_additional_data, dict) else None
    )

    for message_index, message in enumerate(chunk_dict.get("messages") or []):
        if not isinstance(message, dict):
            continue

        message_id = str(
            message.get("message_id") or f"msg_{response_id}_{message_index}"
        )
        message_key = message_id
        tools_state_id = message.get("tools_state_id")
        last_tool_update: ResponsesToolUpdate | None = last_tool_state.get(message_key)

        for part_index, part in enumerate(message.get("content") or []):
            if not isinstance(part, dict):
                continue

            text = part.get("text")
            if isinstance(text, str):
                updates.append(
                    ResponsesTextUpdate(
                        message_key=message_key,
                        item_id=message_id,
                        text=text,
                    )
                )

            function_call = part.get("function_call")
            if isinstance(function_call, dict):
                call_id = (
                    str(tools_state_id)
                    if tools_state_id is not None
                    else f"call_{message_id}_{part_index}"
                )
                name = function_call.get("name")
                mapped_name = (
                    map_tool_name_from_gigachat(name)
                    if isinstance(name, str) and name
                    else None
                )
                updates.append(
                    ResponsesFunctionCallUpdate(
                        call_key=call_id,
                        item_id=f"fc_{call_id}",
                        call_id=call_id,
                        name=mapped_name,
                        arguments=response_processor._stringify_json(
                            function_call.get("arguments")
                        ),
                    )
                )

            tool_execution = part.get("tool_execution")
            if isinstance(tool_execution, dict):
                tool_name = tool_execution.get("name")
                if isinstance(tool_name, str) and tool_name:
                    item_id = f"tool_{tools_state_id or message_id}_{part_index}"
                    output_item = response_processor._build_builtin_tool_output_item(
                        tool_name=tool_name,
                        item_id=item_id,
                        tools_state_id=tools_state_id,
                        response_status="in_progress",
                        raw_status=tool_execution.get("status"),
                        additional_data=additional_data,
                    )
                    if output_item is not None:
                        last_tool_update = ResponsesToolUpdate(
                            tool_key=f"{tools_state_id or message_id}:{tool_name}",
                            item_id=item_id,
                            tool_name=tool_name,
                            tools_state_id=(
                                str(tools_state_id)
                                if tools_state_id is not None
                                else None
                            ),
                            output_item=output_item,
                            raw_status=tool_execution.get("status"),
                        )
                        last_tool_state[message_key] = last_tool_update
                        updates.append(
                            replace(last_tool_update, output_item=dict(output_item))
                        )

            files = part.get("files")
            if isinstance(files, list):
                if last_tool_update is None and _looks_like_generated_image_files(
                    files
                ):
                    item_id = f"tool_{tools_state_id or message_id}_{part_index}"
                    output_item = response_processor._build_builtin_tool_output_item(
                        tool_name="image_generate",
                        item_id=item_id,
                        tools_state_id=(
                            str(tools_state_id) if tools_state_id is not None else None
                        ),
                        response_status="in_progress",
                        raw_status="completed",
                        related_files=files,
                        additional_data=additional_data,
                    )
                    if output_item is not None:
                        last_tool_update = ResponsesToolUpdate(
                            tool_key=f"{tools_state_id or message_id}:image_generate",
                            item_id=item_id,
                            tool_name="image_generate",
                            tools_state_id=(
                                str(tools_state_id)
                                if tools_state_id is not None
                                else None
                            ),
                            output_item=output_item,
                            raw_status="completed",
                        )
                        last_tool_state[message_key] = last_tool_update
                        updates.append(
                            replace(last_tool_update, output_item=dict(output_item))
                        )
                elif last_tool_update is not None:
                    output_item = response_processor._build_builtin_tool_output_item(
                        tool_name=last_tool_update.tool_name,
                        item_id=last_tool_update.item_id,
                        tools_state_id=last_tool_update.tools_state_id,
                        response_status="in_progress",
                        raw_status=last_tool_update.raw_status,
                        related_files=files,
                        additional_data=additional_data,
                    )
                    if output_item is not None:
                        last_tool_update.output_item = output_item
                        last_tool_state[message_key] = last_tool_update
                        updates.append(
                            replace(last_tool_update, output_item=dict(output_item))
                        )

    return updates


def _log_prefix(rquid: str | None) -> str:
    return f"[{rquid}] " if rquid else ""
