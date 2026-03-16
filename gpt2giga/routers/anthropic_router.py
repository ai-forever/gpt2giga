"""Router for Anthropic Messages API compatibility.

Translates Anthropic Messages API requests to GigaChat format
and converts responses back to Anthropic format.
"""

import base64
import json
import traceback
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, AsyncGenerator, Dict, List, Optional

import gigachat
from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from gigachat import GigaChat

from gpt2giga.common.content_utils import ensure_json_object_str
from gpt2giga.common.exceptions import exceptions_handler
from gpt2giga.common.request_json import read_request_json
from gpt2giga.common.tools import convert_tool_to_giga_functions
from gpt2giga.common.tools import map_tool_name_from_gigachat
from gpt2giga.logger import rquid_context
from gpt2giga.openapi_docs import (
    anthropic_count_tokens_openapi_extra,
    anthropic_messages_openapi_extra,
)
from gpt2giga.protocol.batches import (
    extract_batch_result_body,
    get_batch_target,
    parse_jsonl,
    transform_batch_input_file,
)

router = APIRouter(tags=["Anthropic"])


# ---------------------------------------------------------------------------
# Request conversion helpers (Anthropic → OpenAI/GigaChat)
# ---------------------------------------------------------------------------


def _convert_anthropic_tools_to_openai(tools: List[Dict]) -> List[Dict]:
    """Convert Anthropic tool definitions to OpenAI format.

    Anthropic uses ``input_schema`` while OpenAI uses ``parameters``.
    """
    openai_tools: List[Dict] = []
    for tool in tools:
        openai_tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get(
                        "input_schema", {"type": "object", "properties": {}}
                    ),
                },
            }
        )
    return openai_tools


def _convert_anthropic_messages_to_openai(
    system: Optional[Any],
    messages: List[Dict],
) -> List[Dict]:
    """Convert Anthropic messages to OpenAI messages format.

    Handles system prompt, content blocks, tool_use, tool_result,
    and image content.
    """
    openai_messages: List[Dict] = []

    # Track tool_use id → function name for tool_result conversion
    tool_use_names: Dict[str, str] = {}

    # System prompt → system message
    if system:
        if isinstance(system, str):
            openai_messages.append({"role": "system", "content": system})
        elif isinstance(system, list):
            texts = [
                block.get("text", "")
                for block in system
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            if texts:
                openai_messages.append({"role": "system", "content": "\n".join(texts)})

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        # Simple string content
        if isinstance(content, str):
            openai_messages.append({"role": role, "content": content})
            continue

        if not isinstance(content, list):
            openai_messages.append({"role": role, "content": str(content)})
            continue

        # --- Content block arrays ---
        if role == "assistant":
            # Collect tool_use id → name for later tool_result references
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_use_names[block.get("id", "")] = block.get("name", "")
            _convert_assistant_blocks(content, openai_messages)
        elif role == "user":
            _convert_user_blocks(content, openai_messages, tool_use_names)
        else:
            openai_messages.append({"role": role, "content": str(content)})

    return openai_messages


def _convert_assistant_blocks(
    content_blocks: List[Dict],
    openai_messages: List[Dict],
) -> None:
    """Convert Anthropic assistant content blocks to OpenAI format."""
    text_parts: List[str] = []
    tool_uses: List[Dict] = []

    for block in content_blocks:
        btype = block.get("type")
        if btype == "text":
            text_parts.append(block.get("text", ""))
        elif btype == "tool_use":
            tool_uses.append(block)

    if tool_uses:
        tool_calls = [
            {
                "id": tu.get("id", f"call_{uuid.uuid4()}"),
                "type": "function",
                "function": {
                    "name": tu["name"],
                    "arguments": json.dumps(tu.get("input", {}), ensure_ascii=False),
                },
            }
            for tu in tool_uses
        ]
        openai_messages.append(
            {
                "role": "assistant",
                "content": "\n".join(text_parts) if text_parts else "",
                "tool_calls": tool_calls,
            }
        )
    else:
        openai_messages.append({"role": "assistant", "content": "\n".join(text_parts)})


def _convert_user_blocks(
    content_blocks: List[Dict],
    openai_messages: List[Dict],
    tool_use_names: Optional[Dict[str, str]] = None,
) -> None:
    """Convert Anthropic user content blocks (text, image, tool_result)."""
    text_parts: List[str] = []
    openai_content_parts: List[Dict] = []
    tool_results: List[Dict] = []
    has_images = False

    for block in content_blocks:
        btype = block.get("type")
        if btype == "text":
            text_parts.append(block.get("text", ""))
            openai_content_parts.append({"type": "text", "text": block.get("text", "")})
        elif btype == "image":
            has_images = True
            source = block.get("source", {})
            if source.get("type") == "base64":
                media_type = source.get("media_type", "image/png")
                data = source.get("data", "")
                url = f"data:{media_type};base64,{data}"
                openai_content_parts.append(
                    {"type": "image_url", "image_url": {"url": url}}
                )
            elif source.get("type") == "url":
                openai_content_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": source.get("url", "")},
                    }
                )
        elif btype == "tool_result":
            tool_results.append(block)

    # Emit tool results as function-role messages first
    names = tool_use_names or {}
    for tr in tool_results:
        tr_content = tr.get("content", "")
        if isinstance(tr_content, list):
            parts = [
                p.get("text", "")
                for p in tr_content
                if isinstance(p, dict) and p.get("type") == "text"
            ]
            tr_content = "\n".join(parts)
        tool_use_id = tr.get("tool_use_id", "")
        openai_messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_use_id,
                "name": names.get(tool_use_id, ""),
                "content": ensure_json_object_str(tr_content),
            }
        )

    # Emit text / image content
    if has_images and openai_content_parts:
        openai_messages.append({"role": "user", "content": openai_content_parts})
    elif text_parts:
        openai_messages.append({"role": "user", "content": "\n".join(text_parts)})


def _build_openai_data_from_anthropic_request(
    data: Dict[str, Any],
    logger: Any,
) -> Dict[str, Any]:
    """Translate an Anthropic Messages request into the OpenAI-style payload we reuse."""
    openai_data: Dict[str, Any] = {
        "model": data.get("model", "unknown"),
        "messages": _convert_anthropic_messages_to_openai(
            data.get("system"), data.get("messages", [])
        ),
    }

    if "max_tokens" in data:
        openai_data["max_tokens"] = data["max_tokens"]
    if "temperature" in data:
        openai_data["temperature"] = data["temperature"]
    if "top_p" in data:
        openai_data["top_p"] = data["top_p"]
    if "stop_sequences" in data:
        openai_data["stop"] = data["stop_sequences"]

    thinking = data.get("thinking")
    if thinking and isinstance(thinking, dict) and thinking.get("type") == "enabled":
        budget = thinking.get("budget_tokens", 10000)
        if budget >= 8000:
            openai_data["reasoning_effort"] = "high"
        elif budget >= 3000:
            openai_data["reasoning_effort"] = "medium"
        else:
            openai_data["reasoning_effort"] = "low"

    if "tools" in data and data["tools"]:
        openai_data["tools"] = _convert_anthropic_tools_to_openai(data["tools"])
        openai_data["functions"] = convert_tool_to_giga_functions(openai_data)
        if logger:
            logger.debug(f"Functions count: {len(openai_data['functions'])}")

    tool_choice = data.get("tool_choice")
    if tool_choice and isinstance(tool_choice, dict):
        tc_type = tool_choice.get("type")
        if tc_type == "tool":
            openai_data["function_call"] = {"name": tool_choice.get("name")}
        elif tc_type == "none":
            openai_data.pop("tools", None)
            openai_data.pop("functions", None)

    return openai_data


# ---------------------------------------------------------------------------
# Response conversion helpers (GigaChat → Anthropic)
# ---------------------------------------------------------------------------


def _map_stop_reason(finish_reason: Optional[str]) -> str:
    """Map GigaChat finish_reason to Anthropic stop_reason."""
    mapping = {
        "stop": "end_turn",
        "length": "max_tokens",
        "function_call": "tool_use",
        "content_filter": "end_turn",
    }
    return mapping.get(finish_reason or "stop", "end_turn")


def _build_anthropic_response(
    giga_dict: Dict,
    model: str,
    response_id: str,
) -> Dict:
    """Build Anthropic Messages API response from GigaChat response."""
    choice = giga_dict["choices"][0]
    message = choice.get("message", {})
    finish_reason = choice.get("finish_reason", "stop")
    usage = giga_dict.get("usage", {})

    content_blocks: List[Dict] = []

    # Add thinking block if GigaChat returned reasoning_content
    reasoning = message.get("reasoning_content")
    if reasoning:
        content_blocks.append({"type": "thinking", "thinking": reasoning})

    text_content = message.get("content", "") or ""
    if text_content:
        content_blocks.append({"type": "text", "text": text_content})

    tool_calls = list(message.get("tool_calls") or [])
    if message.get("function_call"):
        tool_calls.append({"function": message["function_call"]})

    if tool_calls:
        for tool_call in tool_calls:
            function = tool_call.get("function", {})
            args = function.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            elif not isinstance(args, dict):
                args = {}

            content_blocks.append(
                {
                    "type": "tool_use",
                    "id": tool_call.get("id") or f"toolu_{uuid.uuid4().hex[:24]}",
                    "name": map_tool_name_from_gigachat(function.get("name", "")),
                    "input": args,
                }
            )
        stop_reason = "tool_use"
    else:
        if not content_blocks:
            content_blocks.append({"type": "text", "text": ""})
        stop_reason = _map_stop_reason(finish_reason)

    return {
        "id": f"msg_{response_id}",
        "type": "message",
        "role": "assistant",
        "content": content_blocks,
        "model": model,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }


def _anthropic_http_exception(
    status_code: int,
    error_type: str,
    message: str,
) -> JSONResponse:
    """Build an Anthropic-style error response."""
    return JSONResponse(
        status_code=status_code,
        content={
            "type": "error",
            "error": {
                "type": error_type,
                "message": message,
            },
            "request_id": rquid_context.get(),
        },
    )


def _get_batch_store(request: Request) -> dict:
    state = request.app.state
    if not hasattr(state, "batch_metadata_store"):
        state.batch_metadata_store = {}
    return state.batch_metadata_store


def _get_file_store(request: Request) -> dict:
    state = request.app.state
    if not hasattr(state, "file_metadata_store"):
        state.file_metadata_store = {}
    return state.file_metadata_store


def _rfc3339_from_timestamp(timestamp: Optional[int]) -> Optional[str]:
    """Convert a Unix timestamp into Anthropic's RFC 3339 datetime format."""
    if timestamp is None:
        return None
    return (
        datetime.fromtimestamp(timestamp, tz=UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _build_anthropic_batch_request_counts(batch: Any, metadata: Dict[str, Any]) -> Dict:
    """Map GigaChat request counters onto Anthropic message batch counters."""
    request_counts = getattr(batch, "request_counts", None)
    total = getattr(request_counts, "total", None)
    if total is None:
        total = len(metadata.get("requests", []))

    status = getattr(batch, "status", None)
    failed = getattr(request_counts, "failed", None) or 0
    completed = getattr(request_counts, "completed", None)

    if status == "completed":
        succeeded = completed if completed is not None else max(total - failed, 0)
        errored = failed
        processing = max(total - succeeded - errored, 0)
    else:
        succeeded = 0
        errored = 0
        processing = total

    return {
        "canceled": 0,
        "errored": errored,
        "expired": 0,
        "processing": processing,
        "succeeded": succeeded,
    }


def _build_anthropic_batch_object(batch: Any, metadata: Dict[str, Any]) -> Dict:
    """Build an Anthropic-compatible message batch object."""
    batch_id = getattr(batch, "id_", "")
    created_at = getattr(batch, "created_at", None)
    processing_status = (
        "ended" if getattr(batch, "status", None) == "completed" else "in_progress"
    )
    output_file_id = getattr(batch, "output_file_id", None)

    expires_at = None
    if created_at is not None:
        expires_at = (
            datetime.fromtimestamp(created_at, tz=UTC) + timedelta(hours=24)
        ).isoformat(timespec="seconds").replace("+00:00", "Z")

    results_url = None
    if processing_status == "ended" and output_file_id:
        results_url = f"/v1/messages/batches/{batch_id}/results"

    return {
        "id": batch_id,
        "type": "message_batch",
        "archived_at": metadata.get("archived_at"),
        "cancel_initiated_at": metadata.get("cancel_initiated_at"),
        "created_at": _rfc3339_from_timestamp(created_at),
        "ended_at": (
            _rfc3339_from_timestamp(getattr(batch, "updated_at", None))
            if processing_status == "ended"
            else None
        ),
        "expires_at": expires_at,
        "processing_status": processing_status,
        "request_counts": _build_anthropic_batch_request_counts(batch, metadata),
        "results_url": results_url,
    }


def _build_anthropic_batch_error(error: Any, request_id: str) -> Dict:
    """Normalize a batch error payload to Anthropic's error response schema."""
    if isinstance(error, dict) and error.get("type") == "error" and isinstance(
        error.get("error"), dict
    ):
        return {
            "type": "error",
            "error": {
                "type": error["error"].get("type", "api_error"),
                "message": error["error"].get("message", "Unknown batch error."),
            },
            "request_id": error.get("request_id") or request_id,
        }

    if isinstance(error, dict):
        nested_error = error.get("error")
        if isinstance(nested_error, dict):
            error_type = nested_error.get("type", error.get("type", "api_error"))
            message = nested_error.get("message") or error.get("message")
        else:
            error_type = error.get("type", "api_error")
            message = error.get("message")
        if message is None:
            message = json.dumps(error, ensure_ascii=False)
    else:
        error_type = "api_error"
        message = str(error)

    return {
        "type": "error",
        "error": {
            "type": error_type,
            "message": message,
        },
        "request_id": request_id,
    }


def _paginate_anthropic_batches(
    items: List[Dict[str, Any]],
    *,
    after_id: Optional[str],
    before_id: Optional[str],
    limit: int,
) -> tuple[List[Dict[str, Any]], bool]:
    """Apply Anthropic-style cursor pagination to batch listings."""
    if after_id:
        for index, item in enumerate(items):
            if item.get("id") == after_id:
                items = items[index + 1 :]
                break

    if before_id:
        for index, item in enumerate(items):
            if item.get("id") == before_id:
                items = items[:index]
                break

    return items[:limit], len(items) > limit


def _build_anthropic_batch_results(
    output_content_b64: str,
    batch_metadata: Dict[str, Any],
) -> bytes:
    """Transform a GigaChat batch output file into Anthropic batch results JSONL."""
    output_rows = parse_jsonl(base64.b64decode(output_content_b64))
    requests_by_id = {
        row.get("custom_id"): row.get("params", {})
        for row in batch_metadata.get("requests", [])
        if isinstance(row, dict) and row.get("custom_id")
    }

    result_lines = []
    for index, row in enumerate(output_rows):
        custom_id = row.get("custom_id") or row.get("id") or f"batch-request-{index}"
        request_id = str(row.get("request_id") or row.get("id") or custom_id)
        response = row.get("response")
        status_code = 200
        if isinstance(response, dict):
            status_code = int(response.get("status_code", 200))

        raw_body = extract_batch_result_body(row)
        error = row.get("error")
        if status_code >= 400 or (
            error
            and "result" not in row
            and "response" not in row
            and "body" not in row
        ):
            anthropic_result = {
                "type": "errored",
                "error": _build_anthropic_batch_error(error or raw_body, request_id),
            }
        else:
            params = requests_by_id.get(custom_id, {})
            message_payload = raw_body
            if not isinstance(message_payload, dict):
                message_payload = {
                    "choices": [
                        {
                            "message": {"content": str(raw_body)},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {},
                }

            if isinstance(message_payload, dict) and message_payload.get("type") == "message":
                anthropic_message = message_payload
            else:
                anthropic_message = _build_anthropic_response(
                    message_payload,
                    params.get("model", "unknown"),
                    request_id,
                )

            anthropic_result = {
                "type": "succeeded",
                "message": anthropic_message,
            }

        result_lines.append(
            json.dumps(
                {
                    "custom_id": custom_id,
                    "result": anthropic_result,
                },
                ensure_ascii=False,
            )
        )

    return ("\n".join(result_lines) + ("\n" if result_lines else "")).encode("utf-8")


# ---------------------------------------------------------------------------
# Streaming generator
# ---------------------------------------------------------------------------


async def _stream_anthropic_generator(
    request: Request,
    model: str,
    chat_messages: Dict[str, Any],
    response_id: str,
    giga_client: GigaChat,
) -> AsyncGenerator[str, None]:
    """SSE generator producing Anthropic Messages streaming events."""
    logger = getattr(request.app.state, "logger", None)
    rquid = rquid_context.get()

    def sse(event_type: str, data: dict) -> str:
        return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"

    try:
        # message_start
        yield sse(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": f"msg_{response_id}",
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": model,
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            },
        )

        # ping
        yield sse("ping", {"type": "ping"})

        full_text = ""
        function_call_data: Optional[Dict[str, str]] = None
        content_block_started = False
        thinking_block_emitted = False
        content_index = 0  # current content block index
        output_tokens = 0

        async for chunk in giga_client.astream(chat_messages):
            if await request.is_disconnected():
                if logger:
                    logger.info(f"[{rquid}] Client disconnected during streaming")
                break

            giga_dict = chunk.model_dump()
            choice = giga_dict["choices"][0]
            delta = choice.get("delta", {})
            delta_content = delta.get("content", "")
            delta_fc = delta.get("function_call")
            delta_reasoning = delta.get("reasoning_content", "")

            # --- Reasoning / thinking ---
            if delta_reasoning and not thinking_block_emitted:
                yield sse(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": content_index,
                        "content_block": {"type": "thinking", "thinking": ""},
                    },
                )
                yield sse(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": content_index,
                        "delta": {
                            "type": "thinking_delta",
                            "thinking": delta_reasoning,
                        },
                    },
                )
                yield sse(
                    "content_block_stop",
                    {"type": "content_block_stop", "index": content_index},
                )
                content_index += 1
                thinking_block_emitted = True

            # --- Function call (tool_use) ---
            if delta_fc:
                if function_call_data is None:
                    tool_id = f"toolu_{uuid.uuid4().hex[:24]}"
                    function_call_data = {
                        "name": map_tool_name_from_gigachat(delta_fc.get("name", "")),
                        "arguments": "",
                        "tool_id": tool_id,
                    }
                    yield sse(
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": content_index,
                            "content_block": {
                                "type": "tool_use",
                                "id": tool_id,
                                "name": function_call_data["name"],
                                "input": {},
                            },
                        },
                    )
                    content_block_started = True

                if delta_fc.get("name"):
                    function_call_data["name"] = map_tool_name_from_gigachat(
                        delta_fc["name"]
                    )

                args = delta_fc.get("arguments")
                if args is not None:
                    args_str = (
                        json.dumps(args, ensure_ascii=False)
                        if isinstance(args, dict)
                        else str(args)
                    )
                    if args_str:
                        function_call_data["arguments"] += args_str
                        yield sse(
                            "content_block_delta",
                            {
                                "type": "content_block_delta",
                                "index": content_index,
                                "delta": {
                                    "type": "input_json_delta",
                                    "partial_json": args_str,
                                },
                            },
                        )

            # --- Text content ---
            elif delta_content:
                if not content_block_started:
                    yield sse(
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": content_index,
                            "content_block": {"type": "text", "text": ""},
                        },
                    )
                    content_block_started = True

                full_text += delta_content
                yield sse(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": content_index,
                        "delta": {
                            "type": "text_delta",
                            "text": delta_content,
                        },
                    },
                )

            # Track usage
            chunk_usage = giga_dict.get("usage")
            if chunk_usage and chunk_usage.get("completion_tokens"):
                output_tokens = chunk_usage["completion_tokens"]

        # --- Finalize ---
        stop_reason = "tool_use" if function_call_data else "end_turn"

        if content_block_started:
            yield sse(
                "content_block_stop",
                {"type": "content_block_stop", "index": content_index},
            )

        yield sse(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {
                    "stop_reason": stop_reason,
                    "stop_sequence": None,
                },
                "usage": {"output_tokens": output_tokens},
            },
        )

        yield sse("message_stop", {"type": "message_stop"})

    except gigachat.exceptions.GigaChatException as e:
        if logger:
            logger.error(f"[{rquid}] GigaChat streaming error: {type(e).__name__}: {e}")
        yield sse(
            "error",
            {
                "type": "error",
                "error": {"type": "api_error", "message": str(e)},
            },
        )

    except Exception as e:
        tb = traceback.format_exc()
        if logger:
            logger.error(
                f"[{rquid}] Unexpected streaming error: {type(e).__name__}: {e}\n{tb}"
            )
        yield sse(
            "error",
            {
                "type": "error",
                "error": {
                    "type": "api_error",
                    "message": f"Stream interrupted: {e}",
                },
            },
        )


# ---------------------------------------------------------------------------
# Token counting helpers
# ---------------------------------------------------------------------------


def _extract_text_from_openai_messages(messages: List[Dict]) -> List[str]:
    """Extract text strings from OpenAI-formatted messages for token counting.

    Concatenate all textual content from each message into a flat list of strings.
    """
    texts: List[str] = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            if content:
                texts.append(content)
        elif isinstance(content, list):
            # Multimodal content blocks (text parts only)
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = part.get("text", "")
                    if text:
                        texts.append(text)
        # Include tool/function call names and arguments as countable text
        for tc in msg.get("tool_calls", []):
            func = tc.get("function", {})
            name = func.get("name", "")
            args = func.get("arguments", "")
            if name:
                texts.append(name)
            if args:
                texts.append(args)
    return texts


def _extract_tool_definitions_text(tools: List[Dict]) -> List[str]:
    """Extract text from Anthropic tool definitions for token counting.

    Tool schemas consume tokens in the input context.
    """
    texts: List[str] = []
    for tool in tools:
        parts: List[str] = []
        name = tool.get("name", "")
        if name:
            parts.append(name)
        desc = tool.get("description", "")
        if desc:
            parts.append(desc)
        schema = tool.get("input_schema")
        if schema:
            parts.append(json.dumps(schema, ensure_ascii=False))
        if parts:
            texts.append(" ".join(parts))
    return texts


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/messages/count_tokens", openapi_extra=anthropic_count_tokens_openapi_extra()
)
@exceptions_handler
async def count_tokens(request: Request):
    """Anthropic Messages count_tokens API compatible endpoint.

    Count the number of tokens in a message request without creating a message.
    Uses GigaChat atokens_count for the actual counting.
    """
    data = await read_request_json(request)
    state = request.app.state
    giga_client = getattr(request.state, "gigachat_client", state.gigachat_client)

    model = data.get("model", "unknown")

    # Convert Anthropic messages → OpenAI messages (reuse existing conversion)
    openai_messages = _convert_anthropic_messages_to_openai(
        data.get("system"), data.get("messages", [])
    )

    # Extract all text content for token counting
    texts = _extract_text_from_openai_messages(openai_messages)

    # Include tool definitions in token count (they consume input tokens)
    if "tools" in data and data["tools"]:
        texts.extend(_extract_tool_definitions_text(data["tools"]))

    if not texts:
        return {"input_tokens": 0}

    # Call GigaChat token counting
    token_counts = await giga_client.atokens_count(texts, model=model)
    total_tokens = sum(tc.tokens for tc in token_counts)

    return {"input_tokens": total_tokens}


@router.post("/messages", openapi_extra=anthropic_messages_openapi_extra())
@exceptions_handler
async def messages(request: Request):
    """Anthropic Messages API compatible endpoint.

    Accept requests in Anthropic format, translate them to GigaChat,
    and return responses in Anthropic format.
    """
    data = await read_request_json(request)
    stream = data.get("stream", False)
    current_rquid = rquid_context.get()
    state = request.app.state
    giga_client = getattr(request.state, "gigachat_client", state.gigachat_client)

    model = data.get("model", "unknown")
    openai_data = _build_openai_data_from_anthropic_request(data, state.logger)

    # Use existing request transformer (OpenAI → GigaChat)
    chat_messages = await state.request_transformer.prepare_chat_completion(
        openai_data, giga_client
    )

    if not stream:
        response = await giga_client.achat(chat_messages)
        giga_dict = response.model_dump()
        return _build_anthropic_response(giga_dict, model, current_rquid)

    return StreamingResponse(
        _stream_anthropic_generator(
            request, model, chat_messages, current_rquid, giga_client
        ),
        media_type="text/event-stream",
    )


@router.post("/messages/batches")
@exceptions_handler
async def create_message_batch(request: Request):
    """Anthropic Message Batches API compatible create endpoint."""
    data = await read_request_json(request)
    requests_data = data.get("requests")
    if not isinstance(requests_data, list) or not requests_data:
        return _anthropic_http_exception(
            400,
            "invalid_request_error",
            "`requests` must be a non-empty array.",
        )

    seen_custom_ids = set()
    openai_rows = []
    stored_requests = []
    for index, batch_request in enumerate(requests_data, start=1):
        if not isinstance(batch_request, dict):
            return _anthropic_http_exception(
                400,
                "invalid_request_error",
                f"`requests[{index - 1}]` must be an object.",
            )

        custom_id = batch_request.get("custom_id")
        params = batch_request.get("params")
        if not isinstance(custom_id, str) or not custom_id:
            return _anthropic_http_exception(
                400,
                "invalid_request_error",
                f"`requests[{index - 1}].custom_id` must be a non-empty string.",
            )
        if custom_id in seen_custom_ids:
            return _anthropic_http_exception(
                400,
                "invalid_request_error",
                f"Duplicate `custom_id` detected: `{custom_id}`.",
            )
        if not isinstance(params, dict):
            return _anthropic_http_exception(
                400,
                "invalid_request_error",
                f"`requests[{index - 1}].params` must be an object.",
            )
        if params.get("stream"):
            return _anthropic_http_exception(
                400,
                "invalid_request_error",
                "Streaming requests are not supported inside message batches.",
            )

        seen_custom_ids.add(custom_id)
        openai_rows.append(
            {
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": _build_openai_data_from_anthropic_request(
                    params,
                    request.app.state.logger,
                ),
            }
        )
        stored_requests.append({"custom_id": custom_id, "params": params})

    target = get_batch_target("/v1/chat/completions")
    raw_input = ("\n".join(json.dumps(row, ensure_ascii=False) for row in openai_rows) + "\n").encode(
        "utf-8"
    )
    giga_client = getattr(
        request.state, "gigachat_client", request.app.state.gigachat_client
    )
    transformed_content = await transform_batch_input_file(
        raw_input,
        target=target,
        request_transformer=request.app.state.request_transformer,
        giga_client=giga_client,
        embeddings_model=request.app.state.config.proxy_settings.embeddings,
    )
    batch = await giga_client.acreate_batch(
        transformed_content,
        method=target.method,
    )

    metadata = {
        "api_format": "anthropic_messages",
        "requests": stored_requests,
        "output_file_id": batch.output_file_id,
    }
    _get_batch_store(request)[batch.id_] = metadata
    if batch.output_file_id:
        _get_file_store(request)[batch.output_file_id] = {"purpose": "batch_output"}
    return _build_anthropic_batch_object(batch, metadata)


@router.get("/messages/batches")
@exceptions_handler
async def list_message_batches(
    request: Request,
    after_id: Optional[str] = Query(default=None),
    before_id: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=1000),
):
    """Anthropic Message Batches API compatible list endpoint."""
    giga_client = getattr(
        request.state, "gigachat_client", request.app.state.gigachat_client
    )
    batch_store = _get_batch_store(request)
    file_store = _get_file_store(request)
    batches = await giga_client.aget_batches()

    data = []
    sorted_batches = sorted(
        batches.batches,
        key=lambda batch: getattr(batch, "created_at", 0),
        reverse=True,
    )
    for batch in sorted_batches:
        metadata = batch_store.get(batch.id_)
        if not metadata or metadata.get("api_format") != "anthropic_messages":
            continue
        metadata["output_file_id"] = batch.output_file_id
        batch_store[batch.id_] = metadata
        if batch.output_file_id:
            file_store[batch.output_file_id] = {"purpose": "batch_output"}
        data.append(_build_anthropic_batch_object(batch, metadata))

    paged, has_more = _paginate_anthropic_batches(
        data,
        after_id=after_id,
        before_id=before_id,
        limit=limit,
    )
    return {
        "data": paged,
        "has_more": has_more,
        "first_id": paged[0]["id"] if paged else None,
        "last_id": paged[-1]["id"] if paged else None,
    }


@router.get("/messages/batches/{message_batch_id}")
@exceptions_handler
async def retrieve_message_batch(message_batch_id: str, request: Request):
    """Anthropic Message Batches API compatible retrieve endpoint."""
    batch_store = _get_batch_store(request)
    metadata = batch_store.get(message_batch_id)
    if not metadata or metadata.get("api_format") != "anthropic_messages":
        return _anthropic_http_exception(
            404,
            "not_found_error",
            f"Message batch `{message_batch_id}` not found.",
        )

    giga_client = getattr(
        request.state, "gigachat_client", request.app.state.gigachat_client
    )
    batches = await giga_client.aget_batches(batch_id=message_batch_id)
    if not batches.batches:
        return _anthropic_http_exception(
            404,
            "not_found_error",
            f"Message batch `{message_batch_id}` not found.",
        )

    batch = batches.batches[0]
    metadata["output_file_id"] = batch.output_file_id
    batch_store[message_batch_id] = metadata
    if batch.output_file_id:
        _get_file_store(request)[batch.output_file_id] = {"purpose": "batch_output"}
    return _build_anthropic_batch_object(batch, metadata)


@router.post("/messages/batches/{message_batch_id}/cancel")
@exceptions_handler
async def cancel_message_batch(message_batch_id: str, request: Request):
    """Surface the unsupported cancel capability with an Anthropic-style error."""
    batch_store = _get_batch_store(request)
    metadata = batch_store.get(message_batch_id)
    if not metadata or metadata.get("api_format") != "anthropic_messages":
        return _anthropic_http_exception(
            404,
            "not_found_error",
            f"Message batch `{message_batch_id}` not found.",
        )
    return _anthropic_http_exception(
        501,
        "api_error",
        "Message batch cancellation is not supported by the configured GigaChat backend.",
    )


@router.delete("/messages/batches/{message_batch_id}")
@exceptions_handler
async def delete_message_batch(message_batch_id: str, request: Request):
    """Surface the unsupported delete capability with an Anthropic-style error."""
    batch_store = _get_batch_store(request)
    metadata = batch_store.get(message_batch_id)
    if not metadata or metadata.get("api_format") != "anthropic_messages":
        return _anthropic_http_exception(
            404,
            "not_found_error",
            f"Message batch `{message_batch_id}` not found.",
        )
    return _anthropic_http_exception(
        501,
        "api_error",
        "Message batch deletion is not supported by the configured GigaChat backend.",
    )


@router.get("/messages/batches/{message_batch_id}/results")
@exceptions_handler
async def get_message_batch_results(message_batch_id: str, request: Request):
    """Anthropic Message Batches API compatible results endpoint."""
    batch_store = _get_batch_store(request)
    metadata = batch_store.get(message_batch_id)
    if not metadata or metadata.get("api_format") != "anthropic_messages":
        return _anthropic_http_exception(
            404,
            "not_found_error",
            f"Message batch `{message_batch_id}` not found.",
        )

    giga_client = getattr(
        request.state, "gigachat_client", request.app.state.gigachat_client
    )
    batches = await giga_client.aget_batches(batch_id=message_batch_id)
    if not batches.batches:
        return _anthropic_http_exception(
            404,
            "not_found_error",
            f"Message batch `{message_batch_id}` not found.",
        )

    batch = batches.batches[0]
    metadata["output_file_id"] = batch.output_file_id
    batch_store[message_batch_id] = metadata
    if getattr(batch, "status", None) != "completed" or not batch.output_file_id:
        return _anthropic_http_exception(
            409,
            "invalid_request_error",
            "Results are not available until message batch processing has ended.",
        )

    file_response = await giga_client.aget_file_content(file_id=batch.output_file_id)
    content = _build_anthropic_batch_results(file_response.content, metadata)
    return Response(content=content, media_type="application/binary")
